"""Pipeline orchestrator: fetch → store → score.

M0 keeps stages decoupled and DB-mediated:
  - fetch_all() writes new items, returns count
  - score_pending() picks up un-scored items and fills AI fields

This way M1 (storyline matching) can slot in between as another stage
without rewriting the orchestrator.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import httpx
from rich.console import Console

from .ai.client import create_client
from .ai.scorer import Scorer
from .config import Config
from .db import Database
from .scrapers.base import Scraper
from .scrapers.hackernews import HackerNewsScraper
from .scrapers.rss import RSSScraper


class Pipeline:
    def __init__(self, config: Config, db: Database, console: Console | None = None):
        self.config = config
        self.db = db
        self.console = console or Console()

    async def fetch_all(self, force_hours: int | None = None) -> int:
        hours = force_hours or self.config.filtering.time_window_hours
        since = datetime.now(timezone.utc) - timedelta(hours=hours)
        self.console.print(f"📅 Fetching items since {since.isoformat(timespec='minutes')}")

        async with httpx.AsyncClient(timeout=30.0) as client:
            scrapers: list[Scraper] = []
            if self.config.sources.rss:
                scrapers.append(RSSScraper(self.config.sources.rss, client))
            if self.config.sources.hackernews.enabled:
                scrapers.append(HackerNewsScraper(self.config.sources.hackernews, client))

            results = await asyncio.gather(
                *(self._fetch_one(s, since) for s in scrapers),
                return_exceptions=True,
            )

        new_count = 0
        for r in results:
            if isinstance(r, Exception):
                self.console.print(f"[red]Scraper error: {r}[/red]")
                continue
            new_count += r
        self.console.print(f"📥 Stored {new_count} new items")
        return new_count

    async def _fetch_one(self, scraper: Scraper, since: datetime) -> int:
        self.console.print(f"🔍 {scraper.name}...")
        items = await scraper.fetch(since)
        new = sum(1 for item in items if self.db.upsert_item(item))
        self.console.print(f"   {scraper.name}: {len(items)} fetched, {new} new")
        return new

    async def score_pending(self) -> int:
        pending = self.db.unscored_items()
        if not pending:
            self.console.print("Nothing to score.")
            return 0

        self.console.print(f"🤖 Scoring {len(pending)} items with {self.config.ai.model}")
        client = create_client(self.config.ai)
        scorer = Scorer(client)

        results = await asyncio.gather(
            *(scorer.score(item) for item in pending),
            return_exceptions=True,
        )

        done = 0
        for item, result in zip(pending, results):
            if isinstance(result, Exception) or result is None:
                continue
            self.db.update_ai_fields(
                item.id,
                score=result.score,
                reason=result.reason,
                summary=result.summary,
                tags=result.tags,
            )
            done += 1
        self.console.print(f"⭐️ Scored {done} / {len(pending)} items")
        return done
