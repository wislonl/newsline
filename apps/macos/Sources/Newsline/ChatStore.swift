import Foundation
import SQLite3

/// Persists chat_messages so closing the app doesn't wipe your conversations.
final class ChatStore {
    private let dbURL: URL

    init(dbURL: URL) {
        self.dbURL = dbURL
    }

    func load(storyID: String) -> [ChatMessage] {
        var db: OpaquePointer?
        guard sqlite3_open_v2(dbURL.path,
                              &db,
                              SQLITE_OPEN_READWRITE | SQLITE_OPEN_NOMUTEX,
                              nil) == SQLITE_OK else {
            if let db { sqlite3_close(db) }
            return []
        }
        defer { sqlite3_close(db) }

        var stmt: OpaquePointer?
        let sql = "SELECT role, text FROM chat_messages WHERE story_id = ? ORDER BY id ASC"
        guard sqlite3_prepare_v2(db, sql, -1, &stmt, nil) == SQLITE_OK else { return [] }
        defer { sqlite3_finalize(stmt) }
        sqlite3_bind_text(stmt, 1, (storyID as NSString).utf8String, -1, nil)

        var out: [ChatMessage] = []
        while sqlite3_step(stmt) == SQLITE_ROW {
            let role = sqlite3_column_text(stmt, 0).map { String(cString: $0) } ?? ""
            let text = sqlite3_column_text(stmt, 1).map { String(cString: $0) } ?? ""
            let kind: ChatMessage.Role =
                role == "assistant" ? .assistant : .user
            out.append(ChatMessage(role: kind, text: text))
        }
        return out
    }

    /// Append a finalized message. Drafts (empty text) are not written.
    func append(storyID: String, role: ChatMessage.Role, text: String) {
        guard !text.isEmpty else { return }
        // Errors aren't part of the conversation — we don't reload them.
        let roleStr: String
        switch role {
        case .user: roleStr = "user"
        case .assistant: roleStr = "assistant"
        case .error: return
        }
        DispatchQueue.global(qos: .utility).async { [dbURL] in
            var db: OpaquePointer?
            guard sqlite3_open_v2(dbURL.path,
                                  &db,
                                  SQLITE_OPEN_READWRITE | SQLITE_OPEN_NOMUTEX,
                                  nil) == SQLITE_OK else {
                if let db { sqlite3_close(db) }
                return
            }
            defer { sqlite3_close(db) }
            sqlite3_busy_timeout(db, 1000)

            var stmt: OpaquePointer?
            let sql = "INSERT INTO chat_messages (story_id, role, text) VALUES (?, ?, ?)"
            guard sqlite3_prepare_v2(db, sql, -1, &stmt, nil) == SQLITE_OK else { return }
            defer { sqlite3_finalize(stmt) }
            sqlite3_bind_text(stmt, 1, (storyID as NSString).utf8String, -1, nil)
            sqlite3_bind_text(stmt, 2, (roleStr as NSString).utf8String, -1, nil)
            sqlite3_bind_text(stmt, 3, (text as NSString).utf8String, -1, nil)
            _ = sqlite3_step(stmt)
        }
    }

    func clear(storyID: String) {
        DispatchQueue.global(qos: .utility).async { [dbURL] in
            var db: OpaquePointer?
            guard sqlite3_open_v2(dbURL.path,
                                  &db,
                                  SQLITE_OPEN_READWRITE | SQLITE_OPEN_NOMUTEX,
                                  nil) == SQLITE_OK else {
                if let db { sqlite3_close(db) }
                return
            }
            defer { sqlite3_close(db) }
            sqlite3_busy_timeout(db, 1000)
            var stmt: OpaquePointer?
            guard sqlite3_prepare_v2(db, "DELETE FROM chat_messages WHERE story_id = ?",
                                     -1, &stmt, nil) == SQLITE_OK else { return }
            defer { sqlite3_finalize(stmt) }
            sqlite3_bind_text(stmt, 1, (storyID as NSString).utf8String, -1, nil)
            _ = sqlite3_step(stmt)
        }
    }
}
