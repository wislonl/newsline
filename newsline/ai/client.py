"""Thin multi-provider client. Only what scoring needs in M0."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import AsyncIterator

from ..config import AIConfig


class LLMClient(ABC):
    @abstractmethod
    async def complete_json(self, system: str, user: str) -> str:
        """Return raw JSON text from the model."""

    @abstractmethod
    async def complete_text(self, system: str, user: str, *,
                            max_tokens: int = 1024) -> str:
        """Return free-form text. Used by chat-over-story."""

    async def stream_text(self, system: str, user: str, *,
                          max_tokens: int = 1024) -> AsyncIterator[str]:
        """Yield text chunks as they arrive. Default fallback: one shot.

        Providers override to use their native streaming APIs.
        """
        full = await self.complete_text(system, user, max_tokens=max_tokens)
        yield full


class AnthropicClient(LLMClient):
    def __init__(self, cfg: AIConfig):
        from anthropic import AsyncAnthropic
        self._anthropic = AsyncAnthropic(api_key=cfg.api_key)
        self._model = cfg.model

    async def complete_json(self, system: str, user: str) -> str:
        return await self._call(system, user, max_tokens=1024)

    async def complete_text(self, system: str, user: str, *,
                            max_tokens: int = 1024) -> str:
        return await self._call(system, user, max_tokens=max_tokens)

    async def _call(self, system: str, user: str, *, max_tokens: int) -> str:
        resp = await self._anthropic.messages.create(
            model=self._model,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        return resp.content[0].text

    async def stream_text(self, system: str, user: str, *,
                          max_tokens: int = 1024) -> AsyncIterator[str]:
        async with self._anthropic.messages.stream(
            model=self._model,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
        ) as stream:
            async for chunk in stream.text_stream:
                yield chunk


class OpenAIClient(LLMClient):
    def __init__(self, cfg: AIConfig):
        from openai import AsyncOpenAI
        self._openai = AsyncOpenAI(api_key=cfg.api_key, base_url=cfg.base_url)
        self._model = cfg.model
        self._temperature = cfg.temperature

    async def complete_json(self, system: str, user: str) -> str:
        resp = await self._openai.chat.completions.create(
            model=self._model,
            response_format={"type": "json_object"},
            temperature=self._temperature,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        )
        return resp.choices[0].message.content or "{}"

    async def complete_text(self, system: str, user: str, *,
                            max_tokens: int = 1024) -> str:
        resp = await self._openai.chat.completions.create(
            model=self._model,
            max_tokens=max_tokens,
            temperature=self._temperature,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        )
        return resp.choices[0].message.content or ""

    async def stream_text(self, system: str, user: str, *,
                          max_tokens: int = 1024) -> AsyncIterator[str]:
        stream = await self._openai.chat.completions.create(
            model=self._model,
            max_tokens=max_tokens,
            temperature=self._temperature,
            stream=True,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        )
        async for chunk in stream:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta.content
            if delta:
                yield delta


class MiniMaxClient(LLMClient):
    """MiniMax via its OpenAI-compatible endpoint.

    Differences from vanilla OpenAI:
      - no `response_format` support (rely on prompt + lenient JSON extraction)
      - temperature must be in (0, 1]; clamp upward from 0
    """

    DEFAULT_BASE_URL = "https://api.minimax.io/v1"

    def __init__(self, cfg: AIConfig):
        from openai import AsyncOpenAI
        self._openai = AsyncOpenAI(
            api_key=cfg.api_key,
            base_url=cfg.base_url or self.DEFAULT_BASE_URL,
        )
        self._model = cfg.model
        self._temperature = max(cfg.temperature, 0.01)

    async def complete_json(self, system: str, user: str) -> str:
        return await self._call(system, user, max_tokens=1024) or "{}"

    async def complete_text(self, system: str, user: str, *,
                            max_tokens: int = 1024) -> str:
        return await self._call(system, user, max_tokens=max_tokens)

    async def _call(self, system: str, user: str, *, max_tokens: int) -> str:
        resp = await self._openai.chat.completions.create(
            model=self._model,
            max_tokens=max_tokens,
            temperature=self._temperature,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        )
        return resp.choices[0].message.content or ""

    async def stream_text(self, system: str, user: str, *,
                          max_tokens: int = 1024) -> AsyncIterator[str]:
        stream = await self._openai.chat.completions.create(
            model=self._model,
            max_tokens=max_tokens,
            temperature=self._temperature,
            stream=True,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        )
        async for chunk in stream:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta.content
            if delta:
                yield delta


def create_client(cfg: AIConfig) -> LLMClient:
    p = cfg.provider.lower()
    if p == "anthropic":
        return AnthropicClient(cfg)
    if p == "openai":
        return OpenAIClient(cfg)
    if p == "minimax":
        return MiniMaxClient(cfg)
    raise ValueError(f"Unknown provider: {cfg.provider}")
