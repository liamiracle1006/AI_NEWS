"""Prompt templates.

Phase 1 only ships the first link of the chain: FACT_EXTRACTION.
Phase 2 will add CROSS_REFERENCE and Phase 3 ENTITY_TRACKING.
Keeping them all in one place makes the chain easy to reason about.
"""
from __future__ import annotations

FACT_EXTRACTION_SYSTEM = """\
You are a ruthless fact-extraction engine for geopolitical news.
Your job is to strip a news article of emotion, rhetoric, and authorial framing,
and return only what can be verified from the text itself.

RULES:
1. Remove adjectives, intensifiers, value judgments, and narrative framing.
2. Distinguish CLAIMS (X said Y) from EVENTS (X did Y). Put unverifiable quotes
   in `source_claims_verbatim`, not in `action`.
3. Numbers must be kept exact — do not round, do not translate currencies.
4. If a field is not present in the article, use null or an empty list.
5. Output strictly the JSON schema specified by the user. No prose, no fences.
"""

FACT_EXTRACTION_USER_TEMPLATE = """\
Extract facts from the following news article.

SOURCE: {source_name}  (bias tag: {bias_tag})
URL: {url}
TITLE: {title}

BODY:
\"\"\"
{body}
\"\"\"

Return JSON matching exactly this schema:
{{
  "when":   string or null,
  "where":  string or null,
  "who":    [string, ...],
  "action": string or null,
  "numbers": [string, ...],
  "source_claims_verbatim": [string, ...]
}}
"""


def build_fact_extraction_prompt(article) -> tuple[str, str]:
    """Return (system, user) pair for a single article."""
    body = article.body or article.summary or ""
    # Guard rail: truncate very long articles. ~8k chars ≈ 2k tokens, plenty for
    # fact extraction; the chain-level pass will see the structured output.
    if len(body) > 8000:
        body = body[:8000] + "\n…[truncated]…"

    user = FACT_EXTRACTION_USER_TEMPLATE.format(
        source_name=article.source_name,
        bias_tag=article.bias_tag,
        url=article.url,
        title=article.title,
        body=body,
    )
    return FACT_EXTRACTION_SYSTEM, user
