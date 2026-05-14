import Foundation
import SQLite3

/// Read-only view of the newsline SQLite database.
///
/// The Python daemon owns writes; the app only reads. Re-open on each query
/// so we always see the latest committed state (no stale snapshots).
final class Store {
    let dbURL: URL

    init() {
        let base = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
        self.dbURL = base.appendingPathComponent("newsline/newsline.db")
    }

    func storyExists() -> Bool {
        FileManager.default.fileExists(atPath: dbURL.path)
    }

    func activeStories(limit: Int = 100) -> [StoryRow] {
        guard let db = open() else { return [] }
        defer { sqlite3_close(db) }

        let sql = """
            SELECT s.id, s.title, s.summary, s.last_updated_at,
                   COUNT(ci.id) AS event_count, MAX(ci.ai_score) AS top_score
              FROM stories s
              LEFT JOIN content_items ci ON ci.story_id = s.id
             WHERE s.status = 'active'
             GROUP BY s.id
             ORDER BY s.last_updated_at DESC
             LIMIT ?
            """
        var stmt: OpaquePointer?
        guard sqlite3_prepare_v2(db, sql, -1, &stmt, nil) == SQLITE_OK else { return [] }
        defer { sqlite3_finalize(stmt) }
        sqlite3_bind_int(stmt, 1, Int32(limit))

        var out: [StoryRow] = []
        while sqlite3_step(stmt) == SQLITE_ROW {
            out.append(StoryRow(
                id: text(stmt, 0) ?? "",
                title: text(stmt, 1) ?? "",
                summary: text(stmt, 2),
                lastUpdated: text(stmt, 3) ?? "",
                eventCount: Int(sqlite3_column_int(stmt, 4)),
                topScore: sqlite3_column_type(stmt, 5) == SQLITE_NULL ? nil : sqlite3_column_double(stmt, 5)
            ))
        }
        return out
    }

    func events(storyID: String) -> [EventRow] {
        guard let db = open() else { return [] }
        defer { sqlite3_close(db) }

        let sql = """
            SELECT id, source_type, source_name, url, title, ai_score, ai_summary, published_at
              FROM content_items
             WHERE story_id = ?
             ORDER BY published_at ASC
            """
        var stmt: OpaquePointer?
        guard sqlite3_prepare_v2(db, sql, -1, &stmt, nil) == SQLITE_OK else { return [] }
        defer { sqlite3_finalize(stmt) }
        sqlite3_bind_text(stmt, 1, (storyID as NSString).utf8String, -1, nil)

        var out: [EventRow] = []
        while sqlite3_step(stmt) == SQLITE_ROW {
            out.append(EventRow(
                id: text(stmt, 0) ?? "",
                sourceType: text(stmt, 1) ?? "",
                sourceName: text(stmt, 2),
                url: text(stmt, 3) ?? "",
                title: text(stmt, 4) ?? "",
                aiScore: sqlite3_column_type(stmt, 5) == SQLITE_NULL ? nil : sqlite3_column_double(stmt, 5),
                aiSummary: text(stmt, 6),
                publishedAt: text(stmt, 7)
            ))
        }
        return out
    }

    // MARK: - private

    private func open() -> OpaquePointer? {
        var db: OpaquePointer?
        // RW (not RO) even though we only SELECT. WAL mode databases need to
        // create/touch the -shm shared-memory file on every connection, and
        // SQLITE_OPEN_READONLY refuses to do that — `prepare` then fails with
        // "unable to open database file". The Store class never executes any
        // INSERT/UPDATE/DELETE, so RW is still effectively read-only.
        let flags = SQLITE_OPEN_READWRITE | SQLITE_OPEN_NOMUTEX
        let rc = sqlite3_open_v2(dbURL.path, &db, flags, nil)
        if rc != SQLITE_OK {
            if let db { sqlite3_close(db) }
            return nil
        }
        // Be patient if the daemon happens to be mid-commit.
        sqlite3_busy_timeout(db, 1000)
        return db
    }

    private func text(_ stmt: OpaquePointer?, _ col: Int32) -> String? {
        guard let cstr = sqlite3_column_text(stmt, col) else { return nil }
        return String(cString: cstr)
    }
}

struct StoryRow: Identifiable, Hashable {
    let id: String
    let title: String
    let summary: String?
    let lastUpdated: String
    let eventCount: Int
    let topScore: Double?
}

struct EventRow: Identifiable, Hashable {
    let id: String
    let sourceType: String
    let sourceName: String?
    let url: String
    let title: String
    let aiScore: Double?
    let aiSummary: String?
    let publishedAt: String?
}
