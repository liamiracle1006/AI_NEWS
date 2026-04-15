"""DeepSeek provider.

DeepSeek's API is OpenAI-protocol compatible, so we reuse the `openai` SDK
and just swap the base_url. Two models worth knowing about:

  - deepseek-chat      (V3)   — fast, cheap, strong on Chinese; use this by default
  - deepseek-reasoner  (R1)   — chain-of-thought model, slower & pricier;
                                overkill for fact-extraction / cross-reference

Pricing (as of early 2026) is roughly an order of magnitude cheaper than
GPT-4o-mini, which makes it ideal for the daily-briefing loop.
"""
from __future__ import annotations

from .base import LLMProvider
from ..config import AppConfig


class DeepSeekProvider(LLMProvider):
    name = "deepseek"

    def __init__(self, cfg: AppConfig):
        if not cfg.deepseek_api_key:
            raise RuntimeError("DEEPSEEK_API_KEY not set in .env")
        from openai import OpenAI  # DeepSeek is OpenAI-compatible
        self.client = OpenAI(
            api_key=cfg.deepseek_api_key,
            base_url="https://api.deepseek.com",
        )
        self.model = cfg.deepseek_model

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
            # DeepSeek supports OpenAI-style JSON mode on deepseek-chat.
            kwargs["response_format"] = {"type": "json_object"}
        resp = self.client.chat.completions.create(**kwargs)
        return (resp.choices[0].message.content or "").strip()
