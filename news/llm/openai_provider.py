"""OpenAI provider."""
from __future__ import annotations

from .base import LLMProvider
from ..config import AppConfig


class OpenAIProvider(LLMProvider):
    name = "openai"

    def __init__(self, cfg: AppConfig):
        if not cfg.openai_api_key:
            raise RuntimeError("OPENAI_API_KEY not set in .env")
        from openai import OpenAI
        self.client = OpenAI(api_key=cfg.openai_api_key)
        self.model = cfg.openai_model

    def complete(
        self,
        system: str,
        user: str,
        *,
        json_mode: bool = False,
        max_tokens: int = 2048,
        temperature: float = 0.0,
    ) -> str:
        kwargs = dict(
            model=self.model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            max_tokens=max_tokens,
            temperature=temperature,
        )
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}
        resp = self.client.chat.completions.create(**kwargs)
        return (resp.choices[0].message.content or "").strip()
