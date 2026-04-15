"""Phase 1 CLI entry point.

Usage:
    python -m news.main fetch                 # just fetch + print headlines
    python -m news.main test-extract          # fetch + run FACT_EXTRACTION on first article
    python -m news.main test-extract -n 3     # run on first N articles
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from typing import List

from .config import load_config
from .ingest import fetch_all
from .llm import get_provider
from .llm.prompts import build_fact_extraction_prompt
from .models import Article


def _setup_logging(verbose: bool):
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s — %(message)s",
        datefmt="%H:%M:%S",
    )


def cmd_fetch(args) -> int:
    cfg = load_config()
    articles = fetch_all(
        cfg.sources,
        window_hours=cfg.fetch_window_hours,
        max_per_source=cfg.max_per_source,
        fetch_body=not args.no_body,
    )
    _print_index(articles)
    return 0


def cmd_test_extract(args) -> int:
    cfg = load_config()
    articles = fetch_all(
        cfg.sources,
        window_hours=cfg.fetch_window_hours,
        max_per_source=cfg.max_per_source,
        fetch_body=True,
    )
    if not articles:
        print("No articles fetched — check your sources.yaml and network.", file=sys.stderr)
        return 1

    _print_index(articles)

    with_body = [a for a in articles if (a.body or a.summary)]
    targets = with_body[: args.n]
    if not targets:
        print("No articles had extractable body text.", file=sys.stderr)
        return 1

    provider = get_provider(cfg)
    print(f"\n=== Using LLM provider: {provider.name} ===\n")

    for i, art in enumerate(targets, 1):
        print(f"\n--- [{i}/{len(targets)}] {art.source_name} :: {art.title}")
        system, user = build_fact_extraction_prompt(art)
        raw = provider.complete(system, user, json_mode=True, max_tokens=1024)
        print(_pretty_json(raw))
    return 0


def _print_index(articles: List[Article]) -> None:
    print(f"\nFetched {len(articles)} articles:\n")
    for a in articles:
        body_marker = "●" if a.body else "○"
        when = a.published_at.strftime("%m-%d %H:%M") if a.published_at else "  ?  "
        print(f"  {body_marker} [{when}] [{a.bias_tag:>14}] {a.title[:90]}")
        print(f"      {a.url}")


def _pretty_json(s: str) -> str:
    try:
        return json.dumps(json.loads(s), ensure_ascii=False, indent=2)
    except json.JSONDecodeError:
        return f"[non-JSON response]\n{s}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="news", description="Multi-perspective news analyzer (Phase 1)")
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_fetch = sub.add_parser("fetch", help="Fetch articles and print an index")
    p_fetch.add_argument("--no-body", action="store_true", help="Skip body extraction (faster)")
    p_fetch.set_defaults(func=cmd_fetch)

    p_ex = sub.add_parser("test-extract", help="Run fact-extraction prompt on first N articles")
    p_ex.add_argument("-n", type=int, default=1, help="How many articles to process")
    p_ex.set_defaults(func=cmd_test_extract)

    args = parser.parse_args(argv)
    _setup_logging(args.verbose)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
