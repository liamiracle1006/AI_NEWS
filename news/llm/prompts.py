"""Prompt templates.

Phase 1: FACT_EXTRACTION      (per-article emotion-stripping)
Phase 2: CROSS_REFERENCE      (multi-article consensus + divergence)
Phase 3: ENTITY_TRACKING      (planned)

Keeping them all in one place makes the chain easy to reason about.
All prompts enforce Simplified Chinese output so bilingual article inputs
produce a uniform Chinese briefing.
"""
from __future__ import annotations

import json

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
5. All string values MUST be in Simplified Chinese (简体中文), regardless of
   the input article's language. Proper nouns may stay in their original script
   if no widely-used Chinese translation exists.
6. Output strictly the JSON schema specified by the user. No prose, no fences.
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


# ─── Phase 2: Cross-reference ────────────────────────────────────────────

CROSS_REFERENCE_SYSTEM = """\
You are a geopolitical narrative analyst. You receive fact extractions from
multiple news articles covering the same topic, each tagged with its source's
bias_tag (e.g. western-wire, middle-east, russia-state, china-state,
china-nationalist, overseas-chinese). Your job is NOT to decide the absolute
truth. Your job is to reveal the shape of the narrative space:

1. CONSENSUS FACTS — claims that appear across multiple bias_tags, ESPECIALLY
   opposing ones. A claim agreed on by western-wire AND china-state is
   stronger evidence of fact than ten western outlets agreeing.
2. DIVERGENCES — points where camps tell different stories. For each
   divergence, list which camp says what, and add a one-line observation
   characterising the framing pattern (e.g. "西方强调起因，中方回避起因聚焦后果").
3. SUSPICIOUS GAPS — facts asserted by only one camp when opposing camps
   would have strong reason to mention it if true (e.g. only RT mentions a
   specific casualty number that would be newsworthy in western outlets).

Writing rules:
- Output strictly Simplified Chinese (简体中文). Proper nouns may retain
  original script if no common Chinese translation exists.
- Be concise. Each list item one sentence.
- Do not moralise. Do not editorialise. Do not declare which side is right.
- Output strict JSON matching the user-specified schema. No prose, no fences.
"""

CROSS_REFERENCE_USER_TEMPLATE = """\
TOPIC: {topic}

Below are fact extractions from {n_articles} articles across different
geopolitical camps. Analyse them per the rules and return JSON.

ARTICLES:
{articles_block}

Return JSON matching exactly this schema:
{{
  "consensus_facts": [string, ...],
  "divergences": [
    {{
      "point": string,
      "camp_claims": {{ "<bias_tag>": string, ... }},
      "observation": string or null
    }}
  ],
  "suspicious_gaps": [string, ...]
}}
"""


def build_cross_reference_prompt(topic: str, facts_bundle: list) -> tuple[str, str]:
    """Build (system, user) for the cross-reference pass.

    `facts_bundle` is a list of ArticleFacts. We serialise each one into a
    compact block the model can skim — keeping bias_tag visible for attribution.
    """
    blocks = []
    for i, f in enumerate(facts_bundle, 1):
        block = (
            f"[{i}] source={f.source_name} | bias_tag={f.bias_tag}\n"
            f"    title: {f.title}\n"
            f"    url: {f.article_url}\n"
            f"    facts: {json.dumps(f.facts.model_dump(), ensure_ascii=False)}"
        )
        blocks.append(block)

    user = CROSS_REFERENCE_USER_TEMPLATE.format(
        topic=topic,
        n_articles=len(facts_bundle),
        articles_block="\n\n".join(blocks),
    )
    return CROSS_REFERENCE_SYSTEM, user
