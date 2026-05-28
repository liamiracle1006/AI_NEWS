# AI_NEWS — 项目上下文

> Claude Code 维护规则：每次对话结束前更新「当前进展」「踩过的坑」「下一步」三个 section，替换不追加，总长 < 150 行。

## 项目目标
- 多视角地缘政治新闻分析器：从意识形态对立的 RSS 源抓同一事件，用 LLM 剥离情绪/框架，对比"共识事实"与"叙事分歧"
- 提供交互式世界地图（按国家热力着色）+ 深度分析面板 + 周分析模块（叙事弧、信息延迟、桑基图等）
- 定位是"叙事光谱分析仪"，不是"真相判定器"

## 技术栈

| 层次 | 技术 | 说明 |
|---|---|---|
| 后端框架 | FastAPI + uvicorn | 异步路由 + SSE 进度流 |
| RSS 抓取 | feedparser | 解析 RSS XML，拿标题/摘要/链接/时间 |
| 正文提取 | trafilatura | 抓网页提取正文（深度分析才用，15s 超时） |
| LLM | DeepSeek（默认）/ Anthropic / OpenAI / Gemini | 通过 `news/llm/base.py` 的 LLMProvider 抽象切换 |
| 数据模型 | pydantic v2 | Article、ArticleFacts、WeeklyExtras 等 |
| 缓存 | 本地 JSON | `cache/articles_YYYY-MM-DD.json`，每小时自动刷新 |
| 前端 | Vite + React 18 + TypeScript + Tailwind | proxy /api → :8000 |
| 可视化 | react-simple-maps（世界地图）+ @nivo/sankey（桑基图） | |

## 当前文件结构

```
AI_NEWS/
├── api/
│   ├── main.py              FastAPI 入口；启动时建缓存 + 每小时自动刷新循环
│   ├── routes.py            所有 HTTP 路由（/analyze /map/heat /map/articles /briefs /cache/...）
│   └── geo_keywords.py      ~70 国关键词映射，地图热力图用
├── news/
│   ├── config.py            .env + sources.yaml 加载
│   ├── models.py            Pydantic 模型
│   ├── ingest.py            feedparser + trafilatura 抓取
│   ├── cluster.py           关键词过滤（标题→摘要→正文 三级级联）
│   ├── article_cache.py     每日 JSON 缓存读写（CACHE_WINDOW_HOURS=168 即 7 天）
│   ├── pipeline.py          完整分析流程 + 周分析五个模块
│   ├── output.py            Markdown 简报生成
│   └── llm/
│       ├── base.py          LLMProvider 抽象 + get_provider 工厂
│       ├── prompts.py       所有 prompt 模板（事实提取/交叉比对/实体追踪/周分析×3）
│       └── *_provider.py    四家 LLM 适配器
├── frontend/src/
│   ├── App.tsx              主页面：地图 + 分析表单 + 结果区
│   ├── api.ts               fetch 封装 + SSE hook
│   ├── types.ts             TS 类型镜像 Pydantic 模型
│   └── components/
│       ├── WorldMap.tsx          SVG 世界地图 + 热力着色
│       ├── RegionPanel.tsx       右侧滑入面板（今天/本周文章列表）
│       ├── AnalyzeForm.tsx       关键词输入表单
│       ├── ProgressBar.tsx       SSE 进度条
│       ├── ResultView.tsx        分析结果总容器
│       ├── ConsensusSection.tsx  共识事实
│       ├── DivergenceCard.tsx    叙事分歧
│       ├── GapSection.tsx        可疑缺口
│       ├── EntityCard.tsx        人物状态卡片
│       ├── ArticleDigestList.tsx 各方报道摘要（每篇独立卡）
│       ├── WeeklyView.tsx        周分析五模块（热度/桑基/时间线/弹性/延迟）
│       ├── SourceList.tsx        来源链接列表
│       └── HistoryPanel.tsx      历史简报浏览
├── sources.yaml             16 个新闻源配置（含 bias_tag）
├── requirements.txt         Python 依赖
├── cache/                   运行时缓存（gitignore）
├── briefs/                  分析结果归档（gitignore）
├── README.md                用户向说明
└── PROGRESS.md              历史阶段日志（Phase 0-8 详细记录，不要往里加新内容）
```

## 当前进展

已完成（Phase 0-9）：
- RSS 抓取 + 多 LLM 抽象 + 单篇事实提取
- 关键词聚类 + 交叉比对 + Markdown 简报
- 实体追踪（带 context/key_quotes 上下文，过滤单次提及噪声）
- FastAPI 后端 + SSE 进度流 + React 前端
- 交互式世界地图 + 国家面板（今天/本周切换）
- 按日期的文章缓存（每天一份 JSON，可历史回溯）
- 周分析五模块：热度趋势、桑基图聚光灯转移、叙事时间线、叙事弹性、信息延迟
- 各方报道摘要板块（逐篇展示）
- 后端启动时自动抓 RSS + 每小时后台自动刷新
- LICENSE（非商用）
- **Phase 9（CoW 插件版）**：源码在 `wechat_plugin/`，由 `sync_to_cow.ps1` 同步到 CoW 副本。已实测可用，但需常驻第二个 CoW 进程
- **Phase 9b（路径 B · 单仓库整合）**：抽出 CoW 的 weixin channel 进 `AI_NEWS/wechat/`，去掉对 CoW 的依赖：
  - `wechat/ilink_api.py`（协议层，从 CoW 复制后只换 logger）
  - `wechat/ilink_channel.py`（精简版长轮询 + QR 登录 + 凭证持久化 + 发送）
  - `wechat/dispatcher.py`（替代旧 plugin 的 ai_news.py，直接基于 IncomingMessage 分发）
  - `wechat/types.py`（IncomingMessage / OutgoingReply / ReplyType / IlinkConfig，替代 bridge.context）
  - `wechat/{intent_parser,formatter,renderer,scheduler}.py`（从 wechat_plugin 搬过来，去掉 CoW 引用）
  - 启用方式：`.env` 设 `WECHAT_ENABLED=true`，**单条 `uvicorn api.main:app` 就启动一切**
  - CoW 副本仍可作为备选（如需多 channel 时）

待实现 / TODO：
- 路径 B 用真·微信验证一遍（terminal 模式没有了，需直接扫码测）
- 深度分析速度优化（详见 `~/.claude/plans/readme-progress-squishy-meerkat.md` 番外）

## 踩过的坑

- **关键词命中过宽**：原本标题/摘要/正文同等级匹配，导致台湾分析里混入只在文末提及一句台湾的无关文章。改为三级级联（先标题，不够再摘要，再不够才正文）
- **地图面板"附带提及"噪声**：`/api/map/articles` 必须只用标题匹配，**不能 fallback 到摘要**，否则 SCMP 等大站随便一篇都会因摘要含国名被吞进来
- **`ROC` 子串匹配 Morocco**：地理关键词不能用三字母缩写，已从 Taiwan 关键词中移除
- **trafilatura 默认无超时**：抓正文会卡死，必须用 `use_config()` 设 `DOWNLOAD_TIMEOUT=15`，外层再加 `concurrent.futures.wait(timeout=30)` 兜底
- **LLM 偶尔输出英文**：`FACT_EXTRACTION_SYSTEM` 即便有 Rule 6 要求中文，DeepSeek 处理英文文章时仍会偶发英文输出。已在 user 模板尾部加强提醒
- **PowerShell 的 `curl` 是 `Invoke-WebRequest` 别名**：调试 API 必须用 `curl.exe`
- **`@nivo/sankey` 与 `react-simple-maps` peer dep 冲突**：安装必须加 `--legacy-peer-deps`
- **`.env` 必须在 `.gitignore` 里**：当前已正确忽略，未泄露过 API key

## 下一步

- 跑通 CoW 微信测试：装依赖 → 配置 deepseek key → 扫码登录小号 → 私聊验证 "分析以色列"
- 实现 `send_to_user` 主动推送（CoW weixin channel 的 nickname → user_id 映射）
- 视情况优化图片渲染（Pillow 朴素版可换 imgkit/html2image）
