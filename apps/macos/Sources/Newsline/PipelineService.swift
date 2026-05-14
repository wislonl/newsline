import Foundation

/// Runs `news run` in a subprocess so the toolbar refresh button can
/// actually fetch + score + match, not just re-read the DB.
///
/// Streams stdout line-by-line into an `onProgress` callback so the UI
/// can show what the daemon is doing in real time (📥 Stored 5 items,
/// 🤖 Scoring 5 items, etc.).
struct PipelineService {
    enum PipelineError: LocalizedError {
        case uvNotFound
        case projectNotFound(String)
        case processFailed(exitCode: Int32, stderr: String)

        var errorDescription: String? {
            switch self {
            case .uvNotFound:
                return "uv not found. Install uv or set $NEWSLINE_UV."
            case .projectNotFound(let path):
                return "newsline project not found at \(path). Set $NEWSLINE_HOME."
            case .processFailed(let code, let err):
                return "newsline run exited \(code): \(err.isEmpty ? "(no stderr)" : err)"
            }
        }
    }

    /// Run `news run`. `onProgress` fires on the main queue for each stdout
    /// line. Throws on non-zero exit.
    func run(onProgress: @escaping (String) -> Void) async throws {
        guard let uv = ChatService.uvPath() else { throw PipelineError.uvNotFound }
        let project = ChatService.projectDir()
        guard FileManager.default.fileExists(atPath: project + "/pyproject.toml") else {
            throw PipelineError.projectNotFound(project)
        }

        let p = Process()
        p.executableURL = URL(fileURLWithPath: uv)
        p.arguments = ["run", "--quiet", "--directory", project, "newsline", "run"]
        let out = Pipe(), err = Pipe()
        p.standardOutput = out
        p.standardError = err

        var env = ProcessInfo.processInfo.environment
        env["NO_COLOR"] = "1"
        p.environment = env

        // Tail stdout for progress lines.
        out.fileHandleForReading.readabilityHandler = { handle in
            let data = handle.availableData
            guard !data.isEmpty, let s = String(data: data, encoding: .utf8) else { return }
            for line in s.split(separator: "\n", omittingEmptySubsequences: true) {
                let text = String(line)
                DispatchQueue.main.async { onProgress(text) }
            }
        }

        try p.run()

        // Wait without blocking the calling actor.
        try await withCheckedThrowingContinuation { (cont: CheckedContinuation<Void, Error>) in
            DispatchQueue.global(qos: .utility).async {
                p.waitUntilExit()
                out.fileHandleForReading.readabilityHandler = nil
                let stderr = String(data: err.fileHandleForReading.readDataToEndOfFile(),
                                    encoding: .utf8) ?? ""
                if p.terminationStatus == 0 {
                    cont.resume()
                } else {
                    cont.resume(throwing: PipelineError.processFailed(
                        exitCode: p.terminationStatus,
                        stderr: stderr.trimmingCharacters(in: .whitespacesAndNewlines)))
                }
            }
        }
    }
}
