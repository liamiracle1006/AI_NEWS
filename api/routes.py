"""API routes for the news analyzer."""
from __future__ import annotations

import asyncio
import json
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, BackgroundTasks, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from news.config import load_config
from news.llm import get_provider
from news.pipeline import expand_keyword, extract_facts_batch, cross_reference, track_entities
from news.ingest import fetch_all
from news.cluster import filter_by_keyword
from news.output import render_markdown, write_brief
from news.article_cache import load_or_fetch, fetch_and_cache, cache_status, load_date, list_cached_dates
from api.geo_keywords import GEO_KEYWORDS

router = APIRouter()

# In-memory job store: {job_id: {"status": ..., "events": Queue, "result": ..., "error": ...}}
_jobs: dict[str, dict[str, Any]] = {}

# Heat map cache: {date_str -> (heat_dict, timestamp)}
# Today's entry is refreshed every 10 min; historical dates are loaded once and kept forever.
_heat_cache: dict[str, tuple[dict[str, int], float]] = {}
_HEAT_TTL = 600  # seconds — only applies to today's entry


# ── Request / Response schemas ────────────────────────────────────────────────

class AnalyzeRequest(BaseModel):
    keyword: str
    max_articles: int = 10
    track_people: bool = True
    auto_synonyms: bool = True
    week_mode: bool = False       # use full 7-day cache for cross-week trend analysis
    analyze_date: str | None = None  # YYYY-MM-DD; if set + not week_mode, filter to that publish date


class AnalyzeResponse(BaseModel):
    job_id: str
    expanded_keyword: str


class BriefMeta(BaseModel):
    id: str
    topic: str
    generated_at: str
    filename: str
    article_count: int = 0
    has_data: bool = False


# ── Background worker ─────────────────────────────────────────────────────────

async def _run_analysis(job_id: str, req: AnalyzeRequest, expanded_keyword: str) -> None:
    job = _jobs[job_id]
    q: asyncio.Queue = job["events"]
    loop = asyncio.get_running_loop()

    def emit(step: str, message: str) -> None:
        q.put_nowait({"step": step, "message": message})

    try:
        cfg = await loop.run_in_executor(None, load_config)

        status = cache_status()
        if req.week_mode:
            emit("fetching", f"读取近 7 天缓存（{status.get('article_count', '?')} 篇文章）进行本周综合分析...")
            articles = await loop.run_in_executor(None, lambda: load_or_fetch(cfg))
        elif req.analyze_date:
            emit("fetching", f"读取 {req.analyze_date} 的文章进行分析...")
            articles = await _load_articles_for_date(req.analyze_date, loop)
        elif status["has_today"]:
            emit("fetching", f"读取今日缓存（{status['article_count']} 篇文章）...")
            articles = await loop.run_in_executor(None, lambda: load_or_fetch(cfg))
        else:
            emit("fetching", "首次运行：正在抓取 RSS 源并建立今日缓存...")
            articles = await loop.run_in_executor(None, lambda: load_or_fetch(cfg))

        hits = filter_by_keyword(articles, expanded_keyword)
        if not hits:
            emit("error", "未找到匹配文章，请尝试其他关键词或扩大时间窗口。")
            job["status"] = "error"
            job["error"] = "未找到匹配文章"
            return

        hits = hits[:req.max_articles]
        total = len(hits)

        # Fetch full article bodies in parallel (cache stores RSS metadata only)
        needs_body = [a for a in hits if not a.body]
        if needs_body:
            emit("fetching", f"命中 {total} 篇，正在并行获取全文（{len(needs_body)} 篇）...")
            from news.ingest import _extract_body
            import concurrent.futures

            def _fetch_body(article):
                article.body = _extract_body(article.url)
                return article

            await loop.run_in_executor(
                None,
                lambda: list(concurrent.futures.ThreadPoolExecutor(max_workers=8).map(_fetch_body, needs_body)),
            )

        emit("extracting", f"命中 {total} 篇，开始并行提取事实...")

        provider = get_provider(cfg)

        # Thread-safe counter for progress updates
        _done = [0]
        def on_progress(completed: int, _total: int) -> None:
            _done[0] = completed
            q.put_nowait({"step": "extracting", "message": f"事实提取 {completed}/{_total} 篇..."})

        facts_bundle = await loop.run_in_executor(
            None,
            lambda: extract_facts_batch(provider, hits, on_progress=on_progress),
        )

        if not facts_bundle:
            emit("error", "事实提取全部失败，请检查 API key 或网络。")
            job["status"] = "error"
            job["error"] = "事实提取失败"
            return

        emit("extracting", "正在进行交叉比对分析...")
        cross = await loop.run_in_executor(
            None, lambda: cross_reference(provider, expanded_keyword, facts_bundle)
        )

        entities = None
        if req.track_people:
            emit("extracting", "正在追踪人物...")
            entities = await loop.run_in_executor(
                None, lambda: track_entities(provider, expanded_keyword, facts_bundle)
            )

        result = {
            "facts_bundle": [f.model_dump(mode="json") for f in facts_bundle],
            "cross": cross.model_dump(mode="json"),
            "entities": entities.model_dump(mode="json") if entities else None,
        }
        job["result"] = result

        # Persist: save Markdown brief + JSON result to disk
        try:
            md = render_markdown(expanded_keyword, facts_bundle, cross, entities)
            brief_path = write_brief(Path("briefs"), expanded_keyword, md)
            json_path = brief_path.with_suffix(".json")
            json_path.write_text(
                json.dumps(result, ensure_ascii=False, default=str), encoding="utf-8"
            )
        except Exception as save_exc:  # noqa: BLE001
            print(f"[warn] failed to save brief: {save_exc}")

        job["status"] = "done"
        emit("done", f"分析完成，共 {len(facts_bundle)} 篇文章。")

    except Exception as exc:  # noqa: BLE001
        import traceback
        err_msg = f"{type(exc).__name__}: {exc}"
        job["status"] = "error"
        job["error"] = err_msg
        emit("error", f"分析失败：{err_msg}")
        print(traceback.format_exc())  # visible in uvicorn terminal
    finally:
        q.put_nowait(None)  # sentinel to close the SSE stream


# ── Routes ────────────────────────────────────────────────────────────────────

@router.post("/analyze", response_model=AnalyzeResponse)
async def start_analyze(req: AnalyzeRequest, background_tasks: BackgroundTasks):
    loop = asyncio.get_running_loop()

    # Auto-expand synonyms via LLM (fast, small call)
    if req.auto_synonyms:
        try:
            cfg = await loop.run_in_executor(None, load_config)
            expanded_keyword = await loop.run_in_executor(
                None, lambda: expand_keyword(cfg, req.keyword)
            )
        except Exception:
            expanded_keyword = req.keyword
    else:
        expanded_keyword = req.keyword

    job_id = str(uuid.uuid4())
    _jobs[job_id] = {
        "status": "running",
        "events": asyncio.Queue(),
        "result": None,
        "error": None,
        "keyword": req.keyword,
        "expanded_keyword": expanded_keyword,
        "started_at": datetime.utcnow().isoformat(),
    }
    background_tasks.add_task(_run_analysis, job_id, req, expanded_keyword)
    return AnalyzeResponse(job_id=job_id, expanded_keyword=expanded_keyword)


@router.get("/analyze/{job_id}/stream")
async def stream_progress(job_id: str):
    if job_id not in _jobs:
        raise HTTPException(status_code=404, detail="Job not found")

    job = _jobs[job_id]
    q: asyncio.Queue = job["events"]

    async def event_generator():
        while True:
            item = await q.get()
            if item is None:
                break
            yield f"data: {json.dumps(item, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/analyze/{job_id}/result")
async def get_result(job_id: str):
    if job_id not in _jobs:
        raise HTTPException(status_code=404, detail="Job not found")
    job = _jobs[job_id]
    if job["status"] == "running":
        raise HTTPException(status_code=202, detail="Analysis still in progress")
    if job["status"] == "error":
        raise HTTPException(status_code=500, detail=job.get("error", "Analysis failed"))
    return job["result"]


@router.get("/briefs", response_model=list[BriefMeta])
async def list_briefs():
    briefs_dir = Path("briefs")
    if not briefs_dir.exists():
        return []

    results = []
    for f in sorted(briefs_dir.glob("*.md"), key=lambda p: p.stat().st_mtime, reverse=True):
        stem = f.stem
        parts = stem.rsplit("_", 2)
        if len(parts) == 3:
            topic_raw, date_part, time_part = parts
            try:
                dt = datetime.strptime(f"{date_part}_{time_part}", "%Y%m%d_%H%M")
                generated_at = dt.isoformat()
            except ValueError:
                generated_at = ""
            topic = topic_raw.replace("_", "|")
        else:
            topic = stem
            generated_at = ""

        json_path = briefs_dir / f"{stem}.json"
        article_count = 0
        if json_path.exists():
            try:
                data = json.loads(json_path.read_text(encoding="utf-8"))
                article_count = len(data.get("facts_bundle", []))
            except Exception:
                pass

        results.append(BriefMeta(
            id=stem, topic=topic, generated_at=generated_at, filename=f.name,
            article_count=article_count, has_data=json_path.exists(),
        ))
    return results


@router.get("/briefs/{brief_id}")
async def get_brief(brief_id: str):
    briefs_dir = Path("briefs")
    path = briefs_dir / f"{brief_id}.md"
    if not path.exists():
        raise HTTPException(status_code=404, detail="Brief not found")
    return {"id": brief_id, "content": path.read_text(encoding="utf-8")}


@router.get("/briefs/{brief_id}/data")
async def get_brief_data(brief_id: str):
    """Return the structured JSON result saved alongside the Markdown brief."""
    json_path = Path("briefs") / f"{brief_id}.json"
    if not json_path.exists():
        raise HTTPException(status_code=404, detail="No structured data for this brief")
    return json.loads(json_path.read_text(encoding="utf-8"))


# ── Geo heat map ──────────────────────────────────────────────────────────────


def _build_heat_for(articles) -> dict[str, int]:
    """Count articles per country using GEO_KEYWORDS matching."""
    counts: dict[str, int] = {}
    for article in articles:
        text = f"{article.title} {article.summary or ''}".lower()
        for country, keywords in GEO_KEYWORDS.items():
            if any(k.lower() in text for k in keywords):
                counts[country] = counts.get(country, 0) + 1
    return counts


def _filter_by_published_date(articles: list, date_str: str) -> list:
    """Keep articles whose published_at falls on date_str in UTC+8 (Singapore/HK time).

    RSS timestamps are stored as UTC. Converting to UTC+8 before comparing ensures
    that e.g. an article published at 01:00 SGT (= 4/22 17:00 UTC) appears under
    the correct local calendar date.
    """
    from datetime import date as _date, timezone, timedelta
    target = _date.fromisoformat(date_str)
    sgt = timezone(timedelta(hours=8))
    return [a for a in articles
            if a.published_at and a.published_at.astimezone(sgt).date() == target]


async def _load_all_recent(loop) -> list:
    """Return today's full 7-day rolling cache (unfiltered by publish date)."""
    cfg = await loop.run_in_executor(None, load_config)
    return await loop.run_in_executor(None, lambda: load_or_fetch(cfg))


async def _load_articles_for_date(date_str: str, loop) -> list:
    """Return articles whose published_at falls on date_str (compared in UTC+8).

    Uses today's 7-day cache as source (most complete) for recent dates,
    falling back to the historical cache file for older dates.
    """
    from datetime import date as _date, timezone, timedelta
    sgt = timezone(timedelta(hours=8))
    today_str = datetime.now(tz=sgt).date().isoformat()
    today = _date.fromisoformat(today_str)
    days_ago = (today - _date.fromisoformat(date_str)).days

    cfg = await loop.run_in_executor(None, load_config)

    if days_ago <= 7:
        all_articles = await loop.run_in_executor(None, lambda: load_or_fetch(cfg))
    else:
        all_articles = await loop.run_in_executor(None, lambda: load_date(date_str) or [])

    return _filter_by_published_date(all_articles, date_str)


@router.get("/map/heat")
async def get_map_heat(date: str | None = None):
    """Return per-country article mention counts for a given date (default: today).

    Today's result refreshes every 10 min. Historical dates are cached in memory.
    Dates are interpreted in UTC+8 (Singapore/HK time).
    """
    from datetime import timezone, timedelta
    loop = asyncio.get_running_loop()
    sgt = timezone(timedelta(hours=8))
    today_str = datetime.now(tz=sgt).date().isoformat()
    key = date or today_str
    now = time.time()

    cached = _heat_cache.get(key)
    if cached:
        heat, ts = cached
        is_today = (key == today_str)
        if not is_today or (now - ts < _HEAT_TTL):
            return heat

    articles = await _load_articles_for_date(key, loop)
    heat = await loop.run_in_executor(None, lambda: _build_heat_for(articles))
    _heat_cache[key] = (heat, now)
    return heat


# ── Map: articles by country ─────────────────────────────────────────────────

@router.get("/map/articles")
async def get_map_articles(country: str, date: str | None = None, week: bool = False):
    """Return cached articles for a country.

    - week=true: all articles from the 7-day rolling cache (ignores date param)
    - date=YYYY-MM-DD: articles published on that specific date (UTC+8)
    - default (no params): articles published today (UTC+8)
    """
    from datetime import timezone, timedelta
    loop = asyncio.get_running_loop()
    keywords = GEO_KEYWORDS.get(country, [])
    if not keywords:
        return []

    if week:
        articles = await _load_all_recent(loop)
    else:
        sgt = timezone(timedelta(hours=8))
        today_str = datetime.now(tz=sgt).date().isoformat()
        key = date or today_str
        articles = await _load_articles_for_date(key, loop)

    needles = [k.lower() for k in keywords]

    def matches(a) -> bool:
        text = f"{a.title} {a.summary or ''}".lower()
        return any(n in text for n in needles)

    _MIN_DT = datetime.min.replace(tzinfo=timezone.utc)
    hits = [a for a in articles if matches(a)]
    hits.sort(key=lambda a: a.published_at or _MIN_DT, reverse=True)

    return [
        {
            "title": a.title,
            "url": a.url,
            "source_name": a.source_name,
            "bias_tag": a.bias_tag,
            "summary": (a.summary or "")[:300],
            "published_at": a.published_at.isoformat() if a.published_at else None,
        }
        for a in hits
    ]


# ── Article cache management ──────────────────────────────────────────────────

@router.get("/cache/dates")
async def get_cache_dates():
    """List all available cached dates (newest first)."""
    return list_cached_dates()


@router.get("/cache/status")
async def get_cache_status():
    """Return metadata about the daily article cache."""
    return cache_status()


@router.get("/cache/sources")
async def get_cache_sources():
    """Show per-source article counts from today's cache."""
    from news.article_cache import load_today
    articles = load_today() or []
    counts: dict[str, int] = {}
    for a in articles:
        counts[a.source_name] = counts.get(a.source_name, 0) + 1
    return {"total": len(articles), "by_source": dict(sorted(counts.items(), key=lambda x: -x[1]))}


@router.post("/cache/refresh")
async def refresh_cache(background_tasks: BackgroundTasks):
    """Force-refresh today's article cache by re-fetching all RSS sources."""
    global _heat_cache, _heat_ts

    def _do_refresh():
        global _heat_cache, _heat_ts
        print("[cache] refresh started — fetching all RSS sources...")
        cfg = load_config()
        articles = fetch_and_cache(cfg)
        _heat_ts = 0.0
        print(f"[cache] refresh complete — {len(articles)} articles saved")
        return len(articles)

    background_tasks.add_task(_do_refresh)
    return {"status": "refresh started"}
