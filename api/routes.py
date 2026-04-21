"""API routes for the news analyzer."""
from __future__ import annotations

import asyncio
import json
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

router = APIRouter()

# In-memory job store: {job_id: {"status": ..., "events": Queue, "result": ..., "error": ...}}
_jobs: dict[str, dict[str, Any]] = {}


# ── Request / Response schemas ────────────────────────────────────────────────

class AnalyzeRequest(BaseModel):
    keyword: str
    max_articles: int = 10
    track_people: bool = True
    auto_synonyms: bool = True


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
        emit("fetching", "正在抓取 RSS 源...")
        cfg = await loop.run_in_executor(None, load_config)

        articles = await loop.run_in_executor(
            None,
            lambda: fetch_all(cfg.sources, window_hours=cfg.fetch_window_hours,
                              max_per_source=cfg.max_per_source, fetch_body=True),
        )
        hits = filter_by_keyword(articles, expanded_keyword)
        if not hits:
            emit("error", "未找到匹配文章，请尝试其他关键词或扩大时间窗口。")
            job["status"] = "error"
            job["error"] = "未找到匹配文章"
            return

        hits = hits[:req.max_articles]
        total = len(hits)
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
