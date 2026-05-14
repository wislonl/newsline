"""Config loading. JSON file + env vars for secrets."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Optional  # noqa: F401  (used in AIConfig)

from dotenv import load_dotenv
from pydantic import BaseModel, Field


class AIConfig(BaseModel):
    provider: str = "anthropic"        # anthropic | openai | minimax
    model: str = "claude-haiku-4-5-20251001"
    api_key_env: str = "ANTHROPIC_API_KEY"
    base_url: Optional[str] = None     # override for OpenAI-compatible providers
    temperature: float = 0.3
    language: str = "en"               # "en" | "zh" — drives user-facing LLM output

    @property
    def api_key(self) -> str:
        key = os.environ.get(self.api_key_env, "")
        if not key:
            raise RuntimeError(
                f"Missing API key. Set {self.api_key_env} in your .env file."
            )
        return key


class FilteringConfig(BaseModel):
    time_window_hours: int = 24
    ai_score_threshold: float = 6.0
    # Per-source score bias (added after the LLM scores). Default is 0
    # for every source — looking at real data, MiniMax-M2.7-highspeed is
    # already conservative (a Microsoft BitLocker zero-day was scored 7,
    # not 8). Applying a negative bias on HN here pushes legitimate
    # high-impact news below typical ≥8 filters. Turn this back on if
    # you find a source actually overscoring relative to others.
    source_bias: dict[str, float] = Field(default_factory=lambda: {
        "hackernews": 0.0,
        "reddit": 0.0,
        "rss": 0.0,
        "github": 0.0,
        "twitter": 0.0,
        "telegram": 0.0,
    })
    # After how many days of no new event a story is marked dormant
    # (hidden from the default sidebar). Set 0 to disable.
    dormant_after_days: int = 30


class RSSFeed(BaseModel):
    name: str
    url: str


class HackerNewsConfig(BaseModel):
    enabled: bool = True
    top_n: int = 30
    min_points: int = 50


class RedditSubreddit(BaseModel):
    subreddit: str
    sort: str = "hot"             # hot | top | new
    time_filter: str = "day"      # only when sort=top|controversial
    fetch_limit: int = 25
    min_score: int = 50


class RedditConfig(BaseModel):
    enabled: bool = False
    subreddits: list[RedditSubreddit] = Field(default_factory=list)


class SourcesConfig(BaseModel):
    rss: list[RSSFeed] = Field(default_factory=list)
    hackernews: HackerNewsConfig = Field(default_factory=HackerNewsConfig)
    reddit: RedditConfig = Field(default_factory=RedditConfig)


class Config(BaseModel):
    ai: AIConfig = Field(default_factory=AIConfig)
    filtering: FilteringConfig = Field(default_factory=FilteringConfig)
    sources: SourcesConfig = Field(default_factory=SourcesConfig)

    @classmethod
    def load(cls, path: Optional[Path] = None) -> "Config":
        load_dotenv()
        path = path or Path("config.json")
        if not path.exists():
            raise FileNotFoundError(
                f"{path} not found. Copy config.example.json to config.json and edit it."
            )
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return cls.model_validate(data)
