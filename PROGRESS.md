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

## 下一步计划（Phase 3 · 待启动）

**目标**：在现有交叉比对结果上叠加"人物追踪层"。

**规划**
- 在事实提取时增加 NER 子字段：`people: [{name, position, action, status_change}]`
- 新增 `ENTITY_TRACKING` prompt：汇总一次 `analyze` 内出现的所有政治人物
- 报告新增"## 👤 人物状态速览"板块
- （可选）`streamlit run app.py` 做最简 UI

**触发条件**：Phase 2 实际跑通、用户验收报告质量后启动。

---

## 约定

- **每个 commit 必须更新本文档**。如果改动小到不值得开新节，就追加到最近一节的"后续修补"小节里。
- **阶段完结才打勾**。每个阶段要在 Commit 里可独立运行、可独立验收。
