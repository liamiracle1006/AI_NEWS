# AI_NEWS — Multi-perspective Geopolitical News Analyzer

A tool that pulls the same story from ideologically-opposed news sources, strips emotion and framing with an LLM, and surfaces **consensus facts** vs. **narrative disagreements** — so you can see past any single outlet's spin.

> Positioning: this is a **narrative-spectrum analyzer**, not a truth oracle.
> LLMs weren't at the scene. But they are excellent at comparing how different camps describe the same event and isolating what all of them concede.

---

## Features

### 🗺️ Interactive World Map
- Global news heatmap — countries color-coded by article volume (green → red)
- Click any country to open a side panel with today's or this week's relevant articles
- Articles filtered by title match to avoid loosely related stories

### 📊 Deep Analysis (per topic / country)
Triggered on demand via the UI. Runs the full LLM pipeline:

1. **Fact extraction** — per article: who, when, where, action, numbers, key quotes, context (all output in Simplified Chinese)
2. **Cross-reference** — consensus facts, narrative divergences with per-camp framing, suspicious gaps
3. **Entity tracking** — political figures mentioned across sources, with how each camp describes them
4. **Article digest** — every source article shown individually with action summary, context, and expandable quotes

### 📅 Weekly Analysis (7-day mode)
Exclusive to week mode — goes beyond a daily snapshot:

| Module | What it shows |
|---|---|
| 📈 Coverage momentum | Daily article count bar chart, peak day highlighted |
| 🌊 Attention shift | Sankey diagram: how thematic focus shifted across time periods |
| 🕰️ Story arc | Chronological narrative arc with per-camp reactions at each phase |
| 🎯 Narrative elasticity | Did each camp quietly change its framing early vs. late in the week? |
| ⏱️ Info lag | Which camp first reported the story; lag hours for others |

### ⚡ Infrastructure
- Hourly auto-refresh of RSS cache while backend is running
- Article cache stored per day (`cache/articles_YYYY-MM-DD.json`) for historical browsing
- LLM synonym expansion for multilingual keyword matching (`加沙|Gaza|하마스`)
- SSE progress stream so the UI shows real-time extraction progress

---

## News Sources

16 sources across the geopolitical spectrum:

| Camp | Sources |
|---|---|
| Western wire | Reuters, AP (via NPR) |
| UK | BBC World, The Guardian |
| US liberal | NYT World, CNN |
| US conservative | Fox News World |
| Middle East | Al Jazeera, Mehr News, Press TV |
| Hong Kong / Chinese-angle | SCMP (HK), SCMP (China) |
| China state | CGTN, Global Times, China Daily |

---

## Project Layout

```
AI_NEWS/
├── api/
│   ├── main.py              FastAPI app entry point, hourly cache refresh loop
│   ├── routes.py            All API routes
│   └── geo_keywords.py      Country → keyword mapping for heatmap (~70 countries)
├── news/
│   ├── config.py            Env + sources.yaml loader
│   ├── models.py            Pydantic models (Article, ArticleFacts, WeeklyExtras, …)
│   ├── ingest.py            feedparser + trafilatura pipeline
│   ├── cluster.py           Keyword filter (title → summary → body cascade)
│   ├── pipeline.py          Full analysis pipeline + weekly modules
│   ├── article_cache.py     Daily JSON cache management
│   └── llm/
│       ├── prompts.py       All LLM prompt templates
│       └── providers/       Anthropic / OpenAI / Gemini / DeepSeek adapters
├── frontend/
│   └── src/
│       ├── components/
│       │   ├── WorldMap.tsx          Interactive SVG heatmap
│       │   ├── RegionPanel.tsx       Country article side panel
│       │   ├── ResultView.tsx        Analysis result layout
│       │   ├── ArticleDigestList.tsx Per-article summary cards
│       │   ├── WeeklyView.tsx        Weekly analysis modules
│       │   ├── ConsensusSection.tsx
│       │   ├── DivergenceCard.tsx
│       │   ├── EntityCard.tsx
│       │   └── GapSection.tsx
│       ├── api.ts            Fetch wrappers + SSE hook
│       └── types.ts          TypeScript types mirroring Pydantic models
├── sources.yaml              News source configuration
├── cache/                    Auto-generated daily article snapshots
└── briefs/                   Saved analysis results (JSON)
```

---

## Quick Start

### Prerequisites
- Python 3.11+
- Node.js 18+
- API key for at least one LLM provider (DeepSeek recommended for cost)

### Setup

```bash
# Clone and install backend
git clone <repo>
cd AI_NEWS
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# Configure
cp .env.example .env
# Edit .env — set LLM_PROVIDER and the corresponding API key

# Install frontend
cd frontend
npm install
```

### Running

**Backend** (terminal 1):
```bash
uvicorn api.main:app --reload --port 8000
```

**Frontend** (terminal 2):
```bash
cd frontend
npm run dev
```

Open `http://localhost:5173`

The backend fetches RSS on startup and then refreshes automatically every hour.

---

## Configuration

### `.env`

```env
LLM_PROVIDER=deepseek          # anthropic | openai | gemini | deepseek
DEEPSEEK_API_KEY=sk-...
# ANTHROPIC_API_KEY=...
# OPENAI_API_KEY=...
# GEMINI_API_KEY=...
```

### `sources.yaml`

```yaml
- name: "BBC World"
  bias_tag: "western-uk"
  lang: "en"
  rss: "http://feeds.bbci.co.uk/news/world/rss.xml"
```

`bias_tag` is a free-form label used by the LLM to attribute framing to camps.

---

## API Endpoints

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/map/heat?date=YYYY-MM-DD` | Country → article count heatmap |
| `GET` | `/api/map/articles?country=X&date=X&week=true` | Articles for a country/date |
| `POST` | `/api/analyze` | Start analysis job, returns `job_id` |
| `GET` | `/api/analyze/{job_id}/stream` | SSE progress stream |
| `GET` | `/api/analyze/{job_id}/result` | Full analysis result JSON |
| `GET` | `/api/briefs` | List saved analysis briefs |
| `GET` | `/api/cache/status` | Cache age and article count |
| `POST` | `/api/cache/refresh` | Manually trigger RSS refresh |
