"""Thin multi-provider client. Only what scoring needs in M0."""

from __future__ import annotations

from abc import ABC, abstractmethod

from ..config import AIConfig


class LLMClient(ABC):
    @abstractmethod
    async def complete_json(self, system: str, user: str) -> str:
        """Return raw JSON text from the model."""


class AnthropicClient(LLMClient):
    def __init__(self, cfg: AIConfig):
        from anthropic import AsyncAnthropic
        self._anthropic = AsyncAnthropic(api_key=cfg.api_key)
        self._model = cfg.model

    async def complete_json(self, system: str, user: str) -> str:
        resp = await self._anthropic.messages.create(
            model=self._model,
            max_tokens=1024,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        return resp.content[0].text


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
        resp = await self._openai.chat.completions.create(
            model=self._model,
            temperature=self._temperature,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        )
        return resp.choices[0].message.content or "{}"


def create_client(cfg: AIConfig) -> LLMClient:
    p = cfg.provider.lower()
    if p == "anthropic":
        return AnthropicClient(cfg)
    if p == "openai":
        return OpenAIClient(cfg)
    if p == "minimax":
        return MiniMaxClient(cfg)
    raise ValueError(f"Unknown provider: {cfg.provider}")
