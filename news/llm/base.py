"""Provider-agnostic LLM interface.

Every provider exposes a single `complete(system, user, json_mode)` method.
That is deliberately minimal — the prompt chain lives one layer up.
"""
from __future__ import annotations

from abc import ABC, abstractmethod

from ..config import AppConfig


class LLMProvider(ABC):
    name: str = "base"

    @abstractmethod
    def complete(
        self,
        system: str,
        user: str,
        *,
        json_mode: bool = False,
        max_tokens: int = 2048,
        temperature: float = 0.0,
    ) -> str:
        """Return the assistant's text. If json_mode=True, the model is
        instructed / constrained to return valid JSON."""


def get_provider(cfg: AppConfig) -> LLMProvider:
    name = cfg.llm_provider
    if name == "anthropic":
        from .anthropic_provider import AnthropicProvider
        return AnthropicProvider(cfg)
    if name == "openai":
        from .openai_provider import OpenAIProvider
        return OpenAIProvider(cfg)
    if name == "gemini":
        from .gemini_provider import GeminiProvider
        return GeminiProvider(cfg)
    raise ValueError(f"Unknown LLM_PROVIDER={name!r}")
