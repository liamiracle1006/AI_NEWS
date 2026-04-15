# AI_NEWS — Multi-perspective Geopolitical News Analyzer

A personal-use tool that pulls the same story from ideologically-opposed news sources,
strips emotion/framing with an LLM, and surfaces the **consensus facts** vs. the
**narrative disagreements** — so you can see past any single outlet's spin.

> Positioning: this is a **narrative-spectrum analyzer**, not a truth oracle.
> LLMs weren't at the scene. But they are excellent at comparing how five
> different camps describe the same event and isolating what all of them concede.

## Roadmap

| Phase | Scope | Status |
|---|---|---|
| 1 | RSS ingestion + LLM provider abstraction + single-article fact extraction | done |
| 2 | Keyword-driven clustering + cross-reference chain + Markdown brief | done |
| 3 | Entity tracking (NER), optional Streamlit UI | planned |
| 4 | SQLite history, power-figure timelines, relationship graph | optional |

## Quick start (Phase 1)

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# edit .env and set at least one of ANTHROPIC_API_KEY / OPENAI_API_KEY / GEMINI_API_KEY
# and set LLM_PROVIDER accordingly

# 1) Just fetch and print an index of today's articles:
python -m news.main fetch

# 2) Fetch + run the FACT_EXTRACTION prompt on the first article:
python -m news.main test-extract

# 3) Same, but run on the first 3 articles:
python -m news.main test-extract -n 3
```

## Phase 2: cross-reference a topic

```bash
# Pipe-separated synonyms bridge bilingual sources in a single run:
python -m news.main analyze "加沙|Gaza|gaza"
python -m news.main analyze "乌克兰|Ukraine|Kyiv|Kiev" --max 8
python -m news.main analyze "美国大选|US election|Trump|Harris" --print
```

This runs the full chain:

1. **Fetch** from every source in `sources.yaml` (past `FETCH_WINDOW_HOURS` hours).
2. **Filter** articles mentioning any of the supplied synonyms
   (title/summary first; falls back to full-body match if < `--min-hits`).
3. **Extract facts** per article (emotion-stripped JSON).
4. **Cross-reference** all facts in one LLM call, producing:
    - `consensus_facts` — claims every camp agrees on
    - `divergences` — points where bias_tags diverge, with per-camp framing
    - `suspicious_gaps` — facts only one camp mentions
5. **Render** a Markdown briefing into `briefs/<topic>_<timestamp>.md`.

Use `|` to bridge languages (e.g. `"加沙|Gaza"`) — the filter matches case-insensitive
substrings so both zh and en articles get caught in one pass.

## Project layout

```
news/
├── config.py          env + sources.yaml loader
├── models.py          Pydantic shared models (Article, ExtractedFact, …)
├── ingest.py          feedparser + trafilatura pipeline
├── llm/
│   ├── base.py        LLMProvider ABC + get_provider()
│   ├── anthropic_provider.py
│   ├── openai_provider.py
│   ├── gemini_provider.py
│   └── prompts.py     prompt templates (Phase 1: fact extraction only)
└── main.py            CLI entry point
sources.yaml           customise your news sources here
.env.example           copy -> .env, add API keys
```

## Customising sources

Edit `sources.yaml`. Each entry needs:

```yaml
- name: "Human-readable name"
  bias_tag: "some-label"     # free-form; used downstream by cross-reference prompt
  lang: "en"
  rss: "https://…/feed.xml"
```

Dead feeds are tolerated — the pipeline logs and moves on.

## Phase 2 preview (what's coming next)

- Group articles into *events* using time window + title-keyword overlap + a light LLM pass.
- For each event, gather the per-article extracted facts and run a second prompt:
  *"List the claims all sources agree on. Then list each point where the narratives diverge,
  and label which bias_tag prefers which framing."*
- Persist the result as structured JSON + render a Markdown briefing.
