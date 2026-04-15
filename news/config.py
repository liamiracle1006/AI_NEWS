"""Centralised config: env vars + sources.yaml loader."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import List

import yaml
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")


@dataclass(frozen=True)
class SourceConfig:
    name: str
    bias_tag: str
    lang: str
    rss: str


@dataclass(frozen=True)
class AppConfig:
    llm_provider: str
    anthropic_api_key: str | None
    anthropic_model: str
    openai_api_key: str | None
    openai_model: str
    gemini_api_key: str | None
    gemini_model: str
    deepseek_api_key: str | None
    deepseek_model: str
    fetch_window_hours: int
    max_per_source: int
    sources: List[SourceConfig]


def load_sources(path: Path | None = None) -> List[SourceConfig]:
    path = path or (ROOT / "sources.yaml")
    with path.open("r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    return [SourceConfig(**s) for s in raw.get("sources", [])]


def load_config() -> AppConfig:
    return AppConfig(
        llm_provider=os.getenv("LLM_PROVIDER", "anthropic").lower().strip(),
        anthropic_api_key=os.getenv("ANTHROPIC_API_KEY") or None,
        anthropic_model=os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-6"),
        openai_api_key=os.getenv("OPENAI_API_KEY") or None,
        openai_model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
        gemini_api_key=os.getenv("GEMINI_API_KEY") or None,
        gemini_model=os.getenv("GEMINI_MODEL", "gemini-2.0-flash"),
        deepseek_api_key=os.getenv("DEEPSEEK_API_KEY") or None,
        deepseek_model=os.getenv("DEEPSEEK_MODEL", "deepseek-chat"),
        fetch_window_hours=int(os.getenv("FETCH_WINDOW_HOURS", "24")),
        max_per_source=int(os.getenv("MAX_PER_SOURCE", "10")),
        sources=load_sources(),
    )
