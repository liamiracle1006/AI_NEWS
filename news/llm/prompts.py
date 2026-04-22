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
You are a precise fact-extraction engine for geopolitical news.
Your job is to strip a news article of emotion, rhetoric, and authorial framing,
and return a structured, detailed summary of what the article actually reports.

RULES:
1. Remove adjectives, intensifiers, value judgments, and narrative framing.
2. Distinguish CLAIMS (X said Y) from EVENTS (X did Y).
   - Verifiable events → `action` field (2-3 sentences allowed to capture the full sequence)
   - Official statements and attributed claims → `key_quotes` (format: "[Person/Entity]: exact quote")
   - Unverifiable assertions and editorial attributions → `source_claims_verbatim`
3. Numbers must be kept exact — do not round, do not translate currencies.
4. `context`: one sentence explaining WHY this is happening or what broader situation it fits into.
   If the article provides no background, use null.
5. If a field is not present in the article, use null or an empty list.
6. All string values MUST be in Simplified Chinese (简体中文), regardless of
   the input article's language. Proper nouns may stay in their original script
   if no widely-used Chinese translation exists.
7. Output strictly the JSON schema specified by the user. No prose, no fences.
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
  "context": string or null,
  "key_quotes": [string, ...],
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
bias_tag and publication date. Your job is NOT to decide absolute truth.
Your job is to reveal the shape of the narrative space.

Camp name mapping (use these Chinese labels in output):
  western-wire=西方通讯社  western-uk=英国视角
  us-liberal=美国主流      us-conservative=美国保守
  middle-east=中东视角
  russia-state=俄方官方    china-state=中国官方  china-nationalist=中国民族主义
  overseas-chinese=海外中文

1. CONSENSUS FACTS
   Facts that 2+ articles in this batch report consistently.
   - If articles span multiple camps, cross-camp agreements are most credible — annotate them as "（跨阵营确认）".
   - If all articles come from the same camp, still list what they collectively establish, marking each "（仅{camp中文名}来源，待其他阵营交叉验证）".
   - Format: full sentence + "（来源：阵营名 [日期]、...）"
   - Never return an empty list — even a single article establishes baseline facts worth listing.

2. DIVERGENCES
   Differences in HOW sources frame the same underlying event.
   - Prefer cross-camp divergences (most analytically valuable).
   - When all sources share the same bias_tag, surface meaningful within-source variations in emphasis, detail selection, or implicit framing.
   - If there is genuinely only one article and no variation is possible, skip this section (empty list).
   - `point`: neutral one-phrase description of the disputed aspect
   - `camp_claims`: each source's framing in natural, flowing prose — 2-4 sentences per entry
   - `observation`: WHY the framing gap exists (strategic interest, editorial choice, information access, audience assumptions). Be specific.

3. SUSPICIOUS GAPS
   - Cross-camp: claims one camp makes that opposing camps would have strong incentive to cover if true, yet did not.
   - If the batch is single-camp: explicitly list which major perspectives are ABSENT (e.g., 俄方、中方) and what questions those absent perspectives might answer very differently. This helps the reader know what they are NOT seeing.

Rules:
- Output Simplified Chinese. Proper nouns may keep original script.
- Do not moralize or declare which side is correct.
- NEVER return empty consensus_facts when there are 2+ articles — extract what the articles collectively establish even if it is mundane.
- Strict JSON per schema. No prose, no fences.
"""

CROSS_REFERENCE_USER_TEMPLATE = """\
TOPIC: {topic}

Fact extractions from {n_articles} articles:

{articles_block}

Return JSON:
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
    """Build (system, user) for the cross-reference pass."""
    blocks = []
    for i, f in enumerate(facts_bundle, 1):
        date_str = f.published_at.strftime("%Y-%m-%d") if getattr(f, "published_at", None) else "日期未知"
        block = (
            f"[{i}] source={f.source_name} | bias_tag={f.bias_tag} | date={date_str}\n"
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


# ─── Keyword synonym expansion ───────────────────────────────────────────────

SYNONYM_EXPANSION_SYSTEM = """\
You are a multilingual news search assistant.
Given a news topic keyword, return a comprehensive list of synonyms, alternative
names, abbreviations, and translations that international news sources use
(Chinese, English, Arabic, Russian, French as relevant).

RULES:
1. Include the original keyword as-is.
2. Add common translations and alternate spellings used by major news agencies.
3. Limit to 6-10 terms — quality over quantity.
4. Output strict JSON only. No prose, no fences.
"""

SYNONYM_EXPANSION_USER_TEMPLATE = """\
Topic keyword: {keyword}

Return JSON:
{{"synonyms": [string, ...]}}
"""


def build_synonym_expansion_prompt(keyword: str) -> tuple[str, str]:
    return SYNONYM_EXPANSION_SYSTEM, SYNONYM_EXPANSION_USER_TEMPLATE.format(keyword=keyword)


# ─── Phase 3: Entity Tracking ────────────────────────────────────────────────

ENTITY_TRACKING_SYSTEM = """\
You are a political-entity tracker. Given fact extractions from multiple
articles about a topic, produce a deduplicated list of named political
figures (heads of state, ministers, generals, spokespersons, opposition
leaders) who appear with meaningful agency in this round of reporting.

RULES:
1. MERGE aliases into one entity. "习近平" / "中国国家主席" / "Xi Jinping"
   → canonical_name="习近平", aliases=["Xi Jinping", "中国国家主席", ...].
   Canonical name must be Simplified Chinese if a standard Chinese name exists.
2. Keep ONLY politically meaningful actions: 任命、辞职、被捕、失踪、
   出访、表态、签署、会晤、军事命令 etc. Ignore passing background mentions.
3. status_change: fill ONLY if this round shows a clear role transition
   (appointed / resigned / arrested / disappeared). Leave null otherwise.
4. per_source_framing: if different bias_tags describe the same person's
   action differently, capture each camp's framing here. Omit camps that
   do not mention this person at all.
5. sources: list the article URLs that mention this entity.
6. Do NOT merge two distinct people. When unsure, keep them separate.
7. Output Simplified Chinese for all text fields. Proper nouns may retain
   original script if no common Chinese equivalent exists.
8. Output strict JSON per the user schema. No prose, no fences.
"""

ENTITY_TRACKING_USER_TEMPLATE = """\
TOPIC: {topic}

Below are fact extractions from {n_articles} articles across different
geopolitical bias camps. Identify, deduplicate, and track political figures.

ARTICLES:
{articles_block}

Return JSON matching exactly this schema:
{{
  "entities": [
    {{
      "canonical_name": string,
      "aliases": [string, ...],
      "position": string or null,
      "action_or_status": string,
      "status_change": string or null,
      "per_source_framing": {{ "<bias_tag>": string, ... }},
      "sources": [url, ...]
    }}
  ]
}}
"""


def build_entity_tracking_prompt(topic: str, facts_bundle: list) -> tuple[str, str]:
    """Build (system, user) for the entity tracking pass."""
    blocks = []
    for i, f in enumerate(facts_bundle, 1):
        block = (
            f"[{i}] source={f.source_name} | bias_tag={f.bias_tag}\n"
            f"    title: {f.title}\n"
            f"    url: {f.article_url}\n"
            f"    who: {json.dumps(f.facts.who, ensure_ascii=False)}\n"
            f"    action: {f.facts.action or 'null'}\n"
            f"    claims: {json.dumps(f.facts.source_claims_verbatim, ensure_ascii=False)}"
        )
        blocks.append(block)

    user = ENTITY_TRACKING_USER_TEMPLATE.format(
        topic=topic,
        n_articles=len(facts_bundle),
        articles_block="\n\n".join(blocks),
    )
    return ENTITY_TRACKING_SYSTEM, user
