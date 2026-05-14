import Foundation

/// Watches the SQLite database for writes and fires a debounced callback.
///
/// In WAL mode the daemon writes to `<db>-wal` first and only periodically
/// checkpoints back into the main `<db>` file. We arm two file watchers —
/// one per file — so the UI refreshes on every commit, not just on
/// checkpoints. The `-wal` file may not exist at startup; we re-arm via
/// a 1s poll loop once it appears.
final class DBWatcher {
    private let paths: [String]
    private let onChange: () -> Void
    private let queue = DispatchQueue(label: "newsline.dbwatcher")
    private let debounce: DispatchTimeInterval = .milliseconds(250)

    private var sources: [String: DispatchSourceFileSystemObject] = [:]
    private var pendingFire: DispatchWorkItem?
    private var reopenTimer: DispatchSourceTimer?

    init(dbPath: String, onChange: @escaping () -> Void) {
        self.paths = [dbPath, dbPath + "-wal"]
        self.onChange = onChange
    }

    func start() {
        queue.async { [weak self] in self?.armAll() }
    }

    func stop() {
        queue.async { [weak self] in
            self?.sources.values.forEach { $0.cancel() }
            self?.sources.removeAll()
            self?.reopenTimer?.cancel()
            self?.reopenTimer = nil
        }
    }

    // MARK: - private

    private func armAll() {
        var anyMissing = false
        for path in paths where sources[path] == nil {
            if !arm(path: path) { anyMissing = true }
        }
        if anyMissing { scheduleReopen() }
    }

    /// Returns true if armed, false if the file didn't exist yet.
    private func arm(path: String) -> Bool {
        let fd = Darwin.open(path, O_EVTONLY)
        if fd == -1 { return false }
        let mask: DispatchSource.FileSystemEvent = [.write, .extend, .delete, .rename, .revoke]
        let s = DispatchSource.makeFileSystemObjectSource(
            fileDescriptor: fd, eventMask: mask, queue: queue
        )
        s.setEventHandler { [weak self] in
            guard let self else { return }
            let events = s.data
            if events.intersection([.delete, .rename, .revoke]).isEmpty {
                self.scheduleFire()
            } else {
                s.cancel()
                self.sources.removeValue(forKey: path)
                self.scheduleReopen()
            }
        }
        s.setCancelHandler { Darwin.close(fd) }
        s.resume()
        sources[path] = s
        return true
    }

    private func scheduleFire() {
        pendingFire?.cancel()
        let work = DispatchWorkItem { [weak self] in
            guard let self else { return }
            DispatchQueue.main.async { self.onChange() }
        }
        pendingFire = work
        queue.asyncAfter(deadline: .now() + debounce, execute: work)
    }

    private func scheduleReopen() {
        guard reopenTimer == nil else { return }
        let t = DispatchSource.makeTimerSource(queue: queue)
        t.schedule(deadline: .now() + 1.0, repeating: 1.0)
        t.setEventHandler { [weak self] in
            guard let self else { return }
            var fired = false
            for path in self.paths where self.sources[path] == nil {
                if FileManager.default.fileExists(atPath: path), self.arm(path: path) {
                    fired = true
                }
            }
            // If everything is armed, stop polling.
            let allArmed = self.paths.allSatisfy { self.sources[$0] != nil }
            if allArmed {
                self.reopenTimer?.cancel()
                self.reopenTimer = nil
            }
            if fired { self.scheduleFire() }
        }
        t.resume()
        reopenTimer = t
    }
}
