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

EXTRACT_SYSTEM = """You extract canonical named entities from a news item.

Return only specific, disambiguating entities:
- Companies / organizations (Anthropic, OpenAI, EU Commission)
- Products / projects (Claude, GPT-5, Linux kernel, React Native)
- People (Sam Altman, Dario Amodei)
- Specific technologies / standards (HTTP/3, RISC-V, llama.cpp)
- Version identifiers when present (v4.7, 2024.10)
- Place names when newsworthy (Taiwan, Brussels)

DO NOT include generic topics ("AI", "machine learning", "news"), adjectives,
or tags. If unsure whether something is specific, omit it.

Use canonical English form. Deduplicate. 0–8 entities total."""

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
    return out[:8]
