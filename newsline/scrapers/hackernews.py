"""Hacker News scraper via Firebase API. Adapted from Horizon."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import httpx

from ..config import HackerNewsConfig
from ..models import ContentItem, SourceType
from .base import Scraper, item_id_for

HN_API = "https://hacker-news.firebaseio.com/v0"


class HackerNewsScraper(Scraper):
    name = "HackerNews"

    def __init__(self, cfg: HackerNewsConfig, client: httpx.AsyncClient):
        super().__init__(client)
        self.cfg = cfg

    async def fetch(self, since: datetime) -> list[ContentItem]:
        if not self.cfg.enabled:
            return []
        ids_resp = await self.client.get(f"{HN_API}/topstories.json", timeout=20.0)
        ids_resp.raise_for_status()
        top_ids = ids_resp.json()[: self.cfg.top_n]

        stories = await asyncio.gather(
            *(self._fetch_story(sid) for sid in top_ids),
            return_exceptions=True,
        )

        items: list[ContentItem] = []
        for s in stories:
            if not isinstance(s, dict):
                continue
            if s.get("type") != "story" or s.get("dead") or s.get("deleted"):
                continue
            if (s.get("score") or 0) < self.cfg.min_points:
                continue
            published = datetime.fromtimestamp(s["time"], tz=timezone.utc)
            if published < since:
                continue

            url = s.get("url") or f"https://news.ycombinator.com/item?id={s['id']}"
            title = s.get("title")
            if not title:
                continue

            items.append(
                ContentItem(
                    id=item_id_for(url),
                    source_type=SourceType.HACKERNEWS,
                    source_name="Hacker News",
                    url=url,
                    title=title,
                    author=s.get("by"),
                    content=s.get("text"),
                    published_at=published,
                )
            )
        return items

    async def _fetch_story(self, sid: int) -> dict | None:
        try:
            r = await self.client.get(f"{HN_API}/item/{sid}.json", timeout=10.0)
            r.raise_for_status()
            return r.json()
        except Exception:
            return None
