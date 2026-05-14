"""Chat-over-story: answer questions using one story's events as context."""

from __future__ import annotations

import re

from ..models import ContentItem
from .client import LLMClient
from .language import directive_for

CHAT_SYSTEM = """You answer questions about ONE specific news story.

The user will give you the story's title, summary, and a list of source
events. Use ONLY those events as your source — do not invent facts not
present. If the events don't say, answer "the events don't say". Cite
events inline by their bracketed number, e.g. [2], when you draw on a
specific one.

Be concise: usually 2–4 sentences. Plain prose. No headers."""

CHAT_USER_TEMPLATE = """Story title: {title}
Story summary: {summary}

Source events ({n} total):
{events}

User question: {question}

Answer:"""


def build_user_prompt(title: str, summary: str | None, events: list[ContentItem],
                      question: str) -> str:
    lines = []
    for i, e in enumerate(events, 1):
        when = e.published_at.strftime("%Y-%m-%d") if e.published_at else "  ?  "
        src = f"{e.source_type.value}/{e.source_name or ''}"
        body = (e.ai_summary or "").strip() or e.title
        lines.append(f"[{i}] {when} {src}\n    {e.title}\n    {body}")
    return CHAT_USER_TEMPLATE.format(
        title=title,
        summary=summary or "(none)",
        n=len(events),
        events="\n".join(lines),
        question=question.strip(),
    )


class Chatter:
    def __init__(self, client: LLMClient, language: str = "en"):
        self.client = client
        self._system = CHAT_SYSTEM + directive_for(language)
        self._empty_reply = (
            "这个故事还没有事件可供参考。" if language.lower() == "zh"
            else "The events don't say — this story has no attached items."
        )

    async def ask(self, *, title: str, summary: str | None,
                  events: list[ContentItem], question: str) -> str:
        if not events:
            return self._empty_reply
        user = build_user_prompt(title, summary, events, question)
        raw = await self.client.complete_text(self._system, user, max_tokens=1200)
        return _strip_reasoning(raw)


def _strip_reasoning(raw: str) -> str:
    """Reasoning models (e.g. MiniMax-M2.7) prefix output with <think>...</think>.
    Strip it; users only want the final answer."""
    cleaned = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL).strip()
    # Some models leave a stray closing tag without an opener after truncation.
    cleaned = re.sub(r"^</think>\s*", "", cleaned).strip()
    return cleaned or raw.strip()
