"""Keyword-driven event clustering.

MVP strategy (deliberately simple, no embeddings):

    Level 1: match keyword against TITLE and RSS SUMMARY
    Level 2: if Level 1 yields < min_hits, extend match to full BODY

User supplies synonyms via pipe-separated keyword string, e.g. "加沙|Gaza|gaza".
This keeps bilingual topics working without any auto-translation round-trip.
"""
from __future__ import annotations

import logging
from typing import Iterable, List

from .models import Article

log = logging.getLogger(__name__)


def _parse_keywords(expr: str) -> List[str]:
    return [k.strip().lower() for k in expr.split("|") if k.strip()]


def _contains_any(text: str | None, needles: List[str]) -> bool:
    if not text:
        return False
    t = text.lower()
    return any(n in t for n in needles)


def filter_by_keyword(
    articles: Iterable[Article],
    keyword_expr: str,
    min_hits: int = 3,
) -> List[Article]:
    """Return articles matching `keyword_expr`.

    `keyword_expr` uses pipe `|` for synonyms, e.g. "乌克兰|Ukraine|Kyiv".
    Matching is case-insensitive substring (good enough for zh + en).
    """
    needles = _parse_keywords(keyword_expr)
    if not needles:
        return []

    articles = list(articles)

    # Level 1: title + summary (no cost, fast)
    level1 = [
        a for a in articles
        if _contains_any(a.title, needles) or _contains_any(a.summary, needles)
    ]
    log.info("keyword filter L1 (title/summary): %d hits", len(level1))
    if len(level1) >= min_hits:
        return _dedupe(level1)

    # Level 2: extend to body
    seen_urls = {a.url for a in level1}
    level2 = [
        a for a in articles
        if a.url not in seen_urls and _contains_any(a.body, needles)
    ]
    log.info("keyword filter L2 (body): +%d hits", len(level2))
    return _dedupe(level1 + level2)


def _dedupe(articles: List[Article]) -> List[Article]:
    seen: set[str] = set()
    out: List[Article] = []
    for a in articles:
        if a.url in seen:
            continue
        seen.add(a.url)
        out.append(a)
    return out
