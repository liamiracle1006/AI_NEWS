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

    Three-level cascade — each level only used when the previous yields < min_hits:
      L1: title match  (article is primarily about this topic)
      L2: + summary match (topic mentioned prominently)
      L3: + body match  (topic mentioned anywhere)
    This prevents articles that casually mention a keyword in passing from
    polluting results when there are already enough on-topic articles.
    """
    needles = _parse_keywords(keyword_expr)
    if not needles:
        return []

    articles = list(articles)

    # L1: title only — strongest signal
    title_hits = [a for a in articles if _contains_any(a.title, needles)]
    log.info("keyword filter L1 (title): %d hits", len(title_hits))
    if len(title_hits) >= min_hits:
        return _dedupe(title_hits)

    # L2: extend to summary
    seen = {a.url for a in title_hits}
    summary_hits = [a for a in articles if a.url not in seen and _contains_any(a.summary, needles)]
    log.info("keyword filter L2 (summary): +%d hits", len(summary_hits))
    l2 = title_hits + summary_hits
    if len(l2) >= min_hits:
        return _dedupe(l2)

    # L3: extend to body
    seen = {a.url for a in l2}
    body_hits = [a for a in articles if a.url not in seen and _contains_any(a.body, needles)]
    log.info("keyword filter L3 (body): +%d hits", len(body_hits))
    return _dedupe(l2 + body_hits)


def _dedupe(articles: List[Article]) -> List[Article]:
    seen: set[str] = set()
    out: List[Article] = []
    for a in articles:
        if a.url in seen:
            continue
        seen.add(a.url)
        out.append(a)
    return out
