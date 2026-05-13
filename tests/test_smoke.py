"""Smoke tests — no network, no API key required."""

from __future__ import annotations

import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import pytest

from newsline.db import Database
from newsline.models import ContentItem, SourceType


@pytest.fixture
def tmp_db(monkeypatch: pytest.MonkeyPatch) -> Database:
    tmp = Path(tempfile.mkdtemp())
    monkeypatch.setenv("NEWSLINE_DATA_DIR", str(tmp))
    return Database(path=tmp / "test.db")


def _item(url: str = "https://example.com/a", score: float | None = None) -> ContentItem:
    return ContentItem(
        id=url[-16:].rjust(16, "x"),
        source_type=SourceType.RSS,
        source_name="example",
        url=url,
        title="hello world",
        published_at=datetime.now(timezone.utc),
        ai_score=score,
    )


def test_schema_initializes(tmp_db: Database) -> None:
    with tmp_db.conn() as c:
        tables = {r["name"] for r in c.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()}
    assert {"content_items", "stories", "user_signals", "schema_version"} <= tables


def test_upsert_is_idempotent(tmp_db: Database) -> None:
    it = _item()
    assert tmp_db.upsert_item(it) is True
    assert tmp_db.upsert_item(it) is False


def test_update_ai_fields_and_listing(tmp_db: Database) -> None:
    it = _item()
    tmp_db.upsert_item(it)
    tmp_db.update_ai_fields(it.id, score=7.5, reason="r", summary="s", tags=["a", "b"])

    top = tmp_db.top_items(limit=10, min_score=5.0)
    assert len(top) == 1
    assert top[0].ai_score == 7.5
    assert top[0].ai_tags == ["a", "b"]


def test_unscored_filter(tmp_db: Database) -> None:
    a, b = _item("https://example.com/a"), _item("https://example.com/b")
    tmp_db.upsert_item(a)
    tmp_db.upsert_item(b)
    tmp_db.update_ai_fields(a.id, score=8.0, reason="", summary="", tags=[])

    pending = tmp_db.unscored_items()
    assert {p.id for p in pending} == {b.id}
