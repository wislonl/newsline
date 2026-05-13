"""Domain models. Pydantic for in-memory; SQLite is the source of truth on disk."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class SourceType(str, Enum):
    RSS = "rss"
    HACKERNEWS = "hackernews"
    GITHUB = "github"
    REDDIT = "reddit"
    TELEGRAM = "telegram"
    TWITTER = "twitter"


class ContentItem(BaseModel):
    """A single fetched item. Stable across the pipeline; AI fields filled in later."""

    id: str  # sha256(url)[:16]
    source_type: SourceType
    source_name: Optional[str] = None  # feed name, subreddit, channel, etc.
    url: str
    title: str
    author: Optional[str] = None
    content: Optional[str] = None
    published_at: Optional[datetime] = None
    fetched_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    # AI annotations
    ai_score: Optional[float] = None
    ai_reason: Optional[str] = None
    ai_summary: Optional[str] = None
    ai_tags: list[str] = Field(default_factory=list)

    # Storyline link (filled in M1)
    story_id: Optional[str] = None


class Story(BaseModel):
    """Placeholder for M1 — a story is an evolving cluster of ContentItems."""

    id: str
    title: str
    summary: Optional[str] = None
    status: str = "active"  # active | dormant | closed
    first_seen_at: datetime
    last_updated_at: datetime
