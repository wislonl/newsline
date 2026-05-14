import Foundation

/// Spawns `newsline serve` as a child process on app launch and lets callers
/// stream chat responses from it without paying the subprocess fork-and-import
/// cost on every question.
///
/// Lifecycle: started lazily on the first request that needs it; killed by
/// AppDelegate.applicationWillTerminate. If the process dies the next
/// request restarts it automatically.
@MainActor
final class Sidecar {
    private(set) var baseURL: URL?
    private var process: Process?
    private let port: Int = 8137  // localhost only
    private var startTask: Task<URL, Error>?

    /// Returns the base URL once the server is reachable. Idempotent.
    func ensureRunning() async throws -> URL {
        if let baseURL { return baseURL }
        if let t = startTask { return try await t.value }

        let task = Task<URL, Error> { try await self.start() }
        startTask = task
        defer { startTask = nil }
        let url = try await task.value
        self.baseURL = url
        return url
    }

    func shutdown() {
        process?.terminate()
        process = nil
        baseURL = nil
    }

    // MARK: - private

    private func start() async throws -> URL {
        guard let uv = ChatService.uvPath() else { throw ChatService.ChatError.uvNotFound }
        let project = ChatService.projectDir()
        guard FileManager.default.fileExists(atPath: project + "/pyproject.toml") else {
            throw ChatService.ChatError.projectNotFound(project)
        }

        let p = Process()
        p.executableURL = URL(fileURLWithPath: uv)
        p.arguments = [
            "run", "--quiet", "--directory", project,
            "newsline", "serve", "--port", String(port),
        ]
        // Send stdout/stderr to /dev/null — we only care about the health check.
        p.standardOutput = FileHandle(forWritingAtPath: "/dev/null") ?? Pipe().fileHandleForWriting
        p.standardError = FileHandle(forWritingAtPath: "/dev/null") ?? Pipe().fileHandleForWriting

        var env = ProcessInfo.processInfo.environment
        env["NO_COLOR"] = "1"
        p.environment = env

        try p.run()
        process = p

        let url = URL(string: "http://127.0.0.1:\(port)")!
        try await waitHealthy(base: url, timeout: 10.0)
        return url
    }

    private func waitHealthy(base: URL, timeout: TimeInterval) async throws {
        let healthz = base.appendingPathComponent("healthz")
        let deadline = Date().addingTimeInterval(timeout)
        var attempt = 0
        while Date() < deadline {
            attempt += 1
            do {
                let (data, resp) = try await URLSession.shared.data(from: healthz)
                if let http = resp as? HTTPURLResponse, http.statusCode == 200,
                   String(data: data, encoding: .utf8)?.contains("\"ok\"") == true {
                    return
                }
            } catch { /* not up yet */ }
            try? await Task.sleep(nanoseconds: 200_000_000)  // 200ms
        }
        throw ChatService.ChatError.processFailed(
            exitCode: -1,
            stderr: "newsline serve did not become healthy after \(timeout)s")
    }
}
