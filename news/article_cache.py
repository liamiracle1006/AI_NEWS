"""Daily article snapshot cache.

Strategy:
  - On startup (or on demand), fetch_and_cache() pulls all RSS articles and
    saves them to cache/YYYY-MM-DD.json.
  - Subsequent analysis calls load from today's cache instead of hitting RSS
    again, making analysis instant and resilient to transient feed failures.
  - If today's cache is absent (first run of the day), we fetch live.
  - Cache files are kept indefinitely; old ones accumulate as historical logs.
    Run `news/article_cache.py --clean N` to delete files older than N days.
"""
from __future__ import annotations

import json
import logging
from datetime import date, datetime, timezone
from pathlib import Path
from typing import List, Optional

from .config import AppConfig
from .ingest import fetch_all
from .models import Article

log = logging.getLogger(__name__)

CACHE_DIR = Path("cache")


def _today_str() -> str:
    return date.today().isoformat()  # YYYY-MM-DD


def _cache_path(date_str: str) -> Path:
    return CACHE_DIR / f"articles_{date_str}.json"


def today_path() -> Path:
    return _cache_path(_today_str())


def _serialize(articles: List[Article]) -> str:
    return json.dumps(
        [a.model_dump(mode="json") for a in articles],
        ensure_ascii=False,
        default=str,
    )


def _deserialize(text: str) -> List[Article]:
    rows = json.loads(text)
    out: List[Article] = []
    for r in rows:
        try:
            out.append(Article.model_validate(r))
        except Exception as exc:  # noqa: BLE001
            log.warning("skipping malformed cached article: %s", exc)
    return out


def save(articles: List[Article], date_str: str | None = None) -> Path:
    """Write articles to today's cache file (or a specific date)."""
    CACHE_DIR.mkdir(exist_ok=True)
    path = _cache_path(date_str or _today_str())
    path.write_text(_serialize(articles), encoding="utf-8")
    log.info("Saved %d articles to %s", len(articles), path)
    return path


def load_today() -> Optional[List[Article]]:
    """Load today's cache. Returns None if not yet created."""
    path = today_path()
    if not path.exists():
        return None
    try:
        return _deserialize(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        log.warning("Failed to read cache %s: %s", path, exc)
        return None


def load_date(date_str: str) -> Optional[List[Article]]:
    """Load cache for a specific date (YYYY-MM-DD)."""
    path = _cache_path(date_str)
    if not path.exists():
        return None
    try:
        return _deserialize(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        log.warning("Failed to read cache %s: %s", path, exc)
        return None


def list_cached_dates() -> List[str]:
    """Return sorted list of cached date strings (newest first)."""
    if not CACHE_DIR.exists():
        return []
    dates = []
    for f in CACHE_DIR.glob("articles_*.json"):
        stem = f.stem  # articles_YYYY-MM-DD
        date_part = stem[len("articles_"):]
        try:
            date.fromisoformat(date_part)
            dates.append(date_part)
        except ValueError:
            pass
    return sorted(dates, reverse=True)


def cache_status() -> dict:
    """Return metadata about the current cache state."""
    CACHE_DIR.mkdir(exist_ok=True)
    today = _today_str()
    path = _cache_path(today)
    all_dates = list_cached_dates()

    if path.exists():
        mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
        age_minutes = (datetime.now(tz=timezone.utc) - mtime).total_seconds() / 60
        try:
            articles = _deserialize(path.read_text(encoding="utf-8"))
            count = len(articles)
        except Exception:  # noqa: BLE001
            count = 0
        return {
            "has_today": True,
            "today": today,
            "article_count": count,
            "age_minutes": round(age_minutes, 1),
            "cached_dates": all_dates,
        }
    return {
        "has_today": False,
        "today": today,
        "article_count": 0,
        "age_minutes": None,
        "cached_dates": all_dates,
    }


MAX_PER_SOURCE_CACHE = 50  # no artificial cap for daily snapshot


def fetch_and_cache(cfg: AppConfig) -> List[Article]:
    """Fetch all RSS sources and save to today's cache. Returns the articles.

    Bodies are NOT fetched here (fetch_body=False) to keep startup fast (~30s).
    The analysis pipeline fetches bodies on-demand for the small set of matched articles.
    """
    log.info("Fetching all RSS sources for daily cache...")
    articles = fetch_all(
        cfg.sources,
        window_hours=cfg.fetch_window_hours,
        max_per_source=MAX_PER_SOURCE_CACHE,
        fetch_body=False,  # RSS metadata only; bodies fetched on-demand during analysis
    )
    if articles:
        save(articles)
        log.info("Daily cache built: %d articles", len(articles))
    else:
        log.warning("Daily cache fetch returned 0 articles — cache not saved")
    return articles


def load_or_fetch(cfg: AppConfig) -> List[Article]:
    """Return today's cached articles, fetching and caching if needed."""
    cached = load_today()
    if cached is not None:
        log.info("Using cached articles (%d) from today", len(cached))
        return cached
    log.info("No cache for today — fetching live")
    return fetch_and_cache(cfg)
