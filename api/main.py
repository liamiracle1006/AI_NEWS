"""FastAPI application entry point."""
from __future__ import annotations

import asyncio
import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .routes import router

log = logging.getLogger(__name__)

app = FastAPI(title="AI News Analyzer", version="0.4.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router, prefix="/api")


@app.on_event("startup")
async def _startup_cache():
    """Build today's article cache in the background if it doesn't exist yet."""
    from news.article_cache import cache_status, fetch_and_cache
    from news.config import load_config

    status = cache_status()
    if status["has_today"]:
        log.info(
            "Article cache already exists for today (%d articles, %.0f min old)",
            status["article_count"],
            status["age_minutes"],
        )
        return

    log.info("No cache for today — fetching RSS in background...")

    async def _build():
        loop = asyncio.get_running_loop()
        try:
            cfg = await loop.run_in_executor(None, load_config)
            articles = await loop.run_in_executor(None, lambda: fetch_and_cache(cfg))
            log.info("Startup cache complete: %d articles", len(articles))
        except Exception as exc:  # noqa: BLE001
            log.warning("Startup cache failed: %s", exc)

    asyncio.create_task(_build())
