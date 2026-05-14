"""Translate item / story titles to the configured display language.

Title translation is tricky: many "titles" in feeds are actually
identifiers — repo paths (trycua/cua), filenames, version strings —
which must NOT be translated. The prompt instructs the model to be
conservative.
"""

from __future__ import annotations

import asyncio

from .client import LLMClient
from .jsonio import extract_json

_SYSTEM_ZH = """You translate news headlines to Simplified Chinese.

Rules:
1. If the input is a repo path (owner/name), a filename, a CLI command,
   a URL, or a pure technical identifier, RETURN IT UNCHANGED.
2. Translate prose-style headlines naturally; do not transliterate.
3. Keep proper nouns (companies, product names, technical terms, version
   numbers, code identifiers) in their original English form.
4. Preserve punctuation style.

Examples:
  "trycua/cua"
    → "trycua/cua"
  "Microsoft BitLocker – YellowKey zero-day exploit"
    → "微软 BitLocker — YellowKey 零日漏洞利用"
  "Claude for Small Business"
    → "面向小企业的 Claude"
  "When 'idle' isn't idle: how a Linux kernel optimization became a QUIC bug"
    → "当 idle 不再 idle：一次 Linux 内核优化如何变成 QUIC bug"
"""

_USER_TMPL = """Translate this headline. Respond with VALID JSON ONLY:
{{"title": "<translated headline>"}}

Headline: {title}"""


class TitleTranslator:
    def __init__(self, client: LLMClient, language: str = "zh",
                 concurrency: int = 4):
        if language.lower() != "zh":
            raise ValueError("only 'zh' is supported as a target right now")
        self.client = client
        self._sem = asyncio.Semaphore(concurrency)

    async def translate(self, title: str) -> str | None:
        if not title or not title.strip():
            return None
        user = _USER_TMPL.format(title=title)
        async with self._sem:
            try:
                raw = await self.client.complete_json(_SYSTEM_ZH, user)
            except Exception:
                return None
        data = extract_json(raw)
        if not data:
            return None
        out = data.get("title")
        if not isinstance(out, str):
            return None
        out = out.strip()
        return out or None
