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
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from typing import Callable, List, Optional, Tuple

from .cluster import filter_by_keyword
from .config import AppConfig
from .ingest import fetch_all
from .llm import LLMProvider, get_provider
from .llm.prompts import (
    build_attention_shift_prompt,
    build_cross_reference_prompt,
    build_entity_tracking_prompt,
    build_fact_extraction_prompt,
    build_narrative_elasticity_prompt,
    build_synonym_expansion_prompt,
    build_weekly_story_arc_prompt,
)
from .models import (
    Article,
    ArticleFacts,
    AttentionPeriod,
    CampElasticity,
    CampFirstSeen,
    CrossReferenceResult,
    Divergence,
    EntityEvent,
    EntityTrackingResult,
    ExtractedFact,
    NarrativeNode,
    SourceRef,
    WeeklyExtras,
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


def _extract_one(provider: LLMProvider, art: Article, max_retries: int = 3) -> ArticleFacts | None:
    system, user = build_fact_extraction_prompt(art)
    raw = None
    for attempt in range(max_retries):
        try:
            raw = provider.complete(system, user, json_mode=True, max_tokens=1024)
            break
        except Exception as exc:  # noqa: BLE001
            if attempt == max_retries - 1:
                log.warning("provider failed on %s after %d tries: %s", art.url, max_retries, exc)
                return None
            # Exponential backoff: 1s → 2s → 4s. Covers rate-limit (429) + transient network.
            backoff = 2 ** attempt
            log.info("provider error on %s (attempt %d/%d): %s — retry in %ds",
                     art.url, attempt + 1, max_retries, exc, backoff)
            time.sleep(backoff)
    if raw is None:
        return None
    data = _safe_json(raw)
    if not data:
        return None
    try:
        facts = ExtractedFact(**data)
    except Exception as exc:  # noqa: BLE001
        log.warning("schema mismatch on %s: %s", art.url, exc)
        return None
    return ArticleFacts(
        article_url=art.url,
        source_name=art.source_name,
        bias_tag=art.bias_tag,
        title=art.title,
        published_at=art.published_at,
        facts=facts,
    )


def extract_facts_batch(
    provider: LLMProvider,
    articles: List[Article],
    on_progress: Optional[Callable[[int, int], None]] = None,
    max_workers: int = 10,
) -> List[ArticleFacts]:
    total = len(articles)
    # Preserve input order in output
    results: dict[int, ArticleFacts] = {}
    completed = 0

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(_extract_one, provider, art): i
                   for i, art in enumerate(articles)}
        for future in as_completed(futures):
            idx = futures[future]
            art = articles[idx]
            result = future.result()
            completed += 1
            log.info("fact-extract [%d/%d] %s :: %s",
                     completed, total, art.source_name, art.title[:60])
            if result:
                results[idx] = result
            if on_progress:
                on_progress(completed, total)

    return [results[i] for i in sorted(results)]


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


def expand_keyword(cfg: AppConfig, keyword: str) -> str:
    """Use LLM to expand a keyword into a pipe-separated synonym expression."""
    provider = get_provider(cfg)
    system, user = build_synonym_expansion_prompt(keyword)
    try:
        raw = provider.complete(system, user, json_mode=True, max_tokens=256)
        data = _safe_json(raw) or {}
        synonyms = [s.strip() for s in data.get("synonyms", []) if s.strip()]
        if synonyms:
            # Deduplicate while preserving order
            seen: set[str] = set()
            unique = [s for s in synonyms if not (s in seen or seen.add(s))]  # type: ignore[func-returns-value]
            return "|".join(unique)
    except Exception as exc:  # noqa: BLE001
        log.warning("synonym expansion failed, using original: %s", exc)
    return keyword


def track_entities(
    provider: LLMProvider,
    topic: str,
    facts_bundle: List[ArticleFacts],
) -> Optional[EntityTrackingResult]:
    log.info("entity-tracking over %d fact bundles…", len(facts_bundle))
    system, user = build_entity_tracking_prompt(topic, facts_bundle)
    try:
        raw = provider.complete(system, user, json_mode=True, max_tokens=4096)
    except Exception as exc:  # noqa: BLE001
        log.exception("entity tracking provider call failed: %s", exc)
        return None

    data = _safe_json(raw) or {}
    entities = []
    for e in data.get("entities", []):
        try:
            entities.append(EntityEvent(**e))
        except Exception as exc:  # noqa: BLE001
            log.warning("  entity schema mismatch: %s | %s", exc, e)

    return EntityTrackingResult(
        topic=topic,
        generated_at=datetime.now(tz=timezone.utc),
        entities=entities,
    )


def compute_info_lag(facts_bundle: List[ArticleFacts]) -> List[CampFirstSeen]:
    """Return per-camp first-seen dates, sorted by arrival time.

    Compares when each bias camp first published on this topic during the week.
    Lag is measured in hours relative to the earliest-reporting camp.
    Pure computation — no LLM call.
    """
    from datetime import timezone, timedelta
    sgt = timezone(timedelta(hours=8))

    # Find the earliest published_at per camp (in UTC+8)
    camp_min: dict[str, datetime] = {}
    camp_source: dict[str, str] = {}
    for f in facts_bundle:
        if not f.published_at:
            continue
        dt = f.published_at.astimezone(sgt)
        if f.bias_tag not in camp_min or dt < camp_min[f.bias_tag]:
            camp_min[f.bias_tag] = dt
            camp_source[f.bias_tag] = f.source_name

    if not camp_min:
        return []

    global_first = min(camp_min.values())

    return [
        CampFirstSeen(
            bias_tag=bias_tag,
            source_name=camp_source[bias_tag],
            first_date=first_dt.strftime("%Y-%m-%d"),
            lag_hours=round((first_dt - global_first).total_seconds() / 3600, 1),
        )
        for bias_tag, first_dt in sorted(camp_min.items(), key=lambda x: x[1])
    ]


def compute_daily_counts(facts_bundle: List[ArticleFacts]) -> dict[str, int]:
    """Count articles per calendar day (UTC+8) for the coverage momentum chart."""
    from collections import Counter
    from datetime import timezone, timedelta
    sgt = timezone(timedelta(hours=8))
    counts: Counter[str] = Counter()
    for f in facts_bundle:
        if f.published_at:
            day = f.published_at.astimezone(sgt).date().isoformat()
            counts[day] += 1
    return dict(sorted(counts.items()))


def weekly_story_arc(
    provider: LLMProvider,
    topic: str,
    facts_bundle: List[ArticleFacts],
) -> List[NarrativeNode]:
    """LLM call: construct a chronological narrative arc from a week's articles."""
    log.info("weekly-story-arc over %d fact bundles…", len(facts_bundle))
    system, user = build_weekly_story_arc_prompt(topic, facts_bundle)
    try:
        raw = provider.complete(system, user, json_mode=True, max_tokens=3000)
    except Exception as exc:  # noqa: BLE001
        log.warning("weekly_story_arc provider call failed: %s", exc)
        return []
    data = _safe_json(raw) or {}
    nodes = []
    for n in data.get("nodes", []):
        try:
            nodes.append(NarrativeNode(**n))
        except Exception as exc:  # noqa: BLE001
            log.warning("  narrative node schema mismatch: %s | %s", exc, n)
    return nodes


def compute_attention_shift(
    provider: LLMProvider,
    topic: str,
    facts_bundle: List[ArticleFacts],
) -> List[AttentionPeriod]:
    """LLM call: thematic focus per time period — produces Sankey source data."""
    log.info("attention-shift over %d fact bundles…", len(facts_bundle))
    system, user = build_attention_shift_prompt(topic, facts_bundle)
    try:
        raw = provider.complete(system, user, json_mode=True, max_tokens=1500)
    except Exception as exc:  # noqa: BLE001
        log.warning("attention_shift provider call failed: %s", exc)
        return []
    data = _safe_json(raw) or {}
    periods = []
    for p in data.get("periods", []):
        try:
            periods.append(AttentionPeriod(**p))
        except Exception as exc:  # noqa: BLE001
            log.warning("  attention period schema mismatch: %s | %s", exc, p)
    return periods


def compute_narrative_elasticity(
    provider: LLMProvider,
    topic: str,
    facts_bundle: List[ArticleFacts],
) -> List[CampElasticity]:
    """Compare early-week vs late-week framing per camp (parallel LLM calls)."""
    from datetime import timezone, timedelta
    sgt = timezone(timedelta(hours=8))

    # Split bundle by date median
    dated = sorted(
        [f for f in facts_bundle if f.published_at],
        key=lambda f: f.published_at,  # type: ignore[arg-type]
    )
    if len(dated) < 4:
        return []

    mid = len(dated) // 2
    early_all = dated[:mid]
    late_all = dated[mid:]

    # Group by camp
    from collections import defaultdict
    early_by_camp: dict[str, list] = defaultdict(list)
    late_by_camp: dict[str, list] = defaultdict(list)
    for f in early_all:
        early_by_camp[f.bias_tag].append(f)
    for f in late_all:
        late_by_camp[f.bias_tag].append(f)

    # Only analyse camps present in BOTH halves with 2+ articles each
    camps = [
        c for c in early_by_camp
        if c in late_by_camp and len(early_by_camp[c]) >= 2 and len(late_by_camp[c]) >= 2
    ]
    if not camps:
        return []

    results = []

    def _analyse_camp(bias_tag: str) -> CampElasticity | None:
        system, user = build_narrative_elasticity_prompt(
            topic, bias_tag, early_by_camp[bias_tag], late_by_camp[bias_tag]
        )
        try:
            raw = provider.complete(system, user, json_mode=True, max_tokens=512)
        except Exception as exc:  # noqa: BLE001
            log.warning("narrative_elasticity failed for %s: %s", bias_tag, exc)
            return None
        data = _safe_json(raw) or {}
        try:
            return CampElasticity(bias_tag=bias_tag, **data)
        except Exception as exc:  # noqa: BLE001
            log.warning("  elasticity schema mismatch for %s: %s", bias_tag, exc)
            return None

    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = {pool.submit(_analyse_camp, c): c for c in camps}
        for future in as_completed(futures):
            result = future.result()
            if result:
                results.append(result)

    # Sort: shifted camps first, then by bias_tag
    results.sort(key=lambda e: (not e.shifted, e.bias_tag))
    return results


def build_weekly_extras(
    provider: LLMProvider,
    topic: str,
    facts_bundle: List[ArticleFacts],
) -> WeeklyExtras:
    """Assemble all week-exclusive analysis modules."""
    return WeeklyExtras(
        story_arc=weekly_story_arc(provider, topic, facts_bundle),
        camp_first_seen=compute_info_lag(facts_bundle),
        daily_counts=compute_daily_counts(facts_bundle),
        attention_shift=compute_attention_shift(provider, topic, facts_bundle),
        narrative_elasticity=compute_narrative_elasticity(provider, topic, facts_bundle),
    )


def analyze_topic(
    cfg: AppConfig,
    keyword_expr: str,
    *,
    max_articles: int = 10,
    min_hits: int = 3,
    track_people: bool = True,
    fast_mode: bool = False,
) -> Tuple[List[ArticleFacts], CrossReferenceResult | None, EntityTrackingResult | None]:
    articles = fetch_all(
        cfg.sources,
        window_hours=cfg.fetch_window_hours,
        max_per_source=cfg.max_per_source,
        fetch_body=not fast_mode,
    )
    log.info("fetched %d articles total (fast_mode=%s)", len(articles), fast_mode)

    hits = filter_by_keyword(articles, keyword_expr, min_hits=min_hits)
    log.info("keyword %r matched %d articles", keyword_expr, len(hits))
    if not hits:
        return [], None, None

    hits = hits[:max_articles]

    provider = get_provider(cfg)
    facts_bundle = extract_facts_batch(provider, hits)
    if not facts_bundle:
        log.warning("no usable fact extractions, skipping cross-reference")
        return [], None, None

    # Run cross_reference + track_entities in parallel — independent LLM calls, no shared state.
    with ThreadPoolExecutor(max_workers=2) as pool:
        cross_fut = pool.submit(cross_reference, provider, keyword_expr, facts_bundle)
        ent_fut = pool.submit(track_entities, provider, keyword_expr, facts_bundle) if track_people else None
        cross = cross_fut.result()
        entities = ent_fut.result() if ent_fut else None

    return facts_bundle, cross, entities
