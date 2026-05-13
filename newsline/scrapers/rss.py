"""RSS/Atom scraper. Adapted from Horizon."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from time import mktime
from typing import Iterable

import feedparser
import httpx

from ..config import RSSFeed
from ..models import ContentItem, SourceType
from .base import Scraper, item_id_for


class RSSScraper(Scraper):
    name = "RSS"

    def __init__(self, feeds: Iterable[RSSFeed], client: httpx.AsyncClient):
        super().__init__(client)
        self.feeds = list(feeds)

    async def fetch(self, since: datetime) -> list[ContentItem]:
        results = await asyncio.gather(
            *(self._fetch_one(f, since) for f in self.feeds),
            return_exceptions=True,
        )
        items: list[ContentItem] = []
        for r in results:
            if isinstance(r, list):
                items.extend(r)
        return items

    async def _fetch_one(self, feed: RSSFeed, since: datetime) -> list[ContentItem]:
        try:
            resp = await self.client.get(feed.url, follow_redirects=True, timeout=20.0)
            resp.raise_for_status()
        except Exception:
            return []

        parsed = feedparser.parse(resp.content)
        items: list[ContentItem] = []
        for entry in parsed.entries:
            url = entry.get("link")
            title = entry.get("title")
            if not url or not title:
                continue

            published = _parse_time(entry)
            if published and published < since:
                continue

            content = _extract_content(entry)
            items.append(
                ContentItem(
                    id=item_id_for(url),
                    source_type=SourceType.RSS,
                    source_name=feed.name,
                    url=url,
                    title=title.strip(),
                    author=entry.get("author"),
                    content=content,
                    published_at=published,
                )
            )
        return items


def _parse_time(entry) -> datetime | None:
    for key in ("published_parsed", "updated_parsed"):
        t = entry.get(key)
        if t:
            return datetime.fromtimestamp(mktime(t), tz=timezone.utc)
    return None


def _extract_content(entry) -> str | None:
    # Prefer full content, fall back to summary.
    if "content" in entry and entry.content:
        return entry.content[0].get("value")
    return entry.get("summary")
