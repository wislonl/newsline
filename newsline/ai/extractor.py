"""Entity extraction for storyline matching.

Entities are the matching primitive in M1: companies, products, people, places,
specific projects, technologies, version identifiers. Generic tags like "AI" or
"news" are NOT entities — they don't disambiguate stories.
"""

from __future__ import annotations

import asyncio

from ..models import ContentItem
from .client import LLMClient
from .jsonio import extract_json

EXTRACT_SYSTEM = """You extract canonical named entities that a news item is primarily ABOUT.

Critical rule: extract only the SUBJECT of the story, not entities that are
merely MENTIONED in passing or used as tools.

Good examples:
  Story: "Anthropic launches Claude 4.7"  →  ["Anthropic", "Claude 4.7"]
  Story: "Rars: a Rust RAR implementation, mostly written by GPT-5.5"
    →  ["Rars", "Rust"]   (NOT "GPT-5.5" — it's the tool, not the subject)
  Story: "Simon Willison reviews the new OpenAI API"
    →  ["OpenAI API"]     (NOT "Simon Willison" — he's the reviewer/author)

Entity types to consider when they ARE the subject:
- Companies / organizations
- Products / projects / specific services
- People (only when the story is about THEM, not when they're just the author)
- Specific technologies, standards, or version identifiers
- Place names when newsworthy

DO NOT include:
- Generic topics ("AI", "machine learning", "open source")
- Tools or LLMs used to make the thing (unless that's the story)
- Authors / bylines (unless the story is profiling them)
- Adjectives, tags, categories

Use canonical English form. Deduplicate. 1–5 entities total. If unsure, omit."""

EXTRACT_USER = """Extract entities from this item. Respond with VALID JSON ONLY:
{{
  "entities": ["<entity1>", "<entity2>", ...]
}}

Title:   {title}
Source:  {source}
Summary: {summary}
{content_block}"""


class EntityExtractor:
    def __init__(self, client: LLMClient, concurrency: int = 4):
        self.client = client
        self._sem = asyncio.Semaphore(concurrency)

    async def extract(self, item: ContentItem) -> list[str]:
        content = (item.content or "").strip()
        if len(content) > 1500:
            content = content[:1500] + "..."
        content_block = f"Content:\n{content}" if content else ""

        user = EXTRACT_USER.format(
            title=item.title,
            source=f"{item.source_type.value}/{item.source_name or ''}",
            summary=item.ai_summary or "",
            content_block=content_block,
        )

        async with self._sem:
            try:
                raw = await self.client.complete_json(EXTRACT_SYSTEM, user)
            except Exception:
                return []

        data = extract_json(raw)
        if not data:
            return []
        ents = data.get("entities") or []
        return _normalize_entities(ents)


def _normalize_entities(ents) -> list[str]:
    """Strip, dedupe (case-insensitive), drop too-short/too-long."""
    out: list[str] = []
    seen: set[str] = set()
    for e in ents:
        if not isinstance(e, str):
            continue
        e = e.strip()
        if not (2 <= len(e) <= 60):
            continue
        key = e.casefold()
        if key in seen:
            continue
        seen.add(key)
        out.append(e)
    return out[:5]
