import Foundation

/// Watches the newsline.db file for writes and fires a debounced callback.
///
/// SQLite in rollback-journal mode modifies the main .db file on every commit,
/// so a plain DispatchSource watcher catches updates. If the file is deleted
/// (e.g. by the user wiping data) we re-arm whenever it reappears.
final class DBWatcher {
    private let path: String
    private let onChange: () -> Void
    private let queue = DispatchQueue(label: "newsline.dbwatcher")
    private let debounce: DispatchTimeInterval = .milliseconds(250)

    private var source: DispatchSourceFileSystemObject?
    private var pendingFire: DispatchWorkItem?
    private var reopenTimer: DispatchSourceTimer?

    init(path: String, onChange: @escaping () -> Void) {
        self.path = path
        self.onChange = onChange
    }

    func start() {
        queue.async { [weak self] in self?.arm() }
    }

    func stop() {
        queue.async { [weak self] in
            self?.source?.cancel()
            self?.source = nil
            self?.reopenTimer?.cancel()
            self?.reopenTimer = nil
        }
    }

    // MARK: - private

    private func arm() {
        guard source == nil else { return }
        let fd = Darwin.open(path, O_EVTONLY)
        if fd == -1 {
            scheduleReopen()
            return
        }
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
                self.source = nil
                self.scheduleReopen()
            }
        }
        s.setCancelHandler { Darwin.close(fd) }
        s.resume()
        source = s
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
        reopenTimer?.cancel()
        let t = DispatchSource.makeTimerSource(queue: queue)
        t.schedule(deadline: .now() + 1.0, repeating: 1.0)
        t.setEventHandler { [weak self] in
            guard let self else { return }
            if FileManager.default.fileExists(atPath: self.path) {
                self.reopenTimer?.cancel()
                self.reopenTimer = nil
                self.arm()
                self.scheduleFire()  // user may have just imported fresh data
            }
        }
        t.resume()
        reopenTimer = t
    }
}
