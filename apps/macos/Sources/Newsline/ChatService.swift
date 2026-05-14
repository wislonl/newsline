import Foundation

/// Asks the Python pipeline for a grounded answer about one story.
///
/// Implementation: shells out to `uv run --directory <project> newsline chat <id> <q>`
/// and returns stdout. One subprocess per question — fine at human typing speed.
/// Will be replaced with a longer-lived sidecar if/when streaming or chat
/// history persistence matter.
struct ChatService {
    enum ChatError: LocalizedError {
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
                return "newsline chat exited \(code): \(err.isEmpty ? "(no stderr)" : err)"
            }
        }
    }

    private static let env = ProcessInfo.processInfo.environment

    /// Look for the python project root.
    static func projectDir() -> String {
        if let p = env["NEWSLINE_HOME"] { return (p as NSString).expandingTildeInPath }
        return (NSString(string: "~/Documents/newsline").expandingTildeInPath as String)
    }

    /// Find uv. GUI apps don't inherit a useful PATH, so check well-known
    /// install locations directly.
    static func uvPath() -> String? {
        if let p = env["NEWSLINE_UV"], FileManager.default.isExecutableFile(atPath: p) {
            return p
        }
        let candidates = [
            "\(NSHomeDirectory())/.local/bin/uv",
            "/opt/homebrew/bin/uv",
            "/usr/local/bin/uv",
        ]
        return candidates.first { FileManager.default.isExecutableFile(atPath: $0) }
    }

    func ask(storyID: String, question: String) async throws -> String {
        guard let uv = Self.uvPath() else { throw ChatError.uvNotFound }
        let project = Self.projectDir()
        guard FileManager.default.fileExists(atPath: project + "/pyproject.toml") else {
            throw ChatError.projectNotFound(project)
        }

        return try await withCheckedThrowingContinuation { cont in
            let p = Process()
            p.executableURL = URL(fileURLWithPath: uv)
            p.arguments = [
                "run", "--quiet",
                "--directory", project,
                "newsline", "chat", storyID, question,
            ]
            let out = Pipe(), err = Pipe()
            p.standardOutput = out
            p.standardError = err

            // Inherit PATH but don't depend on it for uv itself.
            var env = ProcessInfo.processInfo.environment
            env["NO_COLOR"] = "1"
            p.environment = env

            p.terminationHandler = { proc in
                let stdout = String(data: out.fileHandleForReading.readDataToEndOfFile(),
                                    encoding: .utf8) ?? ""
                let stderr = String(data: err.fileHandleForReading.readDataToEndOfFile(),
                                    encoding: .utf8) ?? ""
                if proc.terminationStatus == 0 {
                    cont.resume(returning: stdout.trimmingCharacters(in: .whitespacesAndNewlines))
                } else {
                    cont.resume(throwing: ChatError.processFailed(
                        exitCode: proc.terminationStatus,
                        stderr: stderr.trimmingCharacters(in: .whitespacesAndNewlines)))
                }
            }

            do { try p.run() } catch { cont.resume(throwing: error) }
        }
    }
}
