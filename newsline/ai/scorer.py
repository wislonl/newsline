"""Score a ContentItem 0-10 with an importance rubric."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from ..models import ContentItem
from .client import LLMClient
from .jsonio import extract_json

SYSTEM_PROMPT = """You are a content curator scoring news items on a 0-10 importance scale.

9-10  Groundbreaking — major releases, paradigm shifts, industry-changing announcements.
7-8   High value     — substantive technical depth, novel approaches, valuable tools/libraries.
5-6   Interesting    — incremental improvements, useful tutorials, moderate signal.
3-4   Low priority   — minor updates, common knowledge, overly promotional.
0-2   Noise          — spam, off-topic, trivial.

Weigh technical depth, novelty, real impact, and writing quality.
"""

USER_PROMPT = """Score this item and respond with VALID JSON ONLY:
{{
  "score": <0-10 number>,
  "reason": "<one short sentence>",
  "summary": "<one-sentence summary>",
  "tags": ["<tag1>", "<tag2>", "<tag3>"]
}}

Title:   {title}
Source:  {source}
Author:  {author}
URL:     {url}
{content_block}"""


@dataclass
class ScoreResult:
    score: float
    reason: str
    summary: str
    tags: list[str]


class Scorer:
    def __init__(self, client: LLMClient, concurrency: int = 4):
        self.client = client
        self._sem = asyncio.Semaphore(concurrency)

    async def score(self, item: ContentItem) -> ScoreResult | None:
        content = (item.content or "").strip()
        if len(content) > 2000:
            content = content[:2000] + "..."
        content_block = f"Content:\n{content}\n" if content else ""

        user = USER_PROMPT.format(
            title=item.title,
            source=f"{item.source_type.value}/{item.source_name or ''}",
            author=item.author or "unknown",
            url=item.url,
            content_block=content_block,
        )

        async with self._sem:
            try:
                raw = await self.client.complete_json(SYSTEM_PROMPT, user)
            except Exception:
                return None

        data = extract_json(raw)
        if not data:
            return None
        try:
            return ScoreResult(
                score=float(data["score"]),
                reason=str(data.get("reason", "")),
                summary=str(data.get("summary", "")),
                tags=[str(t) for t in (data.get("tags") or [])],
            )
        except (KeyError, ValueError, TypeError):
            return None
