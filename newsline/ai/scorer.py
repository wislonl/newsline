"""Score a ContentItem 0-10 with an importance rubric."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from ..models import ContentItem
from .client import LLMClient
from .jsonio import extract_json
from .language import directive_for

SYSTEM_PROMPT = """You are a content curator scoring news items on a 0-10 importance scale.

CALIBRATION (read carefully — anchor on these examples, not your priors):

9-10  Groundbreaking — paradigm shifts and very-large-impact releases.
  Score 9-10 when you'd put it on the front page of every tech blog.
  Examples:
    - "OpenAI releases GPT-6"
    - "Anthropic acquires Cohere"
    - "DeepMind solves protein folding for arbitrary sequences"
    - "Apple ships first M5 chip with on-device 70B inference"

7-8   High value — substantive news, important technical work, or
  industry-relevant developments. THIS IS THE DEFAULT for any item that
  experienced engineers or researchers would want to read TODAY.
  IF YOU ARE TORN BETWEEN 6 AND 8, PICK 8.
  Examples that score 8:
    - "Microsoft BitLocker zero-day exploit (CVE-XXXX)"
    - "npm supply-chain attack hits TanStack + 170 packages"
    - "AMD ROCm 7.2 vs 7.0 inference benchmarks on Radeon AI Pro"
    - "Sebastian Raschka publishes guide to LLM evaluation"
    - "TSMC defers High-NA EUV; Low-NA stays strong"
    - "Nathan Lambert: How open model ecosystems compound"
    - "Cloudflare postmortem on QUIC connection death spiral"
  Examples that score 7:
    - A solid Show HN of a polished tool with clear use case
    - An incremental but technically interesting library release

5-6   Interesting — incremental improvements, useful tutorials, minor
  product updates without industry-level impact.

3-4   Low priority — minor updates, common knowledge restated,
  overly promotional, opinion pieces with little new content.

0-2   Noise — spam, off-topic, trivial, low-quality reposts.

Weigh technical depth, novelty, real impact, and breadth of audience.
Substantive security disclosures, infrastructure incidents from major
vendors, and benchmarks from credible authors are 8s by default —
they are exactly the news a working engineer would want surfaced.
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
    def __init__(self, client: LLMClient, concurrency: int = 4, language: str = "en"):
        self.client = client
        self._sem = asyncio.Semaphore(concurrency)
        self._system = SYSTEM_PROMPT + directive_for(language)

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
                raw = await self.client.complete_json(self._system, user)
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
