# encoding:utf-8
"""Playwright-based renderer for the brief HTML report.

Both PNG (full-page screenshot) and PDF use the same backend HTML route
(/api/briefs/{brief_id}/render), so layout stays consistent.

Requires:
    pip install playwright
    playwright install chromium

If Playwright is missing or browser launch fails, callers should fall back
to the legacy Pillow renderer.
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path


def is_available() -> bool:
    """Cheap probe — returns True iff playwright is importable."""
    try:
        import playwright  # noqa: F401
        return True
    except ImportError:
        return False


def render_brief_png(brief_url: str, viewport_width: int = 800) -> bytes:
    """Take a full-page screenshot of the HTML report. Returns PNG bytes."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            page = browser.new_page(viewport={"width": viewport_width, "height": 1200})
            page.goto(brief_url, wait_until="networkidle", timeout=30000)
            png = page.screenshot(full_page=True, type="png")
            return png
        finally:
            browser.close()


def render_brief_pdf(brief_url: str) -> bytes:
    """Print the HTML report to A4 PDF. Returns PDF bytes."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            page = browser.new_page()
            page.goto(brief_url, wait_until="networkidle", timeout=30000)
            pdf = page.pdf(
                format="A4",
                margin={"top": "16mm", "right": "12mm", "bottom": "16mm", "left": "12mm"},
                print_background=True,
            )
            return pdf
        finally:
            browser.close()


def write_pdf_to_temp(pdf_bytes: bytes, topic: str) -> str:
    """Write PDF bytes to a temp file, return absolute path.

    WeChat ReplyType.FILE expects a path on disk. Caller is responsible for
    cleanup (or letting OS reclaim temp).
    """
    safe_topic = "".join(c if c.isalnum() or c in "._-" else "_" for c in topic)[:40]
    fd, path = tempfile.mkstemp(prefix=f"AINews_{safe_topic}_", suffix=".pdf")
    os.close(fd)
    Path(path).write_bytes(pdf_bytes)
    return path
