"""RSS + full-body ingestion.

Strategy:
  1. feedparser pulls the RSS feed for each source.
  2. We keep only entries within `fetch_window_hours`.
  3. trafilatura downloads the article URL and extracts clean body text.
     (trafilatura handles most news sites much better than BeautifulSoup alone.)

Failures on any individual article are swallowed and logged — one broken feed
should not kill the whole run.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from time import mktime
from typing import Iterable, List

import feedparser
import trafilatura

from .config import SourceConfig
from .models import Article

log = logging.getLogger(__name__)


def _entry_time(entry) -> datetime | None:
    for key in ("published_parsed", "updated_parsed"):
        tm = getattr(entry, key, None) or entry.get(key)
        if tm:
            return datetime.fromtimestamp(mktime(tm), tz=timezone.utc)
    return None


def _extract_body(url: str) -> str | None:
    try:
        downloaded = trafilatura.fetch_url(url)
        if not downloaded:
            return None
        return trafilatura.extract(
            downloaded,
            include_comments=False,
            include_tables=False,
            favor_recall=True,
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("body extraction failed for %s: %s", url, exc)
        return None


def fetch_source(
    source: SourceConfig,
    window_hours: int,
    max_items: int,
    fetch_body: bool = True,
) -> List[Article]:
    log.info("Fetching %s …", source.name)
    parsed = feedparser.parse(source.rss)
    if parsed.bozo and not parsed.entries:
        log.warning("  feed unreadable (%s): %s", source.rss, parsed.bozo_exception)
        return []

    cutoff = datetime.now(tz=timezone.utc) - timedelta(hours=window_hours)
    results: List[Article] = []

    for entry in parsed.entries[: max_items * 2]:  # oversample; time-filter below
        when = _entry_time(entry)
        if when and when < cutoff:
            continue
        url = entry.get("link")
        title = entry.get("title")
        if not url or not title:
            continue

        body = _extract_body(url) if fetch_body else None
        results.append(
            Article(
                source_name=source.name,
                bias_tag=source.bias_tag,
                lang=source.lang,
                title=title,
                url=url,
                published_at=when,
                summary=entry.get("summary"),
                body=body,
            )
        )
        if len(results) >= max_items:
            break

    log.info("  got %d articles from %s", len(results), source.name)
    return results


def fetch_all(
    sources: Iterable[SourceConfig],
    window_hours: int,
    max_per_source: int,
    fetch_body: bool = True,
) -> List[Article]:
    out: List[Article] = []
    for s in sources:
        try:
            out.extend(fetch_source(s, window_hours, max_per_source, fetch_body))
        except Exception as exc:  # noqa: BLE001
            log.exception("source %s crashed: %s", s.name, exc)
    return out
