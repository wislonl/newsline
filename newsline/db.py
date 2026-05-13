"""SQLite layer. Single file at ~/Library/Application Support/newsline/newsline.db.

Schema is designed so M1 (storylines) and M3 (user signals) can be filled in
without migrations — the tables already exist, just unused in M0.
"""

from __future__ import annotations

import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator, Optional

from .models import ContentItem, SourceType

SCHEMA_VERSION = 1

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
    embedding           BLOB                    -- filled in M1
);

CREATE INDEX IF NOT EXISTS idx_stories_status ON stories(status, last_updated_at DESC);

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
            c.executescript(SCHEMA)
            row = c.execute("SELECT version FROM schema_version LIMIT 1").fetchone()
            if row is None:
                c.execute("INSERT INTO schema_version (version) VALUES (?)", (SCHEMA_VERSION,))

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
            story_id=r["story_id"],
        )
