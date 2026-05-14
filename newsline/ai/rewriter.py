"""Rewrite a story's summary from its full event list.

Triggered when new events attach: the original summary captures only the
first event, so multi-event stories drift out of sync. This step folds
all events into 2-3 sentences leading with the most recent development.
"""

from __future__ import annotations

import asyncio

from ..models import ContentItem
from .client import LLMClient
from .jsonio import extract_json

REWRITE_SYSTEM = """You write evolving-story summaries.

Given a chronological list of events that make up one news story, write
a 2–3 sentence summary that:
  - Leads with the most recent significant development
  - Captures the through-line — what is this story about overall
  - Drops minor or redundant details

Keep it tight: 200 characters or so, no headers, no bullets, plain prose."""

REWRITE_USER = """Story title: {title}

Events in chronological order:
{events}

Respond with VALID JSON ONLY:
{{
  "summary": "<2-3 sentence summary>"
}}"""


class SummaryRewriter:
    def __init__(self, client: LLMClient, concurrency: int = 2):
        self.client = client
        self._sem = asyncio.Semaphore(concurrency)

    async def rewrite(self, title: str, events: list[ContentItem]) -> str | None:
        lines = []
        for i, e in enumerate(events, 1):
            when = e.published_at.strftime("%Y-%m-%d") if e.published_at else "  ?  "
            src = f"{e.source_type.value}/{e.source_name or ''}"
            body = (e.ai_summary or e.title)[:300]
            lines.append(f"{i}. {when} [{src}] {body}")
        user = REWRITE_USER.format(title=title, events="\n".join(lines))

        async with self._sem:
            try:
                raw = await self.client.complete_json(REWRITE_SYSTEM, user)
            except Exception:
                return None

        data = extract_json(raw)
        if not data:
            return None
        summary = data.get("summary")
        if not isinstance(summary, str):
            return None
        return summary.strip() or None
