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
│   ├── App.tsx · api.ts · types.ts   主页面 + fetch/SSE + TS 类型
│   └── components/                   WorldMap / RegionPanel / AnalyzeForm /
│                                     ProgressBar / ResultView / ConsensusSection /
│                                     DivergenceCard / GapSection / EntityCard /
│                                     ArticleDigestList / WeeklyView / SourceList / HistoryPanel
├── wechat/                  Phase 9b/10/12 微信入口
│   ├── dispatcher.py        路由（管理命令 / pairing / Claude pending / tools / intent / chat）
│   ├── voice.py             P12.1 voice_ack 口语化兜底
│   ├── routing_log.py       P12.2 SQLite 路由日志 + reminders + pairings
│   ├── SOUL.md / AGENTS.md  P12.3 人设 + 行为规范，dispatcher 启动加载
│   ├── channels/{base,__init__}.py  P12.6 Channel 抽象基类，IlinkChannel 继承
│   ├── ilink_{api,channel}.py iLink 协议层 + 长轮询
│   ├── intent_parser.py     关键词意图识别
│   ├── claude_sessions.py   P1.5 命名长期分支
│   ├── verify_phase2.py     P1.6 phase-2 py_compile + import 验证
│   ├── tools/               P2 工具插件（每个一目录 + SKILL.md）：echo / remind / now / translate / weather / stock_a
│   ├── task_log.md          Claude 跨 session 传话本
│   └── {formatter,renderer,scheduler}.py  输出 / 渲染 / 定时（含 reminders 循环）
├── news/{pipeline,weekly_stats}.py  分析管线 + P12.5 拆出的 pandas 数据层
├── .mcp.json                P4 MCP 配置（gitignored；.mcp.example.json 是模板）
├── .claudeignore            屏蔽 Claude 读敏感路径
├── sources.yaml             16 个新闻源配置
├── cache/  briefs/  logs/   运行时数据（gitignore）
├── README.md  PROGRESS.md   用户说明 + Phase 0-8 历史
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
- **Phase 9（CoW 插件版）**：源码在 `wechat_plugin/`，由 `sync_to_cow.ps1` 同步到 CoW 副本。可用但需常驻第二个 CoW 进程
- **Phase 9b（单仓库整合）**：抽出 CoW weixin channel 进 `wechat/`，去 CoW 依赖。启用方式：`.env` 设 `WECHAT_ENABLED=true`，单条 `uvicorn api.main:app` 启动一切
- **Phase 10 P0**：语音输入（iLink `type=3` + 腾讯 ASR `voice_item.text`）+ LLM 意图救援
- **Phase 10 P1.1**：自我重启（`start_ai_news.bat` 永循环 + dispatcher "重启" 分支 → `os._exit(0)`；`AI_NEWS_BAT_LOOP=1` 安全门）
- **Phase 10 P1.2/1.3**（commit `3489897`）：Claude Code 元入口 · 强词直通 + 弱词 DeepSeek 过滤 + `CLAUDE_ALLOWED_USERS` 白名单 + 订阅模式 + stdin prompt + acceptEdits + 三选一 LLM 分类
- **Phase 10 P1.4+1.5**（`7537e9d` / `80f45d7`）：工作流级 session + 命名长期分支（"起名 X" / "继续 X"）；`~/.ai_news_claude_sessions.json` 持久化
- **Phase 10 P1.6+1.7-A**（`963d2d2` / `a26d9d1`）：phase-2 客观验证 + 强制三块测试指南
- **Phase 10 番外**（`865c2c2`）：深度分析提速 fact-extract 退避 + cross-ref 并行 + fast_mode
- **`.claudeignore`**（`04dfbe2`）：项目级 + home 级敏感路径屏蔽
- **Phase 10 P2 地基 + P4 MCP**（`da1fe21` / `fd4d415`）：`wechat/tools/` 插件自动发现；`.mcp.json` filesystem + github，需 `bypassPermissions`（acceptEdits 不解锁 MCP read）
- **Phase 12 对话感重塑 + 路由可靠性 + 三件套 + 提醒 + 周分析 + Channel + DM Pairing**（`19f0bb5` → `8b9acae`）
  - **P12.1** voice_ack 兜底口语化 + PHASE_1/2_PROMPT 取消强制 5 行 / 3 块结构 + 弱词分类器 `YES\|NO\|UNCLEAR` 三档 + CLARIFY 反问 + 隐藏架构元数据（emoji 头 / 分隔线 / 分支广播 / verify 全过沉默）
  - **P12.2** routing_log.py：SQLite `routes` 表（path/intent/confidence/elapsed/miss）+ `路由日志` 命令；INTENT_RESCUE / WEAK_CLASSIFIER 加 few-shot + 历史感知；cancel 自动 mark_miss
  - **P12.3** `SOUL.md` + `AGENTS.md` 三件套契约；`wechat/tools/<n>/` 改成目录 + `SKILL.md` 自描述；dispatcher 启动注入到所有 LLM 调用；`重载人设` 命令
  - **P12.4** 单次提醒：`tools/remind/` + scheduler `_remind_loop` 30s 扫；自然语言时间表达走 DeepSeek 解析 → SQLite reminders 表
  - **P12.5** 周分析 minimal 拆分：纯 pandas 模块抽到 `news/weekly_stats.py`（info_lag + daily_counts），向后兼容 re-export
  - **P12.6** `wechat/channels/Channel` 抽象基类（IlinkChannel 继承）+ 沙盒分级（phase-1 加 `--disallowedTools "Write Edit MultiEdit + mcp__*_write*"` 硬拦截）
  - **P12.7** DM Pairing：`pairings` 表 + `dm_policy=pairing` 模式；陌生人发 `/pair <6位码>` → 管理员收申请 → `批准配对 X` / `拒绝配对 X`；默认 `open` 旧行为不变
- **P2 工具填充**（commit `8410382`）：`translate`（DeepSeek 中英互译）+ `now`（datetime 时间）+ `weather`（open-meteo 免 key）+ `stock_a`（东方财富 A/港/指数）。共 6 个工具（含 echo + remind），每个一目录 + SKILL.md

待实现 / TODO：
- **Phase 13.1**（约 1h）：统一 `wechat/config.json` 顶层配置——触发条件 = 接 accounting-project 时配置散落变痛
- **Phase 11**：accounting-project 接入——等用户 API 整理完
- **Phase 13.2-4**（按需）：Subagents 架构 / Hooks 事件系统 / Workspace 结构——见 plan
- **P6 微信图片输入**：iLink CDN 解密 + DeepSeek-VL ~3 小时
- **不做**：永久共享 bot session / Web UI / TTS 输出 / 多渠道实际接入（base class 已留口）

## 踩过的坑

- **关键词命中过宽**：标题/摘要/正文同等级匹配会混入无关文章。改为三级级联（先标题不够再摘要再正文）；`/api/map/articles` 只用标题匹配
- **`ROC` 子串匹配 Morocco**：地理关键词不能用三字母缩写
- **trafilatura 默认无超时**：必须用 `use_config()` 设 `DOWNLOAD_TIMEOUT=15` + 外层 `concurrent.futures.wait(timeout=30)` 兜底
- **LLM 偶尔输出英文**：DeepSeek 处理英文文章时偶发；已在 user 模板尾部加强中文提醒
- **PowerShell 的 `curl` 是 `Invoke-WebRequest` 别名**：调试 API 必须用 `curl.exe`
- **`@nivo/sankey` 与 `react-simple-maps` peer dep 冲突**：安装必须加 `--legacy-peer-deps`
- **P1.1 重启 silent failure**：dispatcher.py 漏 `import os` → `_handle_restart` 异常被 try/except 吃掉，ack/重启都不发。教训：每次新加分支记得带上对应 import；终端日志一定要确保 `PYTHONUNBUFFERED=1` + `logging.basicConfig(force=True)` 才能看见 traceback
- **Python 字符串里"双引号"嵌"双引号"**：用 `『』` 或单引号包，否则 `"...说"退出"放弃..."` 直接把字符串截断成两段，整个文件 SyntaxError
- **iLink 服务器对短时间相同内容自动去重**：连续两次发 "今日热点" 收到的 heat 列表完全一样 → 第二条被服务器返回"请稍后再试。"。不是 bot bug，发别的内容（"你好" / 不同话题分析）正常。如果将来非要让重复内容也能发出去，可以在 send_text 尾部加个隐形时间戳（不推荐——污染输出）
- **claude CLI 在 elevated bat 里找不到**：Admin 启动的 cmd 进程 PATH 可能丢失 npm 全局路径；用 `shutil.which("claude")` 会返回 None。`wechat/dispatcher.py:_find_claude_cli` 加了 `%APPDATA%\npm\claude.cmd` 等几个 fallback 路径兜底
- **Windows 下 claude.cmd 多行 prompt 走 argv 会被截断**：`subprocess.run([claude.cmd, "--print", long_multiline_prompt])` 在 Windows 上会被 cmd.exe 截成首行；Claude 实际只看到第一行，回复 "你的消息空了" / "Your message came through empty"。**修法**：prompt 走 stdin（`subprocess.run(..., input=prompt)`，argv 不带 prompt arg）
- **`--permission-mode acceptEdits` 不足以让 Claude 调 MCP read 工具**：实测在 acceptEdits 下 `mcp__github__list_commits` 仍被权限拒绝。原因：`acceptEdits` 只覆盖文件 Edit 工具，MCP 工具走另一条权限链。**修法**：检测到 `.mcp.json` 时换 `bypassPermissions`（更宽松）。安全边界靠 CLAUDE_ALLOWED_USERS 白名单 + MCP 自己的 scope（filesystem 白名单、github PAT scope）
- **`@modelcontextprotocol/server-fetch` npm 仓 404**：官方 fetch MCP 已废弃；用 Bash + curl 替代
- **DeepSeek-V3 对长 SOUL.md 注入跟随度有限**（P12.3 实测）：persona 加载机制本身没问题（loaded 日志 + 风格一致性能看出），但具体 directive（如"用陕西方言"）容易被冲淡。要强遵循度需切 Claude Sonnet/Opus 或重组 prompt 把 directive 放最末段
- **P12.7 pairing 默认关**：`WECHAT_DM_POLICY` 默认 `open` 兼容旧行为；切 `pairing` 必须同时配 `WECHAT_ADMIN_USER_ID`，否则陌生人申请没人收
- **工具目录化向后兼容**：tools/<name>/handler.py + SKILL.md（推荐）和 tools/<name>.py（旧）并存；`tools/__init__.py:_load_tools` 两种都扫，向后兼容

## 下一步

- **实测 Phase 12 + P2 工具**：重启 bot → 发 `今天几点` / `茅台股价` / `翻译 hello` / `上海天气` 验 4 个新工具；发 `路由日志` 看 SQLite；发 `提醒我 1 分钟后 X` 等响
- **Phase 13.1 统一配置**（约 1h）：触发条件是接 accounting-project；现在做也行不做也行
- **等 accounting-project API 整理完** → 开 `wechat/projects/accounting.py`（Phase 11 起点）
- 视情况切独立 API key（`BOT_ANTHROPIC_API_KEY`），订阅模式吃紧时
