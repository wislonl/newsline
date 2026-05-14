"""Chat-over-story: answer questions using one story's events as context."""

from __future__ import annotations

import re
from typing import AsyncIterator

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

    async def ask_stream(self, *, title: str, summary: str | None,
                         events: list[ContentItem], question: str,
                         history: list[dict[str, str]] | None = None
                         ) -> AsyncIterator[str]:
        """Stream the answer chunk-by-chunk. Reasoning <think> blocks suppressed.

        ``history`` is a list of prior {"role": "user"|"assistant", "content": str}
        turns that came before this question, in chronological order. The story
        context goes in the first user message, prior turns follow, then the new
        question. This lets the model answer follow-ups ('what about its impact?')
        coherently.
        """
        if not events:
            yield self._empty_reply
            return

        story_context = build_user_prompt(title, summary, events, question="")
        # First user turn carries the story. Then prior conversation. Then
        # current question. The model sees: story → past Q/A → new Q.
        messages: list[dict[str, str]] = [{"role": "user", "content": story_context.rstrip()}]
        if history:
            messages.append({"role": "assistant",
                             "content": "Got it. Ask your questions about this story."})
            for turn in history:
                role = turn.get("role")
                content = turn.get("content")
                if role in ("user", "assistant") and isinstance(content, str):
                    messages.append({"role": role, "content": content})
        messages.append({"role": "user", "content": question.strip()})

        stripper = ReasoningStripper()
        async for chunk in self.client.stream_chat(
            self._system, messages, max_tokens=1200
        ):
            emit = stripper.feed(chunk)
            if emit:
                yield emit
        tail = stripper.flush()
        if tail:
            yield tail


class ReasoningStripper:
    """Suppress <think>...</think> blocks across a stream of chunks.

    Reasoning models like MiniMax-M2.7 emit their internal monologue first.
    We buffer chunks until we've either:
      - seen </think> (then emit everything past it), or
      - buffered enough characters with no <think> opening to be confident
        the response isn't using reasoning tags (then emit the buffer).
    """

    _SNIFF = 32  # chars to wait before declaring "no reasoning tag here"

    def __init__(self) -> None:
        self._buf = ""
        self._done = False

    def feed(self, chunk: str) -> str:
        if self._done:
            return chunk
        self._buf += chunk
        if "<think>" not in self._buf and len(self._buf) >= self._SNIFF:
            out, self._buf, self._done = self._buf, "", True
            return out
        idx = self._buf.find("</think>")
        if idx >= 0:
            out = self._buf[idx + len("</think>"):].lstrip()
            self._buf, self._done = "", True
            return out
        return ""

    def flush(self) -> str:
        if self._done:
            return ""
        idx = self._buf.find("</think>")
        out = self._buf[idx + len("</think>"):].lstrip() if idx >= 0 else self._buf
        self._buf, self._done = "", True
        return out


def _strip_reasoning(raw: str) -> str:
    """Reasoning models (e.g. MiniMax-M2.7) prefix output with <think>...</think>.
    Strip it; users only want the final answer."""
    cleaned = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL).strip()
    # Some models leave a stray closing tag without an opener after truncation.
    cleaned = re.sub(r"^</think>\s*", "", cleaned).strip()
    return cleaned or raw.strip()
