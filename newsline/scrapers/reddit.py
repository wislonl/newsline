"""Reddit scraper. Posts only, no comments.

Uses Reddit's public JSON endpoints (no auth). Reddit rate-limits unauthenticated
clients per IP — keep concurrency low and use a realistic User-Agent.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import httpx

from ..config import RedditConfig, RedditSubreddit
from ..models import ContentItem, SourceType
from .base import Scraper, item_id_for

REDDIT_BASE = "https://www.reddit.com"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/135.0.0.0 Safari/537.36",
    "Accept": "application/json,text/plain,*/*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": f"{REDDIT_BASE}/",
}


class RedditScraper(Scraper):
    name = "Reddit"

    def __init__(self, cfg: RedditConfig, client: httpx.AsyncClient):
        super().__init__(client)
        self.cfg = cfg
        # Reddit is sensitive to bursts; cap parallelism per scrape.
        self._sem = asyncio.Semaphore(2)

    async def fetch(self, since: datetime) -> list[ContentItem]:
        if not self.cfg.enabled or not self.cfg.subreddits:
            return []
        results = await asyncio.gather(
            *(self._fetch_one(s, since) for s in self.cfg.subreddits),
            return_exceptions=True,
        )
        items: list[ContentItem] = []
        for r in results:
            if isinstance(r, list):
                items.extend(r)
        return items

    async def _fetch_one(self, sub: RedditSubreddit, since: datetime) -> list[ContentItem]:
        params: dict[str, str | int] = {"limit": min(sub.fetch_limit, 100), "raw_json": 1}
        if sub.sort in ("top", "controversial"):
            params["t"] = sub.time_filter
        url = f"{REDDIT_BASE}/r/{sub.subreddit}/{sub.sort}.json"

        async with self._sem:
            try:
                resp = await self.client.get(url, params=params, headers=HEADERS,
                                              timeout=20.0, follow_redirects=True)
                resp.raise_for_status()
                data = resp.json()
            except Exception:
                return []

        items: list[ContentItem] = []
        for child in data.get("data", {}).get("children", []):
            if child.get("kind") != "t3":
                continue
            p = child["data"]
            created = datetime.fromtimestamp(p.get("created_utc", 0), tz=timezone.utc)
            if created < since:
                continue
            if (p.get("score") or 0) < sub.min_score:
                continue

            permalink = f"https://www.reddit.com{p.get('permalink', '')}"
            is_self = p.get("is_self", False)
            url_external = permalink if is_self else p.get("url") or permalink

            title = p.get("title")
            if not title:
                continue

            selftext = p.get("selftext") or None
            if selftext and len(selftext) > 2000:
                selftext = selftext[:2000] + "..."

            items.append(ContentItem(
                id=item_id_for(url_external),
                source_type=SourceType.REDDIT,
                source_name=f"r/{sub.subreddit}",
                url=url_external,
                title=title.strip(),
                author=p.get("author"),
                content=selftext,
                published_at=created,
            ))
        return items
