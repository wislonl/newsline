import Foundation
import SQLite3

/// Writes user-feedback signals into the SQLite db.
///
/// Separate from `Store` because writers and readers want different open
/// flags. The DB runs in WAL mode (set by the Python daemon at init) so
/// our writes don't block the daemon's pipeline writes.
final class Signals {
    enum Kind: String {
        case open
        case dwellMs = "dwell_ms"
        case thumbUp = "thumb_up"
        case thumbDown = "thumb_down"
        case save
        case dismiss
        case share
    }

    private let dbURL: URL

    init(dbURL: URL) {
        self.dbURL = dbURL
    }

    /// Insert one row. `value` carries dwell ms for `.dwellMs`; nil otherwise.
    /// Fails silently — feedback never blocks UI.
    func record(itemID: String, kind: Kind, value: Double? = nil) {
        guard !itemID.isEmpty else { return }
        DispatchQueue.global(qos: .utility).async { [dbURL] in
            var db: OpaquePointer?
            let flags = SQLITE_OPEN_READWRITE | SQLITE_OPEN_NOMUTEX
            guard sqlite3_open_v2(dbURL.path, &db, flags, nil) == SQLITE_OK else {
                if let db { sqlite3_close(db) }
                return
            }
            defer { sqlite3_close(db) }
            // 1s busy timeout absorbs the rare collision with the daemon writer.
            sqlite3_busy_timeout(db, 1000)

            var stmt: OpaquePointer?
            let sql = "INSERT INTO user_signals (item_id, kind, value) VALUES (?, ?, ?)"
            guard sqlite3_prepare_v2(db, sql, -1, &stmt, nil) == SQLITE_OK else { return }
            defer { sqlite3_finalize(stmt) }

            sqlite3_bind_text(stmt, 1, (itemID as NSString).utf8String, -1, nil)
            sqlite3_bind_text(stmt, 2, (kind.rawValue as NSString).utf8String, -1, nil)
            if let value {
                sqlite3_bind_double(stmt, 3, value)
            } else {
                sqlite3_bind_null(stmt, 3)
            }
            _ = sqlite3_step(stmt)
        }
    }

    /// Record an `open` for every event in a story plus the story itself (as the
    /// representative event — we only have item-level user_signals for now).
    /// For dwell tracking we use the FIRST event id of the story as a proxy.
    func recordOpen(eventIDs: [String]) {
        if let first = eventIDs.first {
            record(itemID: first, kind: .open)
        }
    }

    /// Latest thumb verdict per item. Returns thumbUp/thumbDown or nil.
    func currentThumb(itemID: String) -> Kind? {
        var db: OpaquePointer?
        let flags = SQLITE_OPEN_READONLY | SQLITE_OPEN_NOMUTEX
        guard sqlite3_open_v2(dbURL.path, &db, flags, nil) == SQLITE_OK else {
            if let db { sqlite3_close(db) }
            return nil
        }
        defer { sqlite3_close(db) }

        var stmt: OpaquePointer?
        let sql = """
            SELECT kind FROM user_signals
             WHERE item_id = ? AND kind IN ('thumb_up','thumb_down')
             ORDER BY ts DESC LIMIT 1
            """
        guard sqlite3_prepare_v2(db, sql, -1, &stmt, nil) == SQLITE_OK else { return nil }
        defer { sqlite3_finalize(stmt) }
        sqlite3_bind_text(stmt, 1, (itemID as NSString).utf8String, -1, nil)

        if sqlite3_step(stmt) == SQLITE_ROW,
           let cstr = sqlite3_column_text(stmt, 0) {
            return Kind(rawValue: String(cString: cstr))
        }
        return nil
    }
}
