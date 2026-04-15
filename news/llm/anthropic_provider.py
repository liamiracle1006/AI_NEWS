"""Anthropic Claude provider."""
from __future__ import annotations

from .base import LLMProvider
from ..config import AppConfig


class AnthropicProvider(LLMProvider):
    name = "anthropic"

    def __init__(self, cfg: AppConfig):
        if not cfg.anthropic_api_key:
            raise RuntimeError("ANTHROPIC_API_KEY not set in .env")
        from anthropic import Anthropic
        self.client = Anthropic(api_key=cfg.anthropic_api_key)
        self.model = cfg.anthropic_model

    def complete(
        self,
        system: str,
        user: str,
        *,
        json_mode: bool = False,
        max_tokens: int = 2048,
        temperature: float = 0.0,
    ) -> str:
        sys_prompt = system
        if json_mode:
            sys_prompt += (
                "\n\nYou MUST respond with a single valid JSON object and nothing else. "
                "No prose, no markdown code fences."
            )

        resp = self.client.messages.create(
            model=self.model,
            system=sys_prompt,
            max_tokens=max_tokens,
            temperature=temperature,
            messages=[{"role": "user", "content": user}],
        )
        # Concatenate any text blocks.
        return "".join(
            b.text for b in resp.content if getattr(b, "type", None) == "text"
        ).strip()
