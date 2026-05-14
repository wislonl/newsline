"""SQLite layer. Single file at ~/Library/Application Support/newsline/newsline.db.

Schema is designed so M1 (storylines) and M3 (user signals) can be filled in
without migrations — the tables already exist, just unused in M0.
"""

from __future__ import annotations

import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterator, Optional

from .models import ContentItem, SourceType

SCHEMA_VERSION = 3

# Python 3.12 removed default datetime adapters from sqlite3. Register explicit
# ISO-8601 ones so TIMESTAMP columns round-trip cleanly.
sqlite3.register_adapter(datetime, lambda dt: dt.isoformat())
sqlite3.register_converter("TIMESTAMP", lambda b: datetime.fromisoformat(b.decode()))

SCHEMA = """
CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER PRIMARY KEY
);

CREATE TABLE IF NOT EXISTS content_items (
    id              TEXT PRIMARY KEY,
    source_type     TEXT NOT NULL,
    source_name     TEXT,
    url             TEXT NOT NULL UNIQUE,
    title           TEXT NOT NULL,
    author          TEXT,
    content         TEXT,
    published_at    TIMESTAMP,
    fetched_at      TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,

    ai_score        REAL,
    ai_reason       TEXT,
    ai_summary      TEXT,
    ai_tags         TEXT,                       -- JSON array
    entities        TEXT,                       -- JSON array of extracted entities

    story_id        TEXT                        -- nullable, populated in M1
);

CREATE INDEX IF NOT EXISTS idx_items_published ON content_items(published_at DESC);
CREATE INDEX IF NOT EXISTS idx_items_score     ON content_items(ai_score DESC);
CREATE INDEX IF NOT EXISTS idx_items_story     ON content_items(story_id);

-- M1 placeholder
CREATE TABLE IF NOT EXISTS stories (
    id                  TEXT PRIMARY KEY,
    title               TEXT NOT NULL,
    slug                TEXT UNIQUE,
    summary             TEXT,
    status              TEXT NOT NULL DEFAULT 'active',
    entities            TEXT,                   -- JSON
    first_seen_at       TIMESTAMP NOT NULL,
    last_updated_at     TIMESTAMP NOT NULL,
    summary_updated_at  TIMESTAMP,              -- bumped after an LLM rewrite
    embedding           BLOB                    -- filled in M1
);

CREATE INDEX IF NOT EXISTS idx_stories_status ON stories(status, last_updated_at DESC);

-- M1: normalized entity index for cheap story candidate lookup
CREATE TABLE IF NOT EXISTS story_entities (
    story_id    TEXT NOT NULL,
    entity      TEXT NOT NULL,
    PRIMARY KEY (story_id, entity),
    FOREIGN KEY (story_id) REFERENCES stories(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_story_entities_entity ON story_entities(entity);

-- M3 placeholder
CREATE TABLE IF NOT EXISTS user_signals (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id     TEXT NOT NULL,
    kind        TEXT NOT NULL,                  -- open|dwell_ms|thumb_up|thumb_down|save|dismiss|share
    value       REAL,
    ts          TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (item_id) REFERENCES content_items(id)
);

CREATE INDEX IF NOT EXISTS idx_signals_item ON user_signals(item_id);
"""


def default_data_dir() -> Path:
    env = os.environ.get("NEWSLINE_DATA_DIR")
    if env:
        return Path(env).expanduser()
    return Path.home() / "Library" / "Application Support" / "newsline"


class Database:
    def __init__(self, path: Optional[Path] = None):
        self.path = path or (default_data_dir() / "newsline.db")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _init_schema(self) -> None:
        with self.conn() as c:
            # WAL lets the Mac app write user_signals while the Python pipeline
            # is mid-run. Reads are also non-blocking. Sticky setting — one-shot.
            c.execute("PRAGMA journal_mode=WAL")
            c.executescript(SCHEMA)
            # idempotent column add for pre-v2 databases
            cols = {r["name"] for r in c.execute("PRAGMA table_info(content_items)").fetchall()}
            if "entities" not in cols:
                c.execute("ALTER TABLE content_items ADD COLUMN entities TEXT")
            scols = {r["name"] for r in c.execute("PRAGMA table_info(stories)").fetchall()}
            if "summary_updated_at" not in scols:
                c.execute("ALTER TABLE stories ADD COLUMN summary_updated_at TIMESTAMP")
                # backfill: treat existing summaries as fresh at creation time
                c.execute("UPDATE stories SET summary_updated_at = first_seen_at "
                          "WHERE summary_updated_at IS NULL")
            row = c.execute("SELECT version FROM schema_version LIMIT 1").fetchone()
            if row is None:
                c.execute("INSERT INTO schema_version (version) VALUES (?)", (SCHEMA_VERSION,))
            else:
                c.execute("UPDATE schema_version SET version = ?", (SCHEMA_VERSION,))

    @contextmanager
    def conn(self) -> Iterator[sqlite3.Connection]:
        c = sqlite3.connect(self.path, detect_types=sqlite3.PARSE_DECLTYPES)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA foreign_keys = ON")
        try:
            yield c
            c.commit()
        finally:
            c.close()

    # ---- items --------------------------------------------------------------

    def upsert_item(self, item: ContentItem) -> bool:
        """Insert if new, else leave existing AI fields intact. Returns True if newly inserted."""
        with self.conn() as c:
            existing = c.execute("SELECT id FROM content_items WHERE id = ?", (item.id,)).fetchone()
            if existing:
                return False
            c.execute(
                """
                INSERT INTO content_items
                  (id, source_type, source_name, url, title, author, content,
                   published_at, fetched_at, ai_score, ai_reason, ai_summary, ai_tags, story_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    item.id,
                    item.source_type.value,
                    item.source_name,
                    item.url,
                    item.title,
                    item.author,
                    item.content,
                    item.published_at,
                    item.fetched_at,
                    item.ai_score,
                    item.ai_reason,
                    item.ai_summary,
                    json.dumps(item.ai_tags) if item.ai_tags else None,
                    item.story_id,
                ),
            )
            return True

    def update_ai_fields(self, item_id: str, *, score: float, reason: str, summary: str,
                        tags: list[str]) -> None:
        with self.conn() as c:
            c.execute(
                """
                UPDATE content_items
                   SET ai_score = ?, ai_reason = ?, ai_summary = ?, ai_tags = ?
                 WHERE id = ?
                """,
                (score, reason, summary, json.dumps(tags), item_id),
            )

    def unscored_items(self, since: Optional[datetime] = None) -> list[ContentItem]:
        sql = "SELECT * FROM content_items WHERE ai_score IS NULL"
        args: tuple = ()
        if since is not None:
            sql += " AND (published_at IS NULL OR published_at >= ?)"
            args = (since,)
        sql += " ORDER BY fetched_at DESC"
        with self.conn() as c:
            return [self._row_to_item(r) for r in c.execute(sql, args).fetchall()]

    def items_needing_storyline(self, min_score: float = 6.0, limit: int = 100) -> list[ContentItem]:
        """Scored items above threshold that haven't been attached to a story yet."""
        with self.conn() as c:
            rows = c.execute(
                """
                SELECT * FROM content_items
                 WHERE ai_score IS NOT NULL AND ai_score >= ?
                   AND story_id IS NULL
                 ORDER BY published_at DESC
                 LIMIT ?
                """,
                (min_score, limit),
            ).fetchall()
            return [self._row_to_item(r) for r in rows]

    def set_item_entities(self, item_id: str, entities: list[str]) -> None:
        with self.conn() as c:
            c.execute("UPDATE content_items SET entities = ? WHERE id = ?",
                      (json.dumps(entities), item_id))

    def attach_item_to_story(self, item_id: str, story_id: str, when: datetime) -> None:
        with self.conn() as c:
            c.execute("UPDATE content_items SET story_id = ? WHERE id = ?", (story_id, item_id))
            # Only advance — back-dated events shouldn't drag last_updated_at backwards.
            c.execute(
                "UPDATE stories SET last_updated_at = ? "
                "WHERE id = ? AND last_updated_at < ?",
                (when, story_id, when),
            )

    # ---- stories ------------------------------------------------------------

    def create_story(self, *, story_id: str, title: str, summary: str | None,
                     entities: list[str], when: datetime) -> None:
        with self.conn() as c:
            c.execute(
                """
                INSERT INTO stories
                  (id, title, summary, status, entities,
                   first_seen_at, last_updated_at, summary_updated_at)
                VALUES (?, ?, ?, 'active', ?, ?, ?, ?)
                """,
                (story_id, title, summary, json.dumps(entities), when, when, when),
            )
            c.executemany(
                "INSERT OR IGNORE INTO story_entities (story_id, entity) VALUES (?, ?)",
                [(story_id, e) for e in entities],
            )

    def candidate_stories(self, entities: list[str], days: int = 30,
                          limit: int = 5) -> list[dict]:
        """Find recent active stories ranked by entity overlap count."""
        if not entities:
            return []
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        placeholders = ",".join("?" * len(entities))
        with self.conn() as c:
            rows = c.execute(
                f"""
                SELECT s.id, s.title, s.summary, s.last_updated_at,
                       COUNT(se.entity) AS overlap
                  FROM stories s
                  JOIN story_entities se ON se.story_id = s.id
                 WHERE s.status = 'active'
                   AND s.last_updated_at >= ?
                   AND se.entity IN ({placeholders})
              GROUP BY s.id
              ORDER BY overlap DESC, s.last_updated_at DESC
                 LIMIT ?
                """,
                (cutoff, *entities, limit),
            ).fetchall()
            return [dict(r) for r in rows]

    def active_stories(self, limit: int = 50) -> list[dict]:
        with self.conn() as c:
            rows = c.execute(
                """
                SELECT s.id, s.title, s.summary, s.first_seen_at, s.last_updated_at,
                       COUNT(ci.id) AS event_count,
                       MAX(ci.ai_score) AS top_score
                  FROM stories s
                  LEFT JOIN content_items ci ON ci.story_id = s.id
                 WHERE s.status = 'active'
              GROUP BY s.id
              ORDER BY s.last_updated_at DESC
                 LIMIT ?
                """,
                (limit,),
            ).fetchall()
            return [dict(r) for r in rows]

    def resolve_story_id(self, prefix: str) -> str | None:
        """Find a story by id prefix (≥4 chars). Returns None on miss or ambiguity."""
        if len(prefix) < 4:
            return None
        with self.conn() as c:
            rows = c.execute(
                "SELECT id FROM stories WHERE id LIKE ? LIMIT 2",
                (prefix + "%",),
            ).fetchall()
        if len(rows) != 1:
            return None
        return rows[0]["id"]

    def stories_with_stale_summary(self, min_events: int = 2) -> list[dict]:
        """Stories where new events have been attached since the last summary.

        Uses MAX(content_items.fetched_at) — the wall-clock time the event
        row was inserted — rather than published_at (real-world event time,
        which can be older than the story's creation if a backdated post
        attaches later).
        """
        with self.conn() as c:
            rows = c.execute(
                """
                SELECT s.id, s.title, s.summary, s.summary_updated_at,
                       s.last_updated_at, COUNT(ci.id) AS event_count,
                       MAX(ci.fetched_at) AS last_event_fetched_at
                  FROM stories s
                  JOIN content_items ci ON ci.story_id = s.id
                 WHERE s.status = 'active'
              GROUP BY s.id
                HAVING event_count >= ?
                   AND (s.summary_updated_at IS NULL
                        OR MAX(ci.fetched_at) > s.summary_updated_at)
              ORDER BY last_event_fetched_at DESC
                """,
                (min_events,),
            ).fetchall()
            return [dict(r) for r in rows]

    def update_story_summary(self, story_id: str, summary: str, when: datetime) -> None:
        with self.conn() as c:
            c.execute(
                "UPDATE stories SET summary = ?, summary_updated_at = ? WHERE id = ?",
                (summary, when, story_id),
            )

    def signal_summary(self, days: int = 30) -> dict:
        """Aggregate user_signals over a recent window for inspection."""
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        with self.conn() as c:
            by_kind = {
                r["kind"]: r["n"]
                for r in c.execute(
                    "SELECT kind, COUNT(*) AS n FROM user_signals WHERE ts >= ? "
                    "GROUP BY kind ORDER BY n DESC",
                    (cutoff,),
                ).fetchall()
            }
            dwell = c.execute(
                "SELECT AVG(value) AS avg, COUNT(*) AS n FROM user_signals "
                "WHERE kind = 'dwell_ms' AND ts >= ?",
                (cutoff,),
            ).fetchone()
            recent = [
                dict(r) for r in c.execute(
                    """
                    SELECT us.ts, us.kind, us.value, ci.title
                      FROM user_signals us
                      JOIN content_items ci ON ci.id = us.item_id
                     WHERE us.ts >= ?
                     ORDER BY us.ts DESC
                     LIMIT 20
                    """,
                    (cutoff,),
                ).fetchall()
            ]
        return {
            "by_kind": by_kind,
            "avg_dwell_ms": dwell["avg"] if dwell else None,
            "dwell_count": dwell["n"] if dwell else 0,
            "recent": recent,
        }

    def story_events(self, story_id: str) -> list[ContentItem]:
        with self.conn() as c:
            rows = c.execute(
                """
                SELECT * FROM content_items
                 WHERE story_id = ?
                 ORDER BY published_at ASC
                """,
                (story_id,),
            ).fetchall()
            return [self._row_to_item(r) for r in rows]

    def top_items(self, limit: int = 20, min_score: float = 0.0) -> list[ContentItem]:
        with self.conn() as c:
            rows = c.execute(
                """
                SELECT * FROM content_items
                 WHERE ai_score IS NOT NULL AND ai_score >= ?
                 ORDER BY ai_score DESC, published_at DESC
                 LIMIT ?
                """,
                (min_score, limit),
            ).fetchall()
            return [self._row_to_item(r) for r in rows]

    @staticmethod
    def _row_to_item(r: sqlite3.Row) -> ContentItem:
        return ContentItem(
            id=r["id"],
            source_type=SourceType(r["source_type"]),
            source_name=r["source_name"],
            url=r["url"],
            title=r["title"],
            author=r["author"],
            content=r["content"],
            published_at=r["published_at"],
            fetched_at=r["fetched_at"] or datetime.now(timezone.utc),
            ai_score=r["ai_score"],
            ai_reason=r["ai_reason"],
            ai_summary=r["ai_summary"],
            ai_tags=json.loads(r["ai_tags"]) if r["ai_tags"] else [],
            entities=json.loads(r["entities"]) if r["entities"] else [],
            story_id=r["story_id"],
        )
