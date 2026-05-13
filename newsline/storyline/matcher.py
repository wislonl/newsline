"""Storyline matcher.

For each new high-score item:
  1. Extract entities (LLM).
  2. Look up recent active stories sharing ≥1 entity (SQL, cheap).
  3. If no candidates → create a new story.
  4. If 1+ candidates → ask LLM to choose one or say "new story".
  5. Attach item to chosen story, or create new.

Story summaries are NOT rewritten on attach. The story keeps its original
summary; the event list grows. Re-summarization is deferred until later.
"""

from __future__ import annotations

import asyncio
import secrets
from dataclasses import dataclass
from datetime import datetime, timezone

from ..ai.client import LLMClient
from ..ai.extractor import EntityExtractor
from ..ai.jsonio import extract_json
from ..db import Database
from ..models import ContentItem

MATCH_SYSTEM = """You decide whether a NEW news item is a follow-up to an EXISTING story.

Two items belong to the same story when they cover the same real-world
event, release, incident, or announcement — even if reported from different
angles. They do NOT belong to the same story when they share a topic but
describe different events (e.g. "Gemma 4 released" vs "Gemma 4 jailbroken"
are separate).

Be strict. When in doubt, return "new"."""

MATCH_USER = """NEW ITEM:
Title:   {title}
Summary: {summary}
Entities: {entities}

CANDIDATE STORIES (choose ONE that matches, or "new" if none):
{candidates}

Respond with VALID JSON ONLY:
{{
  "choice": "<story_id>" | "new",
  "reason": "<one short sentence>"
}}"""


@dataclass
class MatchDecision:
    story_id: str | None  # None == create new
    reason: str


class StorylineMatcher:
    def __init__(self, db: Database, client: LLMClient, *, concurrency: int = 2):
        self.db = db
        self.client = client
        self.extractor = EntityExtractor(client)
        self._sem = asyncio.Semaphore(concurrency)

    async def process(self, item: ContentItem) -> tuple[str, bool]:
        """Extract entities, match-or-create a story, attach.

        Returns (story_id, is_new) where is_new=True means a new story was created.
        """
        entities = await self.extractor.extract(item)
        self.db.set_item_entities(item.id, entities)

        candidates = self.db.candidate_stories(entities, days=30, limit=5) if entities else []

        if candidates:
            decision = await self._classify(item, entities, candidates)
        else:
            decision = MatchDecision(story_id=None, reason="no entity overlap")

        when = item.published_at or datetime.now(timezone.utc)
        if when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)

        if decision.story_id:
            self.db.attach_item_to_story(item.id, decision.story_id, when)
            return decision.story_id, False

        new_id = secrets.token_hex(8)
        title = (item.ai_summary or item.title)[:200]
        self.db.create_story(
            story_id=new_id,
            title=title,
            summary=item.ai_summary,
            entities=entities,
            when=when,
        )
        self.db.attach_item_to_story(item.id, new_id, when)
        return new_id, True

    async def _classify(self, item: ContentItem, entities: list[str],
                        candidates: list[dict]) -> MatchDecision:
        cand_text = "\n".join(
            f"- id={c['id']}  title={c['title']}\n  summary={c.get('summary') or ''}"
            for c in candidates
        )
        user = MATCH_USER.format(
            title=item.title,
            summary=item.ai_summary or "",
            entities=", ".join(entities),
            candidates=cand_text,
        )
        async with self._sem:
            try:
                raw = await self.client.complete_json(MATCH_SYSTEM, user)
            except Exception:
                return MatchDecision(None, "classify error")

        data = extract_json(raw) or {}
        choice = str(data.get("choice", "new")).strip()
        reason = str(data.get("reason", ""))[:200]

        if choice == "new":
            return MatchDecision(None, reason)

        valid_ids = {c["id"] for c in candidates}
        if choice in valid_ids:
            return MatchDecision(choice, reason)
        return MatchDecision(None, f"unknown id {choice!r}; default new")
