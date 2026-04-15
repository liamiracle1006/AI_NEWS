"""LLM provider abstraction: swap OpenAI / Anthropic / Gemini without touching pipeline code."""
from .base import LLMProvider, get_provider

__all__ = ["LLMProvider", "get_provider"]
