# 项目进展记录

> 多视角时政新闻交叉比对与分析系统（MVP）  
> 分支：`claude/news-analysis-mvp-VoHga`
>
> 每完成一块工作就在这里追加一节。格式固定：
> **阶段标题 → 目标 → 交付文件 → 关键决策 → 已知限制 → Commit**

---

## Phase 0 · 项目骨架与规划 · 2026-04-15

**目标**  
和产品方对齐期望，砍掉过度工程（LangChain / 向量库），确定分阶段路线图。

**关键决策**
- **产品定位**：从"寻找绝对真相"改为"**叙事光谱分析仪**"。LLM 无法验证真伪，只能对比叙事。
- **技术栈**：`feedparser` + `trafilatura` + `pydantic` + 多家 LLM SDK；拒绝 LangChain。
- **四阶段路线图**：
  1. 数据获取 + LLM 抽象 + 单篇事实提取 ✅
  2. 关键词驱动 + 交叉比对 + Markdown 报告 ✅
  3. 人物追踪（NER）+ 可选 Streamlit UI ⏳
  4. SQLite 归档 + 人物时间线 + 关系图 ⏳（可选）

**交付文件**：无代码，仅规划

---

## Phase 1 · RSS 数据获取 + LLM 抽象层 · 2026-04-15

**目标**  
把 RSS 抓取、正文提取、LLM 调用这三件事做成可独立测试的三个小模块。

**交付文件**
| 文件 | 职责 |
|---|---|
| `requirements.txt` | 依赖清单（feedparser / trafilatura / pydantic / 三家 LLM SDK） |
| `.env.example` | 环境变量模板（API keys、provider 选择、抓取窗口） |
| `sources.yaml` | 数据源配置（初版 6 个英文源） |
| `.gitignore` | 基本忽略规则 |
| `news/config.py` | `.env` + `sources.yaml` 加载器，返回冻结的 `AppConfig` |
| `news/models.py` | Pydantic：`Article`、`ExtractedFact`、`ArticleFacts` |
| `news/ingest.py` | `fetch_source()` / `fetch_all()`：feedparser → trafilatura 正文提取，单源失败不中断 |
| `news/llm/base.py` | `LLMProvider` 抽象类 + `get_provider()` 工厂 |
| `news/llm/anthropic_provider.py` | Claude 适配器（默认 `claude-sonnet-4-6`） |
| `news/llm/openai_provider.py` | OpenAI 适配器 |
| `news/llm/gemini_provider.py` | Gemini 适配器（`google-genai` SDK） |
| `news/llm/prompts.py` | `FACT_EXTRACTION_SYSTEM` + `build_fact_extraction_prompt()` |
| `news/main.py` | CLI：`fetch` / `test-extract -n N` |
| `README.md` | 使用说明与路线图 |

**关键决策**
- **Provider 抽象**：所有模型走统一 `complete(system, user, json_mode=...)`，一行换厂商。
- **正文提取**：用 `trafilatura` 而非纯 `BeautifulSoup`，新闻站点清洁度高得多。
- **容错**：单篇抓取失败 → 记日志跳过；不让一条坏 RSS 毁掉整轮。
- **正文截断**：> 8000 字符自动截断，避免 token 爆炸。

**已知限制**
- Reuters / AP 的官方 RSS 不稳定，使用时可能需要换源或走 RSSHub。
- 没做跨天去重（Phase 4 配合 SQLite 再做）。

**Commit**：`a5ab102`

---

## Phase 1.5 · 双语源 + DeepSeek 支持 · 2026-04-15

**目标**  
把数据源改成"强立场对比的中英混搭"；加入 DeepSeek 作为默认 LLM 供应商。

**交付文件**
| 文件 | 改动 |
|---|---|
| `sources.yaml` | 重写为 8 个源的立场光谱：Reuters / BBC（西方）、Al Jazeera / RT（中东俄）、新华网 / 观察者网（中国官方/民族主义）、联合早报中国+国际（海外中文）。中文源统一走 RSSHub 代理 |
| `news/llm/deepseek_provider.py` | **新增** DeepSeek 适配器，复用 openai SDK + `base_url=https://api.deepseek.com` |
| `news/llm/base.py` | `get_provider()` 识别 `deepseek` 分支 |
| `news/config.py` | 增加 `DEEPSEEK_API_KEY` / `DEEPSEEK_MODEL` |
| `.env.example` | 默认 `LLM_PROVIDER=deepseek`，默认模型 `deepseek-chat` |

**关键决策**
- **为什么选 DeepSeek 作为 MVP 默认**：
  1. 用户只有 DeepSeek API Key（Claude Max 订阅 ≠ Anthropic API）。
  2. 价格是 GPT-4o-mini 的 1/10 数量级；每天跑 3-5 个话题月成本不到 ¥15。
  3. 中文语义理解优于 GPT-4o-mini，适合本项目的双语场景。
- **为什么不换全局 SDK**：DeepSeek 协议和 OpenAI 兼容，直接 `base_url` 替换即可。
- **中文源统一走 RSSHub**：新华网/观察者网/联合早报都没有稳定官方 RSS；文档里提供了 `docker run diygod/rsshub` 的自建 fallback。

**已知限制**
- 公共 RSSHub 实例有速率限制，重度使用需自建。
- `deepseek-reasoner`（R1）没接，对本项目的结构化抽取用不上，成本高。

**Commits**：`850a396` · `5349c8a`

---

## Phase 2 · 关键词聚类 + 交叉比对 + Markdown 报告 · 2026-04-15

**目标**  
用户输入一个关键词（如"加沙"），系统自动从所有源抓取命中报道，剥离情绪，交叉比对，产出一份中文叙事分析报告。

**交付文件**
| 文件 | 职责 |
|---|---|
| `news/cluster.py` | **新增** 两级关键词过滤器。Level 1 匹配标题/摘要（免费）；< min_hits 时 Level 2 扩展到正文。支持 `|` 分隔同义词（`"加沙|Gaza|gaza"` 一次匹配所有中英源） |
| `news/pipeline.py` | **新增** 端到端串联：`analyze_topic()` = fetch → filter → `extract_facts_batch()` → `cross_reference()`。单篇 LLM 失败/JSON 解析失败自动跳过 |
| `news/output.py` | **新增** Markdown 渲染器。`BIAS_LABEL_ZH` 字典把 `bias_tag` 翻译成中文标签（"西方通讯社/中东视角/中国官方/中国民族主义/海外中文"等） |
| `news/llm/prompts.py` | **扩展** `CROSS_REFERENCE_SYSTEM` + `build_cross_reference_prompt()`。Prompt 强制简体中文输出、强制 JSON、明确"跨阵营共识权重 > 同阵营共识" |
| `news/models.py` | **扩展** `Divergence`、`SourceRef`、`CrossReferenceResult`；`ArticleFacts` 增加 `title` 字段方便报告引用 |
| `news/main.py` | **扩展** 新增 `analyze <关键词>` 子命令，参数 `--max` / `--min-hits` / `--out-dir` / `--print` |
| `README.md` | 更新 Phase 2 使用示例 |

**CLI 用法**
```bash
python -m news.main analyze "加沙|Gaza"
python -m news.main analyze "乌克兰|Ukraine|Kyiv|Kiev" --max 8
python -m news.main analyze "美国大选|Trump|Harris" --print
```

**产物结构**（`briefs/<话题>_<时间戳>.md`）
```
# 每日简报：<话题>
> 命中 N 篇 · 覆盖 M 个立场阵营

## 🤝 共识事实
- 跨阵营都承认的事实（最可信）

## ⚔️ 叙事分歧
### 分歧 1：<争议点>
- **西方通讯社**：...
- **中国官方**：...
> 📝 观察：<模型给出的叙事偏好观察>

## 🕳️ 可疑缺口
- 仅单一阵营提及、对立阵营理应跟进却未跟进的信息

## 🔗 原文链接
- [立场标签][标题](url) — 来源名

<details>附录：各篇文章的事实提取明细</details>
```

**关键决策**
- **输出语言强制中文**：`FACT_EXTRACTION` 和 `CROSS_REFERENCE` 两个 prompt 都加了"输出必须简体中文"的硬约束，解决双语输入时的输出语言混乱。
- **跨阵营共识加权**：prompt 里明确告诉模型——"西方 + 中国官方都承认的事 >> 十家西方都承认的事"。这是项目真正的价值点。
- **关键词过滤两级 fallback**：省 token（标题匹配 0 成本），只在命中不足时扩展到正文。
- **"可疑缺口"章节**：让模型主动指出"仅一家提到、理应被对手跟进却没被跟进"的信息，帮助用户察觉单方面操纵。
- **`min_hits` 参数**：命中太少时不强行交叉比对（<3 篇意义不大）。
- **阵营标签中文化查字典**：用 `BIAS_LABEL_ZH` 硬编码映射，未知 tag 回退到原字符串，零风险。

**已知限制**
- 话题内**未做子事件再聚类**：如果用户输 "中东"，各篇可能聊的是完全不同的冲突。建议关键词尽量具体（"加沙" 比 "中东" 好）。
- **未做跨天去重**：同一篇报道明天跑还会再进结果。Phase 4 配合 SQLite 解决。
- **DeepSeek JSON mode 偶发回退**：如果 `deepseek-chat` 某次没返回合法 JSON，`_safe_json()` 会兼容 ` ```json` fences；真解析失败则跳过该篇。
- **单次成本估算**：10 篇文章 × 每篇 ~5k token 输入 + 一次 ~15k token 的交叉比对 ≈ ¥0.05-0.15/次。

**Commit**：`ef69b05`

---

## Phase 2.1 · 抓取窗口从 24h 扩到 72h · 2026-04-15

**目标**  
把默认抓取窗口从 1 天扩到 3 天，避免周末/慢话题的新闻池太薄。

**改动**
- `.env.example`：`FETCH_WINDOW_HOURS=24 → 72`
- `.env.example`：`MAX_PER_SOURCE=10 → 15`（窗口变宽，每源相应放宽）

**为什么连 `MAX_PER_SOURCE` 一起改**  
如果只扩窗口不扩配额，三天的新闻会被截到跟一天一样的条数，等于白扩。  
15 条 × 8 源 = 最多 120 篇，再经关键词过滤通常只剩 5-15 篇，成本完全可控。

**需要用户做的事**  
如果已有 `.env` 文件，手动把值改掉；没 `.env` 只动 `.env.example` 不会生效。

**Commit**：见本节末尾

---

## Phase 2.5 · Prompt 增强 · 2026-04-21

**目标**
让单篇事实提取和交叉比对的输出质量更高，从"机械字段"升级为有分析深度的报告。

**改动**
| 文件 | 改动内容 |
|---|---|
| `news/models.py` | `ExtractedFact` 增加 `context: Optional[str]`（事件背景）和 `key_quotes: List[str]`（关键引言，格式 `"[人物]: 原话"`）；`ArticleFacts` 增加 `published_at: Optional[datetime]` |
| `news/llm/prompts.py` | `FACT_EXTRACTION_SYSTEM`：`action` 允许 2-3 句捕捉完整经过，新增 `context`/`key_quotes` 字段要求 |
| `news/llm/prompts.py` | `CROSS_REFERENCE_SYSTEM` 重写：共识事实末尾标注来源阵营及日期（`来源：西方通讯社 [2026-04-20]`）；`camp_claims` 要求自然散文而非列表；`observation` 必须解释**为什么**有分歧；少于 2 个阵营的不算分歧 |
| `news/llm/prompts.py` | `build_cross_reference_prompt()`：文章块中带入 `date=YYYY-MM-DD` 字段 |

**关键决策**
- 时效性问题：`published_at` 跟随文章进入交叉比对 prompt，让模型能在共识和分歧中标注具体日期，解决"叙事没有时间锚点"的问题。
- 机械语言问题：`observation` 强制要求有分析，解释叙事差异的**原因**（框架选择/利益驱动/信息差）。

**Commit**：包含在 `ae47851`

---

## Phase 2.6 · 关键词自动同义词扩展 · 2026-04-21

**目标**
用户输入"加沙"，系统自动扩展为`加沙|Gaza|Gaza Strip|哈马斯|Hamas`，提升多语言来源的命中率。

**改动**
| 文件 | 改动内容 |
|---|---|
| `news/llm/prompts.py` | 新增 `SYNONYM_EXPANSION_SYSTEM` + `build_synonym_expansion_prompt()`，轻量 LLM 调用，JSON 输出 `{"synonyms": [...]}` |
| `news/pipeline.py` | 新增 `expand_keyword(cfg, keyword) -> str`，把同义词列表以 `|` 合并后返回 |
| `api/routes.py` | `POST /api/analyze`：在创建 job 前先调用 `expand_keyword()`，返回 `expanded_keyword` 字段 |
| `frontend/src/api.ts` | `startAnalyze()` 返回 `{jobId, expandedKeyword}` |
| `frontend/src/App.tsx` | 显示"搜索关键词已扩展为：`...`"的提示 pill |

**Commit**：包含在 `ae47851`

---

## Phase 3 · 人物追踪（NER + 实体归一化）· 2026-04-21

> **状态**：已实现。  
> **依赖**：Phase 1 / Phase 2 的 fact extraction 已稳定跑通。

### 目标
在 `analyze` 产出的每篇简报里，加一个"本话题涉及的政治人物 + 他们在这一轮报道里的动作/状态变化"清单。长期（Phase 4）这些条目会被归档，形成人物权力变动时间线。

### 设计决策

**Q1：NER 嵌入 FACT_EXTRACTION 还是独立 prompt？**  
→ **独立 prompt（`ENTITY_TRACKING`）**，单独一次调用在交叉比对之后跑。
- 理由：事实提取 prompt 已经够长，再加人物字段会让模型分心，导致两边都做不好。
- 理由：独立可开关。`analyze ... --no-people` 跳过省钱。
- 代价：每次 `analyze` 多一次 LLM 调用（约 +¥0.02）。

**Q2：实体归一化怎么做？**  
→ **让同一个 prompt 一次性做合并**：把所有篇文章里的人物一次性喂给模型，要求它输出"已合并的规范化人物清单"。
- MVP 阶段不引入向量/fuzzy match；模型自己能判断"习近平"="中国国家主席"="Xi Jinping"。
- 输出 schema 里 `aliases: [string]` 保留所有原始称呼，供用户自己核对。

**Q3：跨篇文章的立场归因怎么给？**  
→ 每个人物事件里带 `per_source_framing: { bias_tag: "该阵营怎么写这个人的" }`，明确谁在说什么。

### 数据模型（追加到 `news/models.py`）

```python
class EntityEvent(BaseModel):
    canonical_name: str              # 规范化姓名（中文优先）
    aliases: List[str]               # 原文里出现过的所有称呼
    position: Optional[str]          # 报道中最明确的头衔，如"伊朗总统"
    action_or_status: str            # 此事件中此人做了/遭遇了什么
    status_change: Optional[str]     # 若属职务变动/状态转折（辞职/被捕/失踪/任命）
    per_source_framing: Dict[str, str]  # bias_tag -> 该阵营的描述
    sources: List[str]               # 提到此人的 article_url 列表

class EntityTrackingResult(BaseModel):
    topic: str
    generated_at: datetime
    entities: List[EntityEvent]
```

### 新增 Prompt（`news/llm/prompts.py`）

```
ENTITY_TRACKING_SYSTEM
─────────────────────
You are a political-entity tracker. Given fact extractions from multiple
articles about a topic, produce a deduplicated list of named political
figures (heads of state, ministers, generals, spokespersons, opposition
leaders) who appear with meaningful agency.

RULES:
1. MERGE aliases. "习近平" / "中国国家主席" / "Xi Jinping" -> one entity
   with canonical_name="习近平", aliases=["Xi Jinping","中国国家主席",...].
2. Keep ONLY politically meaningful actions: 任命/辞职/被捕/失踪/
   出访/表态/签署/会晤/军事命令 等. Ignore background mentions.
3. For each entity, per_source_framing: if different camps describe
   the same person's action differently, surface it (e.g. western-wire:
   "condemned the strike" vs russia-state: "responded to provocation").
4. Output Simplified Chinese. Strict JSON per user schema. No prose.
```

### Pipeline 改动（`news/pipeline.py`）

```python
def analyze_topic(cfg, keyword, *, max_articles=10, track_people=True):
    ...
    cross = cross_reference(provider, keyword, facts_bundle)
    entities = None
    if track_people and facts_bundle:
        entities = track_entities(provider, keyword, facts_bundle)
    return facts_bundle, cross, entities
```

### Markdown 输出新板块（`news/output.py`）

```
## 👤 人物状态速览

### 习近平（中国国家主席）
别名：Xi Jinping · 中国国家主席 · 习主席  
**动作**：与伊朗外长通话，重申中方立场  
**状态变化**：—  
**阵营差异**：
- 西方通讯社：称此举为"外交斡旋姿态"
- 中国官方：定性为"积极推动政治解决"

### <下一位>
...
```

### CLI 改动

```bash
python -m news.main analyze "加沙|Gaza"              # 默认带人物追踪
python -m news.main analyze "加沙|Gaza" --no-people  # 跳过，省钱
```

### 已预判的坑

1. **DeepSeek 对"政治敏感人物"可能做内容审查**，返回空列表或泛化描述。对策：Prompt 明确"事实性提及，不做评价"；真出问题切换到 Anthropic/OpenAI。
2. **合并过度**：模型可能把"普京"和"梅德韦杰夫"合并（都与克里姆林宫相关）。对策：Prompt 明确要求"name 字段必须是确定的自然人，不合并不同人"。
3. **小人物噪声**：地方官员、发言人、记者被拉进来。对策：Prompt 明确"仅限部长级及以上 / 事件主角"。

### 实现细节

**改动文件**
| 文件 | 改动 |
|---|---|
| `news/models.py` | 新增 `EntityEvent` 和 `EntityTrackingResult` Pydantic 模型 |
| `news/llm/prompts.py` | 新增 `ENTITY_TRACKING_SYSTEM` + `build_entity_tracking_prompt()` |
| `news/pipeline.py` | 新增 `track_entities(provider, keyword, facts_bundle) -> EntityTrackingResult` |
| `news/output.py` | `render_markdown()` 增加"👤 人物状态速览"板块 |
| `news/main.py` | 新增 `--no-people` flag；`analyze_topic()` 返回 3-tuple `(facts_bundle, cross, entities)` |

**并行提取优化**
- 把原来顺序提取改为 `ThreadPoolExecutor(max_workers=5)` 并行，速度提升约 4-5×
- 新增 `on_progress` 回调，每完成一篇通知前端进度

**Commit**：`ae47851`

---

## Phase 3.5 · FastAPI 后端 · 2026-04-21

**目标**
把命令行 pipeline 包成 HTTP API，支持异步分析 + SSE 实时进度推送。

**新增文件结构**
```
api/
├── __init__.py
├── main.py      # FastAPI app，CORS，路由挂载
└── routes.py    # 所有路由 + 后台 worker
```

**API 设计**

| 端点 | 说明 |
|---|---|
| `POST /api/analyze` | 触发分析，立即返回 `{job_id, expanded_keyword}` |
| `GET /api/analyze/{id}/stream` | SSE 流，推送 `{step, message}` 进度事件 |
| `GET /api/analyze/{id}/result` | 分析完成后返回完整结构化 JSON |
| `GET /api/briefs` | 列出 `briefs/` 历史简报，含 `article_count`、`has_data` 字段 |
| `GET /api/briefs/{id}` | 返回 Markdown 原文 |
| `GET /api/briefs/{id}/data` | 返回同名 `.json` 结构化结果（供历史面板加载） |

**关键技术决策**
- Job 存在内存字典 `{job_id: {...}}`（MVP；Phase 4 SQLite 接手）
- SSE 用 `asyncio.Queue` 桥接阻塞的 pipeline 线程和异步 HTTP 流
- 后台 worker 用 `loop.run_in_executor()` 运行同步 pipeline，避免阻塞事件循环
- 每次分析完成后自动将结果保存为 `briefs/<topic>_<timestamp>.json`，支持历史回放

**已知修复**
- Python 3.14 已废弃 `asyncio.get_event_loop()`，改用 `asyncio.get_running_loop()`
- 前端需在 SSE 收到 `step=error` 时立即停止，不再调用 `/result`（否则返回 500）

**Commit**：`ae47851`

---

## Phase 3.6 · React 前端 · 2026-04-21

**目标**
用 React + TypeScript 构建完整 Web UI，展示分析结果、实时进度、历史记录。

**技术栈**
- Vite + React 18 + TypeScript
- TailwindCSS v4（`@tailwindcss/vite` 插件）
- EventSource API（浏览器原生，无额外依赖）

**组件结构**
```
frontend/src/
├── App.tsx                    # 主状态管理、SSE 订阅、历史加载
├── api.ts                     # fetch 封装 + EventSource 订阅
├── types.ts                   # TypeScript 接口 + 阵营颜色/标签工具
└── components/
    ├── AnalyzeForm.tsx         # 关键词输入、参数、提交
    ├── ProgressBar.tsx         # SSE 实时进度（含文章数进度解析）
    ├── ResultView.tsx          # 结果总容器
    ├── ConsensusSection.tsx    # 🤝 共识事实
    ├── DivergenceCard.tsx      # ⚔️ 叙事分歧（可展开/折叠）
    ├── EntityCard.tsx          # 👤 人物卡片（阵营差异展示）
    ├── GapSection.tsx          # 🕳️ 可疑缺口
    ├── SourceList.tsx          # 🔗 原文链接（按阵营分色）
    ├── CampBadge.tsx           # 阵营标签徽章
    └── HistoryPanel.tsx        # 历史记录滑入面板
```

**阵营颜色编码**
| 阵营 | 颜色 |
|---|---|
| western-wire（西方通讯社）| 蓝 |
| western-uk（英国视角）| 天蓝 |
| middle-east（中东视角）| 绿 |
| russia-state（俄方官方）| 橙 |
| china-state（中国官方）| 红 |
| china-nationalist（中国民族主义）| 玫红 |
| overseas-chinese（海外中文）| 紫 |

**历史面板（HistoryPanel）**
- 点击"📋 历史记录"从右侧滑入面板
- 列出所有历史分析，显示话题、时间、文章数
- 无对应 JSON 的历史（仅 Markdown）显示"仅 Markdown"标识并禁用加载
- 点击条目调用 `/api/briefs/{id}/data` 加载结构化结果，直接渲染到主界面

**Commit**：`ae47851`

---

## Phase 4 · 历史归档 + 人物时间线 + 关系图谱 · 设计

> **状态**：设计冻结。Phase 4 是"可选的长线价值"：单次 `analyze` 不靠它也能读。  
> **依赖**：Phase 3 实体归一化稳定。

### 目标

把每天 `analyze` 的产出持久化，让用户能问出这三种问题：

1. **"过去 30 天，加沙话题下的叙事分歧点是怎么演变的？"** → 话题时间线
2. **"过去 3 个月，某人物的职务/状态变化轨迹是什么？"** → 人物时间线
3. **"这些人物之间谁和谁一起出现过？"** → 关系图

### 技术选型（故意保守）

| 能力 | 选型 | 理由 |
|---|---|---|
| 本地存储 | **SQLite**（`sqlite3` 标准库） | 零依赖，单文件可备份 |
| ORM | **不用**，手写 SQL | 数据模型简单，ORM 是负担 |
| 关系图渲染 | **`networkx` + `pyvis`** | 一个 HTML 文件本地打开，无前端工程 |
| 向量/语义搜索 | **不做** | MVP 边界外 |

**新增依赖**：只加 `networkx` 和 `pyvis`（都是纯 Python，装起来不麻烦）。

### 数据库 Schema（`news/db.py`）

```sql
-- 每篇文章归档一次；article_hash = sha1(url) 用作幂等键
CREATE TABLE articles (
    article_hash  TEXT PRIMARY KEY,
    source_name   TEXT NOT NULL,
    bias_tag      TEXT NOT NULL,
    lang          TEXT,
    title         TEXT NOT NULL,
    url           TEXT NOT NULL,
    published_at  TEXT,
    fetched_at    TEXT NOT NULL,
    body_snippet  TEXT    -- 前 2000 字，便于搜索
);

-- 每次 analyze 跑一次就一条
CREATE TABLE analyses (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    topic         TEXT NOT NULL,
    keyword_expr  TEXT NOT NULL,
    generated_at  TEXT NOT NULL,
    brief_path    TEXT,     -- 生成的 Markdown 文件路径
    cross_ref_json TEXT     -- CrossReferenceResult 的原始 JSON（完整存）
);

-- 事件 ↔ 文章：多对多
CREATE TABLE analysis_articles (
    analysis_id   INTEGER REFERENCES analyses(id),
    article_hash  TEXT REFERENCES articles(article_hash),
    PRIMARY KEY (analysis_id, article_hash)
);

-- 人物规范表；canonical_name 作为自然主键的人类可读版本
CREATE TABLE entities (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    canonical_name  TEXT UNIQUE NOT NULL,
    latest_position TEXT,
    aliases_json    TEXT,      -- JSON 数组，追加合并
    first_seen_at   TEXT,
    last_seen_at    TEXT
);

-- 人物 ↔ 事件：每次 analyze 发现的动作/状态
CREATE TABLE entity_events (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    entity_id       INTEGER REFERENCES entities(id),
    analysis_id     INTEGER REFERENCES analyses(id),
    topic           TEXT NOT NULL,
    action_or_status TEXT,
    status_change   TEXT,
    per_source_framing_json TEXT,
    seen_at         TEXT NOT NULL
);

CREATE INDEX idx_events_entity_time ON entity_events(entity_id, seen_at);
CREATE INDEX idx_articles_published ON articles(published_at);
```

### 模块划分

| 新文件 | 职责 |
|---|---|
| `news/db.py` | SQLite 连接池、schema 初始化（`init_db()`）、所有 upsert/query 语句 |
| `news/archive.py` | 把 `analyze_topic()` 的返回值写进 DB（幂等：同 url 不重复存） |
| `news/timeline.py` | `timeline_for_person()` / `timeline_for_topic()` 查询 + Markdown 渲染 |
| `news/graph.py` | 用 `networkx` 构图（节点=人物，边=共同出现事件），`pyvis` 输出 HTML |
| 修改：`news/main.py` | 新增 `archive` / `timeline` / `graph` 三个子命令 |

### 实体归一化升级（增量更新）

每次新 `analyze` 的实体清单进库时：

```python
for e in new_entities:
    existing = find_entity_by_alias(e.canonical_name, e.aliases)
    if existing:
        merge_aliases(existing.id, e.aliases)   # 追加不覆盖
        update_latest_position(existing.id, e.position)
    else:
        insert_entity(e)
```

匹配策略：先按 `canonical_name` 精确匹配；找不到再按别名集合的交集是否非空。**不引入模糊匹配**，宁可漏合并（用户能手动改 DB）也不错合并。

### 新增 CLI

```bash
# 跑完 analyze 后自动归档（或手动）
python -m news.main analyze "加沙" --archive
python -m news.main archive                  # 把历史 briefs/ 全部回灌入库

# 查询
python -m news.main timeline --person "普京" --days 90
python -m news.main timeline --topic "加沙" --days 30

# 关系图（输出 HTML，浏览器打开）
python -m news.main graph --topic "加沙" --days 30 --out graph.html
python -m news.main graph --person "普京" --depth 2
```

### Markdown 时间线输出示例

```
# 人物时间线：普京（过去 90 天）

## 2026-04-12
- **动作**：签署新一轮动员令
- 来源阵营：russia-state / western-wire
- 阵营分歧：俄方定性为"周期性征兵"，西方定性为"战争升级"

## 2026-03-28
- **状态变化**：解除国防部长绍伊古职务
...
```

### 关系图输出

- 节点大小 = 出现次数
- 节点颜色 = 主要关联的 `bias_tag`
- 边粗细 = 共同出现的话题数
- Hover 显示最近一次的 `action_or_status`

### 已预判的坑

1. **人物合并错误不可逆**：一旦把两个不同人合并，后续所有事件都挂到错人身上。对策：提供 `news/main.py entities split <id> --keep <alias>` 命令来分裂。
2. **SQLite 在长期使用后可能膨胀**：正文摘要字段吃空间。对策：`body_snippet` 截断到 2000 字符，历史超过 180 天的自动归档到冷存储（不做，用户手动清理）。
3. **关系图节点过多不可读**：一个活跃话题 30 天可能有 50+ 人物。对策：默认只显示 top-N（按事件数排序），`--limit N` 控制。

### 不做清单（明确边界）

- ❌ Web 后端 / REST API（个人使用不需要）
- ❌ 实时抓取（cron 跑 `analyze` 就够）
- ❌ 多用户 / 权限
- ❌ 向量检索（除非 Phase 4 实际跑下来明显不够用）
- ❌ Telegram / Twitter 接入（独立 Phase 5 或永远不做）

---

## 触发 Phase 4 代码化的条件

1. Phase 3（人物追踪）在实际话题上跑稳，输出质量满意
2. 用户有持久化历史的需求（当前 `.json` 文件方案已够用于 MVP）
3. 启动 SQLite 归档 + 时间线查询 + 关系图

---

## Phase 5 · 交互式世界热力图 · 2026-04-22

**目标**
在首页顶部常驻一张可交互的世界地图，用热力色展示全球新闻热度分布，支持点击国家/地区查看相关文章并触发深度分析。

**新增/修改文件**

| 文件 | 改动 |
|---|---|
| `api/geo_keywords.py` | **新增**。~70 个国家/地区的关键词映射表，用于 RSS 文章地理标注（零 LLM，纯字符串匹配）。台湾/西藏/新疆/香港均归入中国关键词 |
| `api/routes.py` | 新增 `GET /api/map/heat`（10 分钟缓存）、`GET /api/map/articles`（点击后拉取相关文章）、`GET /api/cache/status`、`POST /api/cache/refresh`、`GET /api/cache/sources`（调试） |
| `frontend/src/components/WorldMap.tsx` | **新增**。`react-simple-maps` SVG 地图，sqrt 着色（灰→青→橙→红），固定尺寸（540px / scale 175），无拖拽/缩放，hover tooltip，点击回调 |
| `frontend/src/components/RegionPanel.tsx` | **新增**。点击国家后从右侧滑入面板，独立请求该国相关文章（按阵营分色卡片），顶部"深度分析"按钮可触发 LLM 全文分析 |
| `frontend/src/App.tsx` | 顶部渲染 `<WorldMap>`，页面加载时请求热力数据，每 2 分钟自动轮询更新；`<RegionPanel>` 绑定点击回调 + 深度分析回调 |
| `frontend/src/api.ts` | 新增 `fetchHeatData()`、`fetchMapArticles(country)` |
| `frontend/src/types.ts` | 新增 `us-liberal`（美国主流/靛蓝）、`us-conservative`（美国保守/琥珀）、`china-hk`（香港视角/青）阵营颜色标签 |
| `news/article_cache.py` | **新增**。每日 RSS 元数据快照（`cache/articles_YYYY-MM-DD.json`），`fetch_body=False` 快速建立，`CACHE_WINDOW_HOURS=168`（7 天窗口使低频源也有内容） |
| `api/main.py` | 启动时检查今日缓存，无则在后台触发刷新 |
| `sources.yaml` | 移除所有俄罗斯源（RT/TASS/Sputnik 在新加坡全被封锁）；新增 SCMP × 2（`china-hk`，可从新加坡访问的中文视角英文源） |
| `news/llm/prompts.py` | `CROSS_REFERENCE` 改进：单阵营时不再返回空结果，改为明确列出缺席视角；新增 `us-liberal`/`us-conservative`/`china-hk` 阵营中文映射 |

**关键技术决策**

- **热力数据零 LLM**：`/api/map/heat` 完全靠字符串匹配，整体响应 < 1 秒。
- **正文懒加载**：缓存只存 RSS 元数据（标题 + 摘要），分析时才对命中的文章并行抓取正文（`ThreadPoolExecutor(max_workers=8)`），缓存建立从 30-50 分钟降至 < 30 秒。
- **政治敏感性**：台湾多边形通过 `REDIRECT` 共享中国的颜色，`ZH_NAMES` 里对应显示"中国台湾"；新加坡在 110m 分辨率下无独立多边形，热度归入马来西亚（GEO_KEYWORDS 里 Singapore 挂在 Malaysia 下）。
- **色阶**：sqrt 缩放（低热度国家不再全灰），三段渐变：灰（零）→ 青（少）→ 橙（中）→ 红（热）。

**已知限制**

- 俄罗斯 / 中国官方 RSS 源（RT、TASS、CGTN、Global Times、China Daily）在新加坡均无法抓取，目前用 SCMP 替代中文视角，俄方视角缺失。
- 110m 地图分辨率下新加坡、卡塔尔等小国无独立多边形。
- 热力数据基于 RSS 标题/摘要关键词匹配，无语义消歧（"Georgia" 可能同时命中格鲁吉亚和美国佐治亚州）。

**Commits**：`e3e13a4` · `13246ea` · `facb12b` · `a3bfb9c` 及更早数条

---

## 约定

- **每个 commit 必须更新本文档**。如果改动小到不值得开新节，就追加到最近一节的"后续修补"小节里。
- **阶段完结才打勾**。每个阶段要在 Commit 里可独立运行、可独立验收。
