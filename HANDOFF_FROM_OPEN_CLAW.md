# 从 open_claw 实验过来的 handoff

> 写于 2026-06-11。本文是 `c:/Users/wangzy/Desktop/hobby/open_claw` 那场实验性 Claude Code 会话的 handoff，旨在把那场会话里的架构思考和决策迁移到 AI_NEWS 这边继续推进。
>
> 完整原始对话已经拷到 `C:/Users/wangzy/.claude/projects/c--Users-wangzy-Desktop-hobby-AI-NEWS/28f60c17-698f-492b-b7e8-ae3379f89c22.jsonl`，在 AI_NEWS 目录下开 Claude Code 可以 `/resume` 看完整消息历史（注意里面引用的文件路径是 open_claw/ 不是 AI_NEWS/）。

---

## 一、open_claw 是什么 / 为什么有它

那是用户"想从头再搭一个干净的迷你版"的尝试。架构：

- Telegram bot 入口
- DeepSeek 做轻量路由 (`classify_intent`) → SEARCH / CODE / MAIL / NEWS_ARCHIVE / STOP
- Tavily 搜索
- Claude Code CLI 作为编程后端（claude --print）
- SQLite 存对话历史 + 历史新闻归档
- IMAP（QQ 邮箱）拉邮件 + DeepSeek 三档分类

到目前为止做完 A（跨会话记忆）+ B1（邮箱总结）+ B2（历史新闻归档）+ Tier 0（对话不蠢）。

GitHub: https://github.com/liamiracle1006/open_claw

**和 AI_NEWS 的关系**：

| 维度 | open_claw | AI_NEWS |
|------|-----------|---------|
| 入口 | Telegram bot | 微信（iLink 协议）|
| 业务核心 | 通用助理（搜索 + 编程 + 邮件 + 新闻）| 多视角地缘政治新闻分析器（专业领域）|
| 已实现 phase | Tier 0/A/B1/B2 | Phase 0-10+（FastAPI + React 前端 + 世界地图 + 4 LLM provider + MCP）|
| 成熟度 | 早期 | 主力项目 |

**结论**：open_claw 那套架构思考大部分 AI_NEWS 已经做过或做得更好。值得迁移的是**架构哲学 + 几个具体设计点**，不是代码本身。

---

## 二、那场会话里**真正有价值**的架构洞察（按重要度）

### 1. LLM 是裁判，程序是工人（核心哲学）

参考开源 OpenClaw（真品，247K star）的真核心：

```
传统：触发 → LLM 直接调工具 → LLM 整理 → 推送
     每一步都烧 token

新版：
  采集层（cron 跑纯 Python，不调 LLM）：
    Tavily / RSS / GitHub API / IMAP 定时拉，全部落库
  工具层（纯代码）：
    去重 / 打标签 / 按白名单分类
  理解层（仅用户问 / 主动触发时用 LLM）：
    DeepSeek 从库里捞数据汇总
  行动层（LLM 决策 → 调代码做）：
    Playwright 自动填表等
```

**对 AI_NEWS 的启示**：
- 你的 RSS 抓取 + 每小时刷新已经是这思路了（采集不调 LLM）
- 但 `wechat/dispatcher.py` 的"是否触发 Claude"那段还是 LLM 兜底（弱词命中后调 DeepSeek 一句 YES/NO）。可以考虑：用统计的方法（例如最近 N 条用户是否常发该类请求）做硬规则前置，减少 LLM 调用
- 周分析五模块全靠 LLM，可以拆出"采集 + 统计描述"层（pandas 算趋势/桑基/弧线数据），LLM 只做最后的叙事化包装

### 2. 路由的两阶段架构 vs 单阶段（成本/可控性 vs 自然性的真实 tradeoff）

| 维度 | 两阶段（open_claw + AI_NEWS 都是）| 单阶段（真 OpenClaw）|
|------|--------------------------------|-------------------|
| 入站消息处理 | 关键词硬规则 → LLM 兜底 → 进子系统 | 全部喂给主 LLM 一手通办 |
| 单条消息成本 | 低（路由用 DeepSeek 或纯关键词）| 高（每条都用旗舰模型）|
| 对话自然度 | 需要补"过场话生成" + "FOLLOWUP 接续指代"两个洞 | 内置 |
| 调试可观测性 | 强（每步可独立日志）| 弱（黑盒一次性出结果）|

**AI_NEWS 的 dispatcher.py 已经是两阶段范式**（STRONG_CLAUDE_TRIGGERS 硬规则 + 弱词兜底）。
**值得补的洞**：

- a. **过场话不再用模板**：现在 dispatcher 触发 Claude 时回复是固定模板（"已进入 Claude 待执行模式…"）。可以加一个轻量 LLM 调用 `voice_ack(user_text, intent, branch_name)` 生成口语化回应，让 bot 感觉像人
- b. **接续指代意图（FOLLOWUP）**：当 phase-1 提案给出后，用户回"那个不对"/"再细一点" → 现在 dispatcher 会把它当作新请求重启 phase-1。可以加 FOLLOWUP 检测，把"上一次提案 + 用户反馈"一起喂给 Claude 继续修改，而不是从头来
- c. **模糊就反问（CLARIFY）**：用户说"处理一下" / "搞快点" 这种没明确指代的消息，dispatcher 现在可能瞎触发 Claude。可以让 LLM 路由器加置信度判断，< 60 就直接生成反问回复，不进 Claude

### 3. 跨会话长期记忆的两种模型

| 模型 | 实现 | 用途 |
|------|------|------|
| 对话流水（短期）| SQLite 表存最近 N 条 user/bot 消息 | 让接续问能识别指代 |
| 用户事实（长期，可手编辑）| Markdown 文件（如 `data/user_facts.md`），bot 自动追加，用户可手改 | 让 bot 跨周/跨月记得"用户偏好 / 项目状态 / 关键事件"|

**AI_NEWS 现状**：
- 有 `wechat/claude_sessions.py` 做命名分支持久化（任务粒度）
- 有 `wechat/task_log.md` 跨 session 传话本（事件粒度）
- **缺**：用户级别的长期事实记忆。如果你想让 bot 记得"用户最近 3 周关心以色列议题"、"用户偏好桑基图"、"用户每周二会问周分析"，需要新加一个 `data/user_facts.md` 之类的可手编 markdown

### 4. 多渠道抽象（OpenClaw 哲学，但 AI_NEWS 暂时不需要）

真 OpenClaw 支持 20+ 聊天渠道。AI_NEWS 目前只有微信，但**架构上可以预留 channel 抽象**：

```
agent/channels/
  base.py            Channel 接口（send_text / on_text / start）
  wechat_channel.py  iLink 协议
  telegram_channel.py（如果哪天接 Telegram）
```

不急做。但 `dispatcher.py` 现在 iLink 协议细节耦合太深，未来加渠道会改大。

### 5. 浏览器自动化（Playwright）

OpenClaw 真品的"AI that actually does things"杀手锏。能搞定那些"没 API 只有网页"的场景（自动登学校系统、填表、续费、抓需要登录的网页）。

**对 AI_NEWS 的潜在价值**：
- 你有 16 个 RSS 源，但有些媒体不开 RSS 或反爬虫严格（比如某些国家的官媒/被墙的源），Playwright 能直接打开浏览器抓
- 周分析的桑基图聚光灯转移如果需要 Twitter/X 数据，那是没 RSS 的，浏览器能上

如果决定做：`pip install playwright && playwright install chromium`，新建 `tools/browser.py`，4 个 primitive（open / fill / click / scrape）。

### 6. 自扩展技能（Tier 6，比较远）

让 bot 在缺工具时自己写一个，必须人工 confirm 后才落 `tools/` 并 register。AI_NEWS 已经有 `wechat/tools/` 插件目录，再做这层只是"Claude 自动生成插件代码 + dispatcher 检测 [CONFIRM] → 用户回复 1/0 → 落盘"。

---

## 三、Tier 0 在 open_claw 已经写完的代码（可作为参考）

下面是已经实现并 push 到 `liamiracle1006/open_claw` 的代码要点，对应可能映射到 AI_NEWS 的位置。

### voice_ack — 口语化过场话生成

文件：`open_claw/agent/voice.py`

```python
def voice_ack(user_text, intent, project_name=None):
    # 用 DeepSeek 一句话回应，限 25 字以内，口语化
    # 失败时返回 {"code":"好的，我去做。", "search":"搜一下。", ...} 兜底
```

**映射到 AI_NEWS**：可以在 `dispatcher.py` 触发各类回复前调用，替换 `format_help()` / `format_briefs()` 之外那些固定模板（如"已进入 Claude 待执行模式")。

### classify_intent 历史感知 + 置信度

文件：`open_claw/agent/router.py`

```python
def classify_intent(user_text, history=None) -> str:
    # 硬规则前置（项目名 / 关键词 / 活跃会话）
    # LLM 兜底输出 "INTENT|CONFIDENCE"
    # 置信度 < 60 自动降级 CLARIFY
```

**映射到 AI_NEWS**：`intent_parser.py` 已经是关键词路径，可以加一个 LLM 兜底层，用一致的 INTENT|CONFIDENCE 格式输出，让 dispatcher.py 拿到不确定信号时走 voice_clarify 反问而不是默认进 CoW chat 流。

### 数据库 schema：对话记忆 + 历史新闻归档

文件：`open_claw/agent/memory.py` + `open_claw/agent/news_archive.py`

```sql
CREATE TABLE messages (id, chat_id, role, content, ts);
CREATE TABLE news_digests (id, topic, content, ts);
```

**AI_NEWS 现状**：你已经有 `cache/articles_YYYY-MM-DD.json` 做日缓存。如果想做"用户问 'X 议题最近 3 周变化'" 这种跨日聚合查询，可能要从 JSON 迁到 SQLite。当前 7 天缓存窗（CACHE_WINDOW_HOURS=168）已经够用，不急。

---

## 四、Tier 0-6 完整路线（来自那场会话的最终方案）

| Tier | 内容 | open_claw 状态 | AI_NEWS 状态 |
|------|------|---------------|------------|
| 0 | 对话不蠢（voice_ack / FOLLOWUP / CLARIFY）| ✅ 已做 | dispatcher 有强弱词路由但缺 voice + FOLLOWUP + CLARIFY |
| 1 | 采集层 / 理解层分离（cron 不调 LLM）| 计划中 | ✅ 大部分做了（RSS 抓取 + 每小时刷新都不调 LLM；只有周分析 LLM 用得多）|
| 2 | 主动行动 + 安全 confirm（daily_brief, [CONFIRM] 按钮）| 计划中 | dispatcher 有 phase-1 → 用户确认 → phase-2 流程，已经是同思路 |
| 3 | 声明式配置 + 用户事实记忆（bot_persona.md + SKILL.md + user_facts.md）| 计划中 | wechat/tools/ 有插件框架但缺 SKILL.md 自描述；缺 user_facts |
| 4 | 多渠道抽象（WeChat + Telegram + ...）| 计划中 | iLink 单渠道，channel 抽象未拆 |
| 5 | 浏览器自动化（Playwright + 4 primitive）| 计划中 | 无 |
| 6 | 自扩展技能（bot 自写新 tool）| 计划中 | wechat/tools/ 插件框架已就位，只缺"Claude 生成 + confirm 落盘"环节 |

**AI_NEWS 当前最可能用得上的下一步**：

1. **dispatcher.py 加 voice_ack**：所有触发回复前过一次 LLM 口语化，30 行代码
2. **加 CLARIFY 反问**：弱词命中后置信度低就反问，避免 phase-1 误触发
3. **加 FOLLOWUP**：phase-1 提案后用户的"那个不对/再细点"识别，不重启 phase-1
4. **可选**：Playwright + 1 个浏览器抓 demo（针对 RSS 拿不到的源）

---

## 五、原始 Claude Code session 怎么用

在 AI_NEWS 目录下打开 Claude Code，运行 `/resume`，应该能看到这个 session（id 后六位 `5a8aa2`）。点开能看到完整 12000 行对话历史，包括：

- OpenClaw 真品架构调查的 WebFetch 结果（DigitalOcean / TechCrunch / GitHub 等 7-8 个来源）
- Tier 0-6 完整 plan（多版本迭代）
- Tier 0 全部代码改动 diff
- 用户对每个架构选择的反馈

**注意**：session 里所有引用的文件路径是 `open_claw/...`，在 AI_NEWS 里这些路径不存在。读对话时把它当"在另一个项目里发生过的事"看，思考"哪些思路映射到我的项目"。

---

## 六、open_claw 本身怎么处理

那个 repo 还在 GitHub 上（`liamiracle1006/open_claw`），代码完整可跑。要不要继续是另一回事：

- 选项 A：**冻结，作为参考**（推荐）。它的代码量小、思路清晰，可以作为"从零搭建 personal AI agent 的简化版示例"留着
- 选项 B：删 repo
- 选项 C：把 open_claw 的某些模块（如 `agent/voice.py`）抽出来当独立 PyPI 包供 AI_NEWS 引用

短期最现实是 A。
