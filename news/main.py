"""CLI entry point.

Usage:
    # Phase 1 sanity checks:
    python -m news.main fetch                       # fetch + print index
    python -m news.main test-extract -n 2           # run FACT_EXTRACTION on N articles

    # Phase 2 full pipeline:
    python -m news.main analyze "加沙|Gaza"          # fetch + filter + cross-reference
    python -m news.main analyze "乌克兰|Ukraine|Kyiv" --max 8
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import List

from .config import load_config
from .ingest import fetch_all
from .llm import get_provider
from .llm.prompts import build_fact_extraction_prompt
from .models import Article
from .output import render_markdown, write_brief
from .pipeline import analyze_topic


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


def cmd_analyze(args) -> int:
    cfg = load_config()
    facts_bundle, cross = analyze_topic(
        cfg,
        keyword_expr=args.keyword,
        max_articles=args.max,
        min_hits=args.min_hits,
    )
    if not cross:
        print(
            f"No analysable articles found for keyword {args.keyword!r}. "
            "Try different synonyms (pipe-separated), a wider window "
            "(FETCH_WINDOW_HOURS in .env), or more sources.",
            file=sys.stderr,
        )
        return 1

    md = render_markdown(args.keyword, facts_bundle, cross)
    out_dir = Path(args.out_dir)
    path = write_brief(out_dir, args.keyword, md)
    print(f"\n✅ Brief saved: {path}")
    print(f"   Articles analysed: {len(facts_bundle)}")
    print(f"   Consensus facts:   {len(cross.consensus_facts)}")
    print(f"   Divergences:       {len(cross.divergences)}")
    if args.print:
        print("\n" + "=" * 60 + "\n")
        print(md)
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

    p_an = sub.add_parser(
        "analyze",
        help="Full pipeline: fetch + filter by keyword + cross-reference + Markdown brief",
    )
    p_an.add_argument(
        "keyword",
        help="Keyword expression; use '|' for synonyms, e.g. \"加沙|Gaza|gaza\"",
    )
    p_an.add_argument("--max", type=int, default=10, help="Max articles to analyse (cost cap)")
    p_an.add_argument("--min-hits", type=int, default=3, help="Level-1 minimum before falling back to body match")
    p_an.add_argument("--out-dir", default="briefs", help="Directory to write Markdown briefs into")
    p_an.add_argument("--print", action="store_true", help="Also print the brief to stdout")
    p_an.set_defaults(func=cmd_analyze)

    args = parser.parse_args(argv)
    _setup_logging(args.verbose)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
