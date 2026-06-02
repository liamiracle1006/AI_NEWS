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
├── wechat/                  Phase 9b+10 微信入口
│   ├── dispatcher.py        消息路由（管理命令 / Claude pending / tools / parse_intent / chat）
│   ├── ilink_{api,channel}.py iLink 协议层 + 长轮询
│   ├── intent_parser.py     关键词意图识别
│   ├── claude_sessions.py   P1.5 命名长期分支持久化
│   ├── verify_phase2.py     P1.6 phase-2 后客观验证（py_compile + import）
│   ├── tools/               P2 命令式工具插件（echo.py 示范 + 未来 weather/stock_a 等）
│   ├── task_log.md          Claude 任务流水（跨 session 传话本）
│   └── {formatter,renderer,scheduler}.py  输出 / 渲染 / 定时
├── .mcp.json                P4 MCP 配置（gitignored；.mcp.example.json 是模板）
├── .claudeignore            屏蔽 Claude 读敏感路径
├── sources.yaml             16 个新闻源配置
├── requirements.txt         Python 依赖
├── cache/  briefs/  logs/   运行时数据（gitignore）
├── README.md                用户向说明
└── PROGRESS.md              历史阶段日志（Phase 0-8，不要往里加新内容）
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
- **Phase 10 P1.2 / P1.3**：Claude Code 元入口 · 可行性先行两阶段 · commit `3489897`
  - `wechat/dispatcher.py`：`_claude_pending` 状态机 + trigger 检测 + subprocess 调用 + 分块输出
  - 触发分两档：强词（"@claude / 让 claude / 新增加功能" 等 15 个）直通；弱词（"帮我加 / 实现一下" 等 9 个）DeepSeek YES/NO 过滤
  - 白名单：`.env` 的 `CLAUDE_ALLOWED_USERS` 空 = fail-closed
  - subprocess: `env.pop("ANTHROPIC_API_KEY")` 强制订阅模式；prompt 走 stdin 避免 Windows argv 截断；phase-2 加 `--permission-mode acceptEdits` 才能写盘
  - 退出/确认走 LLM 三选一分类（CONFIRM / CANCEL / REFINE），"结束吧 / 别搞了 / 改成 X" 都能识别
  - 管理命令（重启 / 列分支 / 测试推送）优先级最高，不会被陈旧 pending 抢
- **Phase 10 P1.4 + P1.5**：工作流级 session + 命名长期分支 · commits `7537e9d` / `80f45d7`
  - `wechat/claude_sessions.py`：`~/.ai_news_claude_sessions.json` 持久化 `{user_id: {name: {session_id, ...}}}`，per-user 独立、无 TTL、命名冲突拒绝
  - phase-1 起 session 用 `--session-id`；refinement / phase-2 用 `--resume`（同工作流内推理接续）
  - 触发含"起名 X" → 持久化命名分支；匿名 session 完成即弃
  - 新管理命令：「继续 X [follow-up]」 / 「列出 Claude 分支」 / 「删除 X 分支」；支持模糊匹配（含空格 / 大小写归一化）
- **Phase 10 P1.6**：phase-2 客观验证 · commit `963d2d2`
  - `wechat/verify_phase2.py`：snapshot 文件 mtime → diff → `py_compile` + `python -c "import X"` 双重检查
  - 失败时头标题改 "⚠️ Claude 改完但验证有警告" + 给修复指引；try/except 兜底 verify 自己挂掉不影响 phase-2
- **Phase 10 P1.7-A**：PHASE_2_PROMPT 强制三块结构 · commit `a26d9d1` —— 改动文件 / 测试指南（具体步骤 + 预期 + 边界用例）/ 系统级动作。Claude 不许再写"自行测试"这种空话
- **Phase 10 番外**：深度分析提速 A+B+C · commit `865c2c2` —— fact-extract 指数退避 + cross-ref/track-entities 并行 + `fast_mode` 跳过正文抓取
- **`.claudeignore`** · commit `04dfbe2` —— 项目根屏蔽 `.env` / `*.key` / build 产物；home 级 `~/.claudeignore` 屏蔽 `.ssh/` / `.aws/` / `~/.ai_news_*.json` 等
- **Phase 10 P2 地基**：`wechat/tools/` 插件目录 · commit `da1fe21`
  - `__init__.py` 自动发现（pkgutil）+ 注册 + 异常隔离
  - 契约：`TOOL_NAME` / `TRIGGER_KEYWORDS` / `handle(text, ctx) -> str`
  - 路由位置：dispatcher 在 `parse_intent` 失败、`chat_fallback` 之前调 `_try_tools`
  - 现有：`echo.py` 示范；weather / stock_a / pc_launcher 留给微信侧 @claude 仿照加
- **Phase 10 P4**：MCP 侧门 · commit `fd4d415`
  - `.mcp.json`（gitignored）配 `filesystem`（白名单 AI_NEWS + accounting-project）+ `github`（用 .env 的 PAT）
  - dispatcher 检测到 `.mcp.json` → 自动加 `--mcp-config` + `--permission-mode bypassPermissions`（acceptEdits 不足以解锁 MCP read 工具，已实测）
  - 使能跨项目读 + GitHub remote 操作（issue / PR / commit 查询）

待实现 / TODO：
- **P2 工具填充**：让微信 @claude 仿照 `echo.py` 加 weather / stock_a / pc_launcher（每个 ~5 分钟，端到端实战 P1.2）
- **P3 股票监控**：等 P2 stock_a 做完，加后台轮询 + 阈值告警 → 微信推送
- **Phase 11 accounting-project 接入**：等用户那边 API 整理好（router 列表 + 触发关键词），建 `wechat/projects/accounting.py`
- **P6 微信图片输入**：iLink CDN 解密 + DeepSeek-VL，约 3 小时，详见 plan
- **不做**：永久共享 bot session（task_log.md 已经做了摘要后的长期记忆，质量更高）

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
- **`@modelcontextprotocol/server-fetch` npm 仓 404**：原以为存在的官方 fetch MCP 已经被废弃；Python 版 `mcp-server-fetch` 还在但需 `uvx`。当前方案：不装 fetch MCP，Claude 用 Bash + `curl` 干 HTTP 完全够

## 下一步

- **微信侧实战测 P2 + P4**：发"echo 你好"验工具地基；发"@claude 看下 AI_NEWS 最近 5 条 commit" 验 github MCP；发"@claude 看下 accounting-project 的 main.py 用了哪些 router" 验跨项目读
- **让 @claude 加 weather 工具**：发触发词 + "在 wechat/tools/ 仿照 echo.py 加 weather，open-meteo 免 key，起名 weather"——同时验证 P2 契约 + P1.5 命名分支
- **等 accounting-project API 整理完**：用户更新好后开 `wechat/projects/accounting.py`（Phase 11 起点）
- 视情况切独立 API key（`BOT_ANTHROPIC_API_KEY`），如果订阅模式跟自己用配额冲突
