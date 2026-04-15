"""Google Gemini provider (via google-genai SDK)."""
from __future__ import annotations

from .base import LLMProvider
from ..config import AppConfig


class GeminiProvider(LLMProvider):
    name = "gemini"

    def __init__(self, cfg: AppConfig):
        if not cfg.gemini_api_key:
            raise RuntimeError("GEMINI_API_KEY not set in .env")
        from google import genai
        self.client = genai.Client(api_key=cfg.gemini_api_key)
        self.model = cfg.gemini_model

    def complete(
        self,
        system: str,
        user: str,
        *,
        json_mode: bool = False,
        max_tokens: int = 2048,
        temperature: float = 0.0,
    ) -> str:
        from google.genai import types
        cfg = types.GenerateContentConfig(
            system_instruction=system,
            max_output_tokens=max_tokens,
            temperature=temperature,
            response_mime_type="application/json" if json_mode else "text/plain",
        )
        resp = self.client.models.generate_content(
            model=self.model,
            contents=user,
            config=cfg,
        )
        return (resp.text or "").strip()
