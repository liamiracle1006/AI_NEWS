"""End-to-end analysis pipeline for Phase 2.

analyze_topic(cfg, keyword) does:
    1. fetch_all()                  — pull fresh RSS
    2. filter_by_keyword()          — keep only articles mentioning the topic
    3. per-article fact extraction  — LLM call #1..N
    4. cross_reference()            — one LLM call summarising consensus/divergence

Returns a tuple (facts_bundle, cross_result) so the caller can render whatever
output format it wants (markdown, streamlit, json dump, …).
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import List, Tuple

from .cluster import filter_by_keyword
from .config import AppConfig
from .ingest import fetch_all
from .llm import LLMProvider, get_provider
from .llm.prompts import build_cross_reference_prompt, build_fact_extraction_prompt
from .models import (
    Article,
    ArticleFacts,
    CrossReferenceResult,
    Divergence,
    ExtractedFact,
    SourceRef,
)

log = logging.getLogger(__name__)


def _safe_json(raw: str) -> dict | None:
    # Tolerate models that sometimes wrap JSON in ```json fences.
    s = raw.strip()
    if s.startswith("```"):
        s = s.strip("`")
        if s.lower().startswith("json"):
            s = s[4:].lstrip()
    try:
        return json.loads(s)
    except json.JSONDecodeError as exc:
        log.warning("LLM returned non-JSON: %s | raw=%r", exc, raw[:200])
        return None


def extract_facts_batch(
    provider: LLMProvider,
    articles: List[Article],
) -> List[ArticleFacts]:
    out: List[ArticleFacts] = []
    for i, art in enumerate(articles, 1):
        log.info("fact-extract [%d/%d] %s :: %s",
                 i, len(articles), art.source_name, art.title[:60])
        system, user = build_fact_extraction_prompt(art)
        try:
            raw = provider.complete(system, user, json_mode=True, max_tokens=1024)
        except Exception as exc:  # noqa: BLE001
            log.exception("  provider failed on %s: %s", art.url, exc)
            continue

        data = _safe_json(raw)
        if not data:
            continue
        try:
            facts = ExtractedFact(**data)
        except Exception as exc:  # noqa: BLE001
            log.warning("  schema mismatch on %s: %s", art.url, exc)
            continue

        out.append(ArticleFacts(
            article_url=art.url,
            source_name=art.source_name,
            bias_tag=art.bias_tag,
            title=art.title,
            facts=facts,
        ))
    return out


def cross_reference(
    provider: LLMProvider,
    topic: str,
    facts_bundle: List[ArticleFacts],
) -> CrossReferenceResult:
    log.info("cross-reference over %d fact bundles…", len(facts_bundle))
    system, user = build_cross_reference_prompt(topic, facts_bundle)
    raw = provider.complete(system, user, json_mode=True, max_tokens=4096)
    data = _safe_json(raw) or {}

    divergences = []
    for d in data.get("divergences", []):
        try:
            divergences.append(Divergence(**d))
        except Exception as exc:  # noqa: BLE001
            log.warning("  divergence schema mismatch: %s | %s", exc, d)

    return CrossReferenceResult(
        topic=topic,
        generated_at=datetime.now(tz=timezone.utc),
        sources_covered=[
            SourceRef(
                source_name=f.source_name,
                bias_tag=f.bias_tag,
                url=f.article_url,
                title=f.title,
            )
            for f in facts_bundle
        ],
        consensus_facts=list(data.get("consensus_facts", [])),
        divergences=divergences,
        suspicious_gaps=list(data.get("suspicious_gaps", [])),
    )


def analyze_topic(
    cfg: AppConfig,
    keyword_expr: str,
    *,
    max_articles: int = 10,
    min_hits: int = 3,
) -> Tuple[List[ArticleFacts], CrossReferenceResult | None]:
    articles = fetch_all(
        cfg.sources,
        window_hours=cfg.fetch_window_hours,
        max_per_source=cfg.max_per_source,
        fetch_body=True,
    )
    log.info("fetched %d articles total", len(articles))

    hits = filter_by_keyword(articles, keyword_expr, min_hits=min_hits)
    log.info("keyword %r matched %d articles", keyword_expr, len(hits))
    if not hits:
        return [], None

    hits = hits[:max_articles]

    provider = get_provider(cfg)
    facts_bundle = extract_facts_batch(provider, hits)
    if not facts_bundle:
        log.warning("no usable fact extractions, skipping cross-reference")
        return [], None

    cross = cross_reference(provider, keyword_expr, facts_bundle)
    return facts_bundle, cross
