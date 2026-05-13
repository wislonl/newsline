"""Config loading. JSON file + env vars for secrets."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from pydantic import BaseModel, Field


class AIConfig(BaseModel):
    provider: str = "anthropic"        # anthropic | openai
    model: str = "claude-haiku-4-5-20251001"
    api_key_env: str = "ANTHROPIC_API_KEY"

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


class RSSFeed(BaseModel):
    name: str
    url: str


class HackerNewsConfig(BaseModel):
    enabled: bool = True
    top_n: int = 30
    min_points: int = 50


class SourcesConfig(BaseModel):
    rss: list[RSSFeed] = Field(default_factory=list)
    hackernews: HackerNewsConfig = Field(default_factory=HackerNewsConfig)


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
