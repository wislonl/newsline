"""M1 storyline matcher tests — no network."""

from __future__ import annotations

import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

import pytest

from newsline.ai.client import LLMClient
from newsline.ai.extractor import _normalize_entities
from newsline.db import Database
from newsline.models import ContentItem, SourceType
from newsline.storyline.matcher import StorylineMatcher


class FakeLLM(LLMClient):
    """Returns canned JSON in order; raises if exhausted."""

    def __init__(self, responses: Iterable[str]):
        self._responses = list(responses)
        self.calls: list[tuple[str, str]] = []

    async def complete_json(self, system: str, user: str) -> str:
        self.calls.append((system, user))
        return self._responses.pop(0)


@pytest.fixture
def db(monkeypatch: pytest.MonkeyPatch) -> Database:
    tmp = Path(tempfile.mkdtemp())
    monkeypatch.setenv("NEWSLINE_DATA_DIR", str(tmp))
    return Database(path=tmp / "test.db")


def _item(url: str, title: str, summary: str = "") -> ContentItem:
    return ContentItem(
        id=url[-16:].rjust(16, "x"),
        source_type=SourceType.RSS,
        source_name="x",
        url=url,
        title=title,
        ai_score=8.0,
        ai_summary=summary,
        published_at=datetime.now(timezone.utc),
    )


def test_entity_normalization_dedupes_and_filters() -> None:
    out = _normalize_entities(["Anthropic", "anthropic", "  ", "A", "B" * 100,
                                "Claude", 123, "OpenAI"])
    assert out == ["Anthropic", "Claude", "OpenAI"]


def test_schema_migration_adds_entities_column(tmp_path: Path) -> None:
    # Simulate an old (v1) database: create just content_items without `entities`.
    import sqlite3
    db_path = tmp_path / "old.db"
    with sqlite3.connect(db_path) as c:
        c.executescript("""
            CREATE TABLE content_items (
                id TEXT PRIMARY KEY, source_type TEXT NOT NULL, source_name TEXT,
                url TEXT NOT NULL UNIQUE, title TEXT NOT NULL, author TEXT,
                content TEXT, published_at TIMESTAMP,
                fetched_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                ai_score REAL, ai_reason TEXT, ai_summary TEXT, ai_tags TEXT,
                story_id TEXT
            );
        """)
    Database(path=db_path)  # should ALTER without error
    with sqlite3.connect(db_path) as c:
        cols = {r[1] for r in c.execute("PRAGMA table_info(content_items)").fetchall()}
    assert "entities" in cols


async def test_matcher_creates_new_story_when_no_candidates(db: Database) -> None:
    llm = FakeLLM([
        '{"entities": ["Anthropic", "Claude"]}',  # extractor
    ])
    matcher = StorylineMatcher(db, llm)

    item = _item("https://x/a", "Anthropic launches Claude 4.7", "release")
    db.upsert_item(item)

    sid, is_new = await matcher.process(item)
    assert is_new is True

    events = db.story_events(sid)
    assert [e.id for e in events] == [item.id]
    assert db.candidate_stories(["Anthropic"]) == [
        c for c in db.candidate_stories(["Anthropic"])
    ]  # smoke
    overlap = db.candidate_stories(["Anthropic"])
    assert len(overlap) == 1 and overlap[0]["id"] == sid


async def test_matcher_attaches_when_llm_picks_existing(db: Database) -> None:
    llm = FakeLLM([
        '{"entities": ["Anthropic", "Claude"]}',          # first item entities
        '{"entities": ["Anthropic", "Claude", "v4.7"]}',  # second item entities
        '{"choice": "PICK", "reason": "same release"}',   # match decision
    ])
    matcher = StorylineMatcher(db, llm)

    a = _item("https://x/a", "Anthropic launches Claude 4.7", "release")
    b = _item("https://x/b", "Claude 4.7 benchmarks", "follow-up")
    db.upsert_item(a)
    db.upsert_item(b)

    sid_a, new_a = await matcher.process(a)
    assert new_a is True

    # Patch the placeholder PICK with the real story id we just created
    llm._responses[-1] = f'{{"choice": "{sid_a}", "reason": "same release"}}'

    sid_b, new_b = await matcher.process(b)
    assert new_b is False
    assert sid_b == sid_a

    events = db.story_events(sid_a)
    assert {e.id for e in events} == {a.id, b.id}


async def test_matcher_falls_back_to_new_on_unknown_id(db: Database) -> None:
    llm = FakeLLM([
        '{"entities": ["Anthropic"]}',
        '{"entities": ["Anthropic"]}',
        '{"choice": "ghost", "reason": "made up"}',
    ])
    matcher = StorylineMatcher(db, llm)

    a = _item("https://x/a", "Anthropic news A")
    b = _item("https://x/b", "Anthropic news B")
    db.upsert_item(a)
    db.upsert_item(b)

    sid_a, _ = await matcher.process(a)
    sid_b, new_b = await matcher.process(b)
    assert new_b is True
    assert sid_a != sid_b
