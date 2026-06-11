# encoding:utf-8
"""微信消息分发器 — AI_NEWS 同进程版。

CoW 时代要走 HTTP 调 localhost:8000；现在直接 import pipeline 函数，
省一跳，也避免微信 daemon 启动早于 FastAPI 时的连接失败。
"""
from __future__ import annotations

import io
import logging
import os
import re
import shutil
import subprocess
import threading
import time
import urllib.parse
import uuid
from collections import defaultdict, deque
from pathlib import Path
from typing import Optional

import requests

from . import claude_sessions, routing_log, tools as wechat_tools, verify_phase2
from .voice import voice_ack
from .formatter import (
    format_analysis,
    format_articles,
    format_briefs,
    format_heat,
    format_help,
    render_analysis_card,
)
from .ilink_channel import IlinkChannel
from .intent_parser import COUNTRY_ALIASES, Intent, parse_intent
from .renderer import is_available as renderer_available, render_brief_png, render_brief_pdf, write_pdf_to_temp
from .types import IlinkConfig, IncomingMessage, OutgoingReply, ReplyType

logger = logging.getLogger(__name__)


# ── P1.2 · Claude Code 元入口相关常量 ─────────────────────────────────────────
# 项目根（dispatcher.py 在 wechat/，所以 parent.parent 是 AI_NEWS/）
_PROJECT_ROOT = Path(__file__).resolve().parent.parent

# 强词：substring 命中即进 phase-1，不再过 LLM
STRONG_CLAUDE_TRIGGERS = (
    "@claude", "@Claude",
    "让 claude", "让claude", "让 Claude", "让Claude",
    "新增加功能", "新增功能", "加个功能", "添加功能", "添加新功能",
    "给 bot 加", "给bot加", "帮 bot 加", "帮bot加",
)

# 弱词：substring 命中后调 DeepSeek 一句 YES/NO 才进 phase-1
WEAK_CLAUDE_TRIGGERS = (
    "帮我加", "帮我做", "帮我写", "帮我修", "帮我看",
    "实现一下", "实现这个", "做个", "做一个",
)

# pending 状态下用户回这些 = 退出 Claude 模式
CLAUDE_CANCEL_WORDS = {
    "退出", "取消", "不要了", "算了", "停",
    "exit", "cancel", "quit",
    "/exit", "/quit", "/cancel",
    "退出claude", "退出 claude", "取消claude", "取消 claude",
}

# pending 状态下用户回这些 = 确认执行（进 phase-2）
CLAUDE_CONFIRM_WORDS = {
    "执行", "好", "好的", "ok", "go", "干", "继续", "yes", "y", "1",
    "确认", "确定", "改吧", "动手", "开干",
}

# P1.5 · 命名分支管理：触发文本里"起名 X / 命名为 X / 叫 X"
# 名字只允许 [A-Za-z0-9_-]，最长 32（避免奇怪字符进文件名）
_BRANCH_NAME_RE = r"([A-Za-z][\w\-]{0,31})"
NAMING_HINT_RE = re.compile(rf"(?:起名为?|命名为?|叫做|叫)\s*[:：]?\s*{_BRANCH_NAME_RE}")

# 管理命令："继续 X" / "恢复 X" / "resume X"（不强制空格；分支名可以含空格——会在用户分支表里 normalize 查找）
RESUME_VERB_RE = re.compile(
    r"^(?:继续|恢复|resume)\s*(.*)$",
    re.IGNORECASE | re.DOTALL,
)
# 管理命令："删除 X" / "删 X" / "删除 X 分支"
DELETE_VERB_RE = re.compile(
    r"^(?:删除|删)\s*(.+?)\s*(?:分支)?\s*$",
    re.IGNORECASE,
)


def _resolve_branch_by_prefix(user_id: str, rest: str) -> tuple[Optional[str], str]:
    """从用户的命名分支表里找一个名字能匹配 `rest` 起始部分的（空格 + 大小写不敏感）。

    例：用户分支 'testbranch'；输入 'test branch 再加一行'
        → 归一化后 'testbranch再加一行' 起始包含 'testbranch'
        → 返回 ('testbranch', '再加一行')

    没匹配返回 (None, rest)。
    """
    if not rest:
        return None, ""
    branches = claude_sessions.list_for_user(user_id)
    if not branches:
        return None, rest
    # 长名优先（避免 'stock' 抢走 'stock_monitor' 的匹配）
    names_by_len = sorted([b["name"] for b in branches], key=len, reverse=True)
    rest_norm = re.sub(r"\s+", "", rest.lower())
    for bname in names_by_len:
        bname_norm = re.sub(r"\s+", "", bname.lower())
        if not bname_norm or not rest_norm.startswith(bname_norm):
            continue
        # 在原始 rest 中走指针定位"分支名末尾"的位置（跳过空白）
        i = j = 0
        while i < len(rest) and j < len(bname_norm):
            c = rest[i]
            if c.isspace():
                i += 1
                continue
            if c.lower() == bname_norm[j]:
                i += 1
                j += 1
            else:
                break
        if j == len(bname_norm):
            follow_up = rest[i:].lstrip(":：").strip()
            return bname, follow_up
    return None, rest
# 管理命令：列分支（normalize：去空白 + 小写后比对，避免半角/全角空格、大小写差异）
_LIST_BRANCHES_NORMALIZED = {
    "列出claude分支", "列出bot分支", "列出分支",
    "claude分支", "bot分支", "分支列表",
    "listbranches", "list", "branches",
}


def _is_list_branches_command(text: str) -> bool:
    if not text:
        return False
    normalized = re.sub(r"\s+", "", text.lower())
    return normalized in _LIST_BRANCHES_NORMALIZED

PHASE_1_PROMPT = """<user_request>
{current_request}
</user_request>

<recent_user_messages>
{recent_msgs}
</recent_user_messages>

上面 <user_request> 是用户的字面请求。逐字处理：markdown 符号 (`##` `*`) 是字面字符不是标题；冒号后的内容是请求的延续不是截断。

你的任务：分析这件事能不能做、怎么做。**只分析，绝对不动文件**。

cwd 是 AI_NEWS 项目根，CLAUDE.md 已自动加载。wechat/task_log.md 是历史流水（按需读取）。

**输出要求**：
- 像朋友讲话，**口语化**。不要"用户配合"/"风险评估"这种汇报模板词
- **100-200 字**，**不要硬编号** 1./2./3./4./5.（之前那种工程师文档腔的"1. 需求理解: 2. 实现步骤..."统统**不要**）
- 该说清楚改哪个文件就说，该提风险就提，可以用要点 (一句话一行) 但不要硬凑
- 末尾**别加** "回复 '执行' / '退出'" 之类的提示——dispatcher 自动收尾
- 别用 emoji，别加分隔线 (`———` `===`)

举例 (要这样讲)：
> 加个 stock 工具是吧。我会在 wechat/tools/ 仿照 echo 加个 stock 目录，handler.py 里调东方财富的 push2 接口，触发词"股价/股票"。先支持 A 股（茅台、宁德这种），大概 60 行。风险低，不动现有代码。这么搞？

不要这样（**反例**，工程师文档腔）：
> 1. 需求理解：在 wechat/tools/ 加 stock 工具
> 2. 实现步骤：handler.py，调 push2 接口
> 3. 用户配合：无
> 4. 风险评估：低 —— 不动现有代码
> 5. 结论：✅ 建议执行"""

PHASE_2_PROMPT = """现在按下面的方案**动手改代码**。

<plan>
{proposal}
</plan>

<original_request>
{original_request}
</original_request>

<user_confirmation>
{confirmation_text}
</user_confirmation>

`original_request` / `user_confirmation` 是用户原话，纯文本处理（markdown 符号别解读）。

**执行要求**：
- 直接按方案改文件
- 默认**不** commit（除非用户在补充里明示）
- 完成后把本次任务追加到 wechat/task_log.md（追加而非覆盖），简短一段就行：

  ## YYYY-MM-DD HH:MM · 用户：{user_id}
  **请求**：[一句话]
  **改动**：[文件清单]

**输出要求**：
- **一两句话**告诉用户改了啥 + 用户下一步做啥 (如"试试发『茅台股价』")
- **口语化**，不要列三块结构 (【改动文件】【测试指南】【系统级动作】这种统统**不要**)
- 不要 emoji，不要分隔线，不要"建议执行"这种说辞

举例 (要这样讲)：
> 改完了。加了 wechat/tools/stock 目录，handler.py 调东方财富 push2 拿 A 股价。发『茅台股价』试一下，应该回价格 + 涨跌。

不要这样（**反例**）：
> 【📂 改动文件】
> - wechat/tools/stock/handler.py — 新建 ...
> 【🧪 测试指南】
> 主流程：1. ... 2. ... 3. ...
> 【⚙️ 系统级动作】
> 无"""

WEAK_CLASSIFIER_SYSTEM = """\
判断用户的一句话是不是在让我**改 AI_NEWS 代码 / 加新功能 / 改 bot 行为**。

输出格式（严格）：`<决定>|<置信度 0-100>`
- 决定 ∈ {YES, NO, UNCLEAR}
- 置信度 = 你对这个决定有多确信
- UNCLEAR 用在"模糊指代/没说清做什么"的情况；这种应该让 bot 反问而不是硬猜

示例：
"帮我加一个查股票工具" → YES|92
"实现一下 PPT 生成功能" → YES|88
"@claude 看下 dispatcher 的 bug" → YES|95
"帮我看看今天忙不忙" → NO|85
"实现一下这周的健身计划" → NO|90
"帮我看看" → UNCLEAR|40
"搞快点" → UNCLEAR|30
"做个 PPT 给我看" → UNCLEAR|55  （没说做什么 PPT）
"实现一下" → UNCLEAR|25

只输出一行 `决定|置信度`，不要任何其他文字。"""


def _find_claude_cli() -> Optional[str]:
    """定位 claude CLI 可执行文件。

    Windows 下 claude 通常装在 npm 全局目录（`%APPDATA%\\npm\\claude.cmd`）。
    用 Administrator 启动 bat 时，Admin 的 PATH 跟当前用户的 PATH 不一样，
    `shutil.which("claude")` 可能返回 None。这里加几个常见安装路径兜底。
    """
    p = shutil.which("claude")
    if p:
        return p
    candidates: list[str] = []
    appdata = os.environ.get("APPDATA")
    if appdata:
        candidates += [
            os.path.join(appdata, "npm", "claude.cmd"),
            os.path.join(appdata, "npm", "claude.exe"),
            os.path.join(appdata, "npm", "claude"),
        ]
    user_profile = os.environ.get("USERPROFILE")
    if user_profile:
        candidates += [
            os.path.join(user_profile, "AppData", "Roaming", "npm", "claude.cmd"),
            os.path.join(user_profile, ".npm-global", "claude.cmd"),
            os.path.join(user_profile, ".claude", "local", "claude.cmd"),
            os.path.join(user_profile, ".claude", "local", "claude.exe"),
            os.path.join(user_profile, ".claude", "local", "claude"),
        ]
    local_appdata = os.environ.get("LOCALAPPDATA")
    if local_appdata:
        candidates.append(os.path.join(local_appdata, "Programs", "claude", "claude.cmd"))
    for c in candidates:
        if os.path.isfile(c):
            return c
    return None

PENDING_INTENT_CLASSIFIER_SYSTEM = """\
用户正在跟我（Claude Code 元代理）对话。
我刚给了他一个改代码的方案，正在等他回应。
判断他这条消息表达的是哪种意图，三选一：

- CONFIRM：明确同意 / 让我开始改
  例："执行" / "好" / "可以" / "干吧" / "开始" / "嗯" / "ok" / "好的，开干"

- CANCEL：放弃这次任务，不要改了
  例："退出" / "算了" / "不弄了" / "停" / "别搞了" / "先不做了" / "结束吧"

- REFINE：还在讨论 / 补充意见 / 修改方案
  例："改成 X 不要 Y" / "再加一条" / "改一下" / "别用 X 用 Y" / "不对" / "再想想" /
      "把 A 改成 B" / "有问题，X 部分应该 Y" / "再细点"

注意：
- 短句"嗯"= CONFIRM；"不"= CANCEL；"那个不对"= REFINE
- 用户问"为啥" / "X 是啥意思" 这种问问题 → REFINE
- 模糊的"再看看" → REFINE (倾向继续讨论而非取消)

只回答 CONFIRM 或 CANCEL 或 REFINE 一个词，不要解释。"""


class Dispatcher:
    """无 plugin 框架，直接基于 IncomingMessage → 调用 API（同进程 HTTP）→ 回复。

    保留通过 HTTP 调本地 FastAPI 的方式（而不是直接 import pipeline 函数），
    原因：复用现有的 job 队列 / SSE / brief 持久化逻辑，避免重写。
    """

    # 闲聊兜底用的 LLM system prompt（12.2：口语化，不要客服腔）
    CHAT_FALLBACK_SYSTEM = (
        "你是用户的朋友，在微信上聊天。"
        "**口语化**，像朋友说话，不要客服腔（『请问』『为您』『建议您』这种统统**不要**）。"
        "回复**短**，30 字以内。一两句话就够。\n\n"
        "如果用户问国际新闻/国家局势/时事 → 自然提一句『发 今日热点 看热度榜，或 分析<国家> 做深度分析』\n"
        "不要回答金融投资买卖建议（拒绝时也用口语：『这个我不能给具体建议』）\n"
        "不要 emoji，不要分隔线，不要长篇大论。"
    )

    # LLM 意图救援：关键词匹配漏掉时让 DeepSeek 看一眼，返回结构化结果或闲聊
    # 12.2：加 few-shot 示例 + 历史感知 + chat reply 口语化（≤30字）
    INTENT_RESCUE_SYSTEM = """\
你是 AI_NEWS 微信助手的意图分类器。判断用户消息属于哪类，按 JSON 一行返回。
AI_NEWS 支持：深度分析国家/话题、看全球热度榜、看单国文章列表、看历史简报。

返回格式（**只**返回 JSON 一行）：
- 深度分析话题：{"action":"analyze","topic":"<话题>","week":false}
- 全球热度榜：{"action":"heat"}
- 某国文章列表：{"action":"articles","country_zh":"<中文国名>"}
- 历史简报：{"action":"brief_list"}
- 本周综合：在 analyze 上加 "week":true
- 闲聊/无关：{"action":"chat","reply":"<口语化回复，≤30字>"}

few-shot 示例：
"以色列最近怎么样" → {"action":"analyze","topic":"以色列","week":false}
"分析下加沙" → {"action":"analyze","topic":"加沙","week":false}
"伊朗本周综合" → {"action":"analyze","topic":"伊朗","week":true}
"今日热点" → {"action":"heat"}
"全球大事" → {"action":"heat"}
"中国新闻" → {"action":"articles","country_zh":"中国"}
"看下俄罗斯报道" → {"action":"articles","country_zh":"俄罗斯"}
"历史简报" → {"action":"brief_list"}
"之前那些分析在哪" → {"action":"brief_list"}
"你好" → {"action":"chat","reply":"嗨，找我啥事？"}
"今天天气怎么样" → {"action":"chat","reply":"我没法查天气哎。要不发『今日热点』看下新闻？"}
"我要买茅台" → {"action":"chat","reply":"这个我不能给具体买卖建议。"}
"在干啥" → {"action":"chat","reply":"等你召唤。要分析啥？"}

chat 的 reply **必须**：
- ≤ 30 字
- 口语化，像朋友说话
- 不要客服腔（"请问您""为您服务""建议您"全删）
- 不要 emoji
- 涉及新闻/国家话题时自然提一句『发"今日热点"或"分析X"』
"""

    # 确认类回复（"是"/"对"/...）映射成布尔
    CONFIRM_YES = {"是", "对", "好", "ok", "OK", "确认", "yes", "Y", "y", "1", "嗯", "确定"}
    CONFIRM_NO = {"不", "否", "no", "N", "n", "0", "取消", "算了", "不要"}
    PENDING_TTL_SECONDS = 120

    def __init__(self, channel: IlinkChannel, config: IlinkConfig):
        self.channel = channel
        self.config = config
        self.api_base = config.api_base
        # LLM provider 延迟初始化，避免启动时阻塞
        self._llm_provider = None
        # 待确认的意图（每个 user_id 一条）：{user_id: {"intent": Intent, "expires": ts}}
        self._pending: dict[str, dict] = {}
        # P1.2 · Claude Code 元入口的 pending 状态（每个 user_id 一条；无 TTL，必须手动退出）
        # {user_id: {"request": str, "proposal": str|None, "created_at": float,
        #            "running": "phase1"|"phase2"|False, "cancelled": bool}}
        self._claude_pending: dict[str, dict] = {}
        # 每个 user 最近 10 条文本消息，注入 Claude phase-1 prompt 做短期上下文
        self._recent_msgs: dict[str, deque] = defaultdict(lambda: deque(maxlen=10))
        # 12.2 · 启动时初始化 SQLite 路由日志 + reminders 表
        routing_log.init()
        # 12.3 · 加载三件套契约（SOUL.md + AGENTS.md）
        self._persona = {"soul": "", "agents": ""}
        self._load_persona_files()
        channel.set_dispatcher(self._dispatch)

    def _load_persona_files(self):
        """启动 / 重载人设时调。读 wechat/SOUL.md + wechat/AGENTS.md 缓存到 self._persona。"""
        wechat_dir = Path(__file__).resolve().parent
        for key, filename in [("soul", "SOUL.md"), ("agents", "AGENTS.md")]:
            path = wechat_dir / filename
            try:
                if path.exists():
                    self._persona[key] = path.read_text(encoding="utf-8")
                    logger.info(f"[wechat-dispatch] loaded {filename} ({len(self._persona[key])}B)")
                else:
                    logger.warning(f"[wechat-dispatch] {filename} not found at {path}")
                    self._persona[key] = ""
            except Exception as e:
                logger.warning(f"[wechat-dispatch] load {filename} failed: {e}")
                self._persona[key] = ""

    def _persona_prefix(self, include_skills: bool = False) -> str:
        """生成注入 LLM prompt 开头的人设 + 行为规范 + 可选 skills 列表。"""
        parts = []
        if self._persona.get("soul"):
            parts.append("<persona>\n" + self._persona["soul"] + "\n</persona>")
        if self._persona.get("agents"):
            parts.append("<behavior>\n" + self._persona["agents"] + "\n</behavior>")
        if include_skills:
            try:
                summary = wechat_tools.all_skills_summary()
                if summary:
                    parts.append("<available_tools>\n" + summary + "\n</available_tools>")
            except Exception as e:
                logger.warning(f"[wechat-dispatch] skills summary failed: {e}")
        return ("\n\n".join(parts) + "\n\n") if parts else ""

    def _get_llm(self):
        """懒加载 LLM provider（用 AI_NEWS 的 DeepSeek 配置）。"""
        if self._llm_provider is None:
            try:
                from news.config import load_config
                from news.llm import get_provider
                cfg = load_config()
                self._llm_provider = get_provider(cfg)
            except Exception as e:
                logger.warning(f"[wechat-dispatch] LLM provider init failed: {e}")
                self._llm_provider = False  # sentinel：不再尝试
        return self._llm_provider if self._llm_provider else None

    # ── 公共入口 ───────────────────────────────────────────────────────────

    def _dispatch(self, msg: IncomingMessage, channel: IlinkChannel):
        """每条收到的消息都进这里。在调用线程内执行，慢操作要起新线程。"""
        # P12.7 · DM Pairing 安全门（dm_policy=pairing 时陌生人先配对）
        if self.config.dm_policy == "pairing":
            if not self._pairing_gate(msg, channel):
                return
        # 白名单（空 = 任何人都可用；优先级低于 pairing gate）
        if self.config.whitelist_user_ids and msg.from_user_id not in self.config.whitelist_user_ids:
            # pairing 模式下白名单可以放空（pairing 自己当门）；open 模式下保留旧行为
            if self.config.dm_policy != "pairing":
                return

        text = (msg.text or "").strip()
        prefix = "🎤" if msg.is_voice else "💬"
        # 双管齐下：logger（结构化）+ print（绕开 logging 链路，绝不会丢）
        msg_log = f"[wechat-dispatch] {prefix} {msg.from_user_id}: {text[:60]}"
        logger.info(msg_log)
        print(msg_log, flush=True)

        # P1.2 · 记录最近消息（为 Claude phase-1 prompt 提供短期上下文）
        if text:
            self._recent_msgs[msg.from_user_id].append(text)

        # 12.2 · routing_log 入口短手——每个 return 之前调一次记录决策
        def _log(path: str, **kw):
            routing_log.log_route(msg.from_user_id, text, path, **kw)

        # 12.2 · 管理命令命中也算"路由日志"管理（log 在 _handle_routing_log 内部做了）
        if text in ("路由日志", "routing log", "routing_log", "看路由"):
            self._handle_routing_log(msg, channel)
            return

        # 12.3 · 重载人设（不重启加载新 SOUL/AGENTS）
        if text in ("重载人设", "reload persona", "reload_persona"):
            self._load_persona_files()
            channel.send_text(
                msg.from_user_id,
                f"重载了 SOUL ({len(self._persona['soul'])}B) + "
                f"AGENTS ({len(self._persona['agents'])}B)。"
            )
            _log("admin -> reload_persona")
            return

        # 管理类指令是全局逃生口：最高优先级，即使有 Claude pending 也立刻执行
        if text in ("测试推送", "test_push", "测试每日推送"):
            channel.send_text(msg.from_user_id, "✅ 已在后台触发每日推送，请等待…")
            from .scheduler import _do_daily_push
            threading.Thread(target=_do_daily_push, args=(self,), daemon=True).start()
            _log("admin -> daily_push", intent="daily_push")
            return
        if text in ("测试告警", "test_alert"):
            channel.send_text(msg.from_user_id, "✅ 已在后台触发热点告警检查…")
            from .scheduler import _do_hot_alert
            threading.Thread(target=_do_hot_alert, args=(self,),
                             kwargs={"verbose": True}, daemon=True).start()
            _log("admin -> hot_alert", intent="hot_alert")
            return
        if text in ("重启", "重启 bot", "重启 uvicorn", "restart", "reboot"):
            _log("admin -> restart", intent="restart")
            self._handle_restart(msg, channel)
            return
        if text in ("强制重启", "force restart", "force-restart", "强退"):
            _log("admin -> force_restart", intent="force_restart")
            self._handle_force_restart(msg, channel)
            return

        # P1.5 · 命名分支管理命令
        if _is_list_branches_command(text):
            self._handle_list_branches(msg, channel)
            _log("admin -> list_branches", intent="list_branches")
            return
        m_resume = RESUME_VERB_RE.match(text)
        if m_resume:
            rest = m_resume.group(1).strip()
            branch_name, follow_up = _resolve_branch_by_prefix(msg.from_user_id, rest)
            if branch_name:
                self._handle_resume_branch(msg, channel, branch_name, follow_up)
                _log("admin -> resume_branch", intent=f"resume:{branch_name}")
                return
        m_delete = DELETE_VERB_RE.match(text)
        if m_delete:
            rest = m_delete.group(1).strip()
            branch_name, _ignore = _resolve_branch_by_prefix(msg.from_user_id, rest)
            if branch_name:
                self._handle_delete_branch(msg, channel, branch_name)
                _log("admin -> delete_branch", intent=f"delete:{branch_name}")
                return
            self._handle_delete_branch(msg, channel, rest)
            _log("admin -> delete_branch_missing", intent=f"delete:{rest}")
            return

        # P1.2 · Claude pending（_check_claude_pending 自己内部 log）
        if self._check_claude_pending(msg, channel):
            return

        # 优先检查是否在回应一个待确认的意图
        if self._check_pending_confirmation(msg, channel):
            _log("pending_confirmation", intent="confirm_analyze_reply")
            return

        # P1.2 · Claude Code 元入口（_check_claude_trigger 自己内部 log）
        if self._check_claude_trigger(msg, channel):
            return

        intent = parse_intent(text)
        if intent is None:
            # P2 · 先看 wechat/tools/ 里有没有命令式工具能接住
            if self._try_tools(msg):
                _log("tools_match", intent="tool")
                return
            # 工具也没命中 → LLM 闲聊兜底
            _log("chat_fallback", intent="chat")
            threading.Thread(
                target=self._handle_chat_fallback,
                args=(msg,),
                daemon=True,
                name="wechat-chat",
            ).start()
            return

        _log(f"parse_intent -> {intent.action}", intent=intent.action)
        if intent.action == "help":
            channel.send_text(msg.from_user_id, format_help())
        elif intent.action == "heat":
            self._handle_heat(msg)
        elif intent.action == "brief_list":
            self._handle_briefs(msg)
        elif intent.action == "articles":
            self._handle_articles(msg, intent)
        elif intent.action == "analyze":
            self._handle_analyze(msg, intent)
        elif intent.action == "confirm_analyze":
            self._handle_confirm_analyze(msg, intent)

    # ── 自我重启（配合 start_ai_news.bat 的永循环）───────────────────────

    def _handle_restart(self, msg: IncomingMessage, channel: IlinkChannel):
        """微信发"重启"时触发：先回执 → 延迟 3 秒 → os._exit(0)。
        .bat 包装器检测到正常退出后自动重启 uvicorn。
        """
        bat_loop_env = os.getenv("AI_NEWS_BAT_LOOP")
        logger.warning(
            f"[wechat-dispatch] _handle_restart called by {msg.from_user_id}, "
            f"AI_NEWS_BAT_LOOP={bat_loop_env!r}"
        )

        # 关键安全检查：必须由 start_ai_news.bat 启动（它会设这个环境变量）
        if bat_loop_env != "1":
            ok = channel.send_text(
                msg.from_user_id,
                "⚠️ 检测到你没用 start_ai_news.bat 启动。\n\n"
                "现在直接重启会让 bot 彻底退出且不会自动起来——\n"
                "因为外层没有循环可以接管。\n\n"
                "正确做法：\n"
                "1. 按 Ctrl+C 停掉当前 uvicorn\n"
                "2. 双击 scripts/start_ai_news.bat 启动\n"
                "3. 之后再发重启才能自动循环\n\n"
                "如果你确认想直接退出 bot 不再启动，发 强制重启"
            )
            logger.warning(f"[wechat-dispatch] safety reject; send ok={ok}")
            return

        ack = (f"🎤 我听到：{msg.text}\n♻️ 收到，3 秒后重启…"
               if msg.is_voice else "♻️ 收到，3 秒后重启…")
        ok = channel.send_text(msg.from_user_id, ack)
        logger.warning(f"[wechat-dispatch] restart ack send ok={ok}")

        def _delayed_exit():
            time.sleep(3)
            logger.warning("[wechat-dispatch] self-restart triggered, exiting NOW")
            os._exit(0)

        threading.Thread(target=_delayed_exit, daemon=True, name="self-restart").start()

    def _handle_force_restart(self, msg: IncomingMessage, channel: IlinkChannel):
        """用户明确"强制重启" → 直接 exit，不再警告。"""
        channel.send_text(msg.from_user_id, "♻️ 强制退出中...")

        def _delayed_exit():
            time.sleep(2)
            os._exit(0)

        threading.Thread(target=_delayed_exit, daemon=True, name="force-exit").start()

    # ── P12.7 · DM Pairing 流程 ───────────────────────────────────────────

    def _pairing_gate(self, msg: IncomingMessage, channel: IlinkChannel) -> bool:
        """陌生人入口控制。返回 True = 让消息通过；False = 拦截（已处理或拒绝）。

        允许通过的条件：
        - 已 paired（status='approved'）
        - 在 claude_allowed_users 里（管理员）
        - 是 admin_user_id（管理员本人）
        - 正在 admin 批准 / 拒绝其他用户的请求
        """
        import random
        uid = msg.from_user_id
        text = (msg.text or "").strip()

        # 管理员（admin_user_id 或 claude_allowed_users 任一）直接通过
        is_admin = (
            uid == self.config.admin_user_id
            or (self.config.claude_allowed_users and uid in self.config.claude_allowed_users)
        )

        if is_admin:
            # 管理员命令：批准 / 拒绝 / 列出申请
            if text in ("列出配对申请", "查配对申请", "配对申请"):
                pending = routing_log.list_pending_pairings()
                if not pending:
                    channel.send_text(uid, "现在没人在等配对。")
                    return False
                lines = [f"等批准的 {len(pending)} 个："]
                for p in pending:
                    lines.append(f"  {p['user_id']} 码={p['pair_code']}")
                lines.append("\n回『批准配对 <user_id>』或『拒绝配对 <user_id>』")
                channel.send_text(uid, "\n".join(lines))
                return False
            m_approve = re.match(r"^批准配对\s+(\S+)$", text)
            if m_approve:
                target = m_approve.group(1)
                if routing_log.approve_pairing(target):
                    channel.send_text(uid, f"已批准 {target}。")
                    try:
                        channel.send_text(target,
                            voice_ack("管理员批准你了，可以聊了", "done",
                                      provider=self._get_llm()))
                    except Exception:
                        pass
                else:
                    channel.send_text(uid, f"找不到 {target} 的待批申请。")
                return False
            m_reject = re.match(r"^拒绝配对\s+(\S+)$", text)
            if m_reject:
                target = m_reject.group(1)
                routing_log.upsert_pairing(target, "", "rejected")
                channel.send_text(uid, f"已拒绝 {target}。")
                return False
            return True  # 管理员其他消息正常路由

        # 非管理员路径
        if routing_log.is_paired(uid):
            return True  # 已批准

        existing = routing_log.get_pairing(uid)

        # 用户发 /pair <code> 确认配对码
        m_pair = re.match(r"^/?pair\s+(\d{6})$", text, re.IGNORECASE)
        if m_pair:
            code = m_pair.group(1)
            if existing and existing["pair_code"] == code and existing["status"] == "awaiting_code":
                routing_log.upsert_pairing(uid, code, "awaiting_admin")
                channel.send_text(uid, "码对了，等管理员批准。")
                # 通知管理员
                admin = self.config.admin_user_id or (
                    self.config.claude_allowed_users[0] if self.config.claude_allowed_users else None
                )
                if admin:
                    try:
                        channel.send_text(admin,
                            f"有人申请用 bot：{uid}（码 {code}）\n"
                            f"回『批准配对 {uid}』批准 / 『拒绝配对 {uid}』拒绝")
                    except Exception:
                        pass
            else:
                channel.send_text(uid, "码不对，重新发我码。")
            return False

        # 首次见此用户 → 生成码
        if existing is None or existing["status"] not in ("awaiting_code", "rejected"):
            code = f"{random.randint(100000, 999999)}"
            routing_log.upsert_pairing(uid, code, "awaiting_code")
            channel.send_text(uid,
                f"想用我的话，发 /pair {code} 给我验一下。")
            return False
        if existing["status"] == "rejected":
            channel.send_text(uid, "管理员拒了你的申请，找他聊吧。")
            return False
        if existing["status"] == "awaiting_code":
            # 还没发码 → 重新提示
            channel.send_text(uid,
                f"发 /pair {existing['pair_code']} 给我验一下。")
            return False
        # awaiting_admin → 等批准
        channel.send_text(uid, "等管理员批呢，再等等。")
        return False

    # ── 12.2 · 路由日志管理命令 ──────────────────────────────────────────────

    def _handle_routing_log(self, msg: IncomingMessage, channel: IlinkChannel):
        """显示该用户最近 15 条路由决策 + miss 率。"""
        # 12.2 · 把"路由日志"这条查询自己也先记一笔，再读
        # （否则第一次查永远是空——查的瞬间还没记）
        routing_log.log_route(
            msg.from_user_id, msg.text or "路由日志",
            "admin -> routing_log", intent="routing_log",
        )
        records = routing_log.recent_routes(msg.from_user_id, limit=15)
        if not records:
            channel.send_text(msg.from_user_id, "还没有路由记录哎。")
            return
        rate = routing_log.miss_rate(msg.from_user_id, recent_n=100)
        lines = [f"最近 {len(records)} 条路由（miss 率 {rate*100:.0f}%）："]
        for r in records:
            t = time.strftime("%H:%M:%S", time.localtime(r["ts"]))
            miss_mark = "❌ " if r["routing_miss"] else "  "
            conf = f" ({r['confidence']})" if r["confidence"] is not None else ""
            lines.append(
                f"{miss_mark}{t} {r['msg_text'][:18]:18s} → {r['decision_path']}{conf}"
            )
        channel.send_text(msg.from_user_id, "\n".join(lines))

    # ── P1.5 · Claude 命名工作分支管理 ────────────────────────────────────────

    def _handle_list_branches(self, msg: IncomingMessage, channel: IlinkChannel):
        """列出该用户所有命名 Claude 分支。"""
        branches = claude_sessions.list_for_user(msg.from_user_id)
        if not branches:
            channel.send_text(
                msg.from_user_id,
                "📂 你还没有命名的 Claude 分支。\n\n"
                "触发任务时加『起名 X』可创建：\n"
                "  新增加功能 Gmail 集成，起名 gmail"
            )
            return
        lines = [f"📂 你的 Claude 分支（{len(branches)} 个）："]
        for i, b in enumerate(branches, 1):
            when = (time.strftime("%Y-%m-%d", time.localtime(b["last_used"]))
                    if b["last_used"] else "—")
            desc = b["description"] or "(无描述)"
            lines.append(f"\n{i}. {b['name']}")
            lines.append(f"   最后活动: {when} · 任务数: {b['task_count']}")
            lines.append(f"   首次描述: {desc[:50]}")
        lines.append("\n———\n发 '继续 X' 接续 / '删除 X 分支' 删除")
        channel.send_text(msg.from_user_id, "\n".join(lines))

    def _handle_delete_branch(self, msg: IncomingMessage, channel: IlinkChannel, name: str):
        """删除一个命名 Claude 分支。"""
        if claude_sessions.delete_branch(msg.from_user_id, name):
            channel.send_text(msg.from_user_id, f"✅ 已删除分支 '{name}'。")
        else:
            channel.send_text(
                msg.from_user_id,
                f"❌ 没找到分支 '{name}'。发『列出 Claude 分支』看看现有的。"
            )

    def _handle_resume_branch(self, msg: IncomingMessage, channel: IlinkChannel,
                              name: str, follow_up: str):
        """从命名 Claude 分支接续。follow_up 是用户在"继续 X"后面跟的话。"""
        # 白名单（fail-closed）
        allowed = self.config.claude_allowed_users
        if not allowed or msg.from_user_id not in allowed:
            channel.send_text(msg.from_user_id, "🛑 Claude Code 仅授权账号可用。")
            return
        branch = claude_sessions.get_branch(msg.from_user_id, name)
        if not branch:
            channel.send_text(
                msg.from_user_id,
                f"❌ 没找到分支 '{name}'。发『列出 Claude 分支』看看现有的。"
            )
            return

        sid = branch["session_id"]
        # follow_up 为空时，让 Claude 看历史决定下一步
        request = follow_up or "(用户没说做什么；请你回顾这个 session 之前的进度，简短问下一步)"

        self._claude_pending[msg.from_user_id] = {
            "request": request,
            "proposal": None,
            "created_at": time.time(),
            "running": "phase1",
            "cancelled": False,
            "session_id": sid,
            "session_name": name,
            "is_first_call": False,  # resume → 后续都走 --resume
        }
        channel.send_text(
            msg.from_user_id,
            voice_ack(f"从 {name} 分支接续", "branch_resume",
                      user_msg=follow_up or "", provider=self._get_llm()),
        )
        threading.Thread(
            target=self._run_claude_phase1,
            args=(msg, False),
            daemon=True,
            name=f"claude-resume-{name}",
        ).start()

    # ── P1.2 · Claude Code 元入口（可行性先行的两阶段执行）───────────────────

    def _detect_claude_trigger(self, text: str) -> Optional[str]:
        """返回 'strong' / 'weak' / None。"""
        if not text:
            return None
        s = text.lower()
        for kw in STRONG_CLAUDE_TRIGGERS:
            if kw.lower() in s:
                return "strong"
        for kw in WEAK_CLAUDE_TRIGGERS:
            if kw.lower() in s:
                return "weak"
        return None

    def _classify_weak_trigger(self, text: str) -> tuple[str, int]:
        """弱词命中时让 DeepSeek 出 (decision, confidence)。
        decision ∈ {'YES', 'NO', 'UNCLEAR'}；置信度 0-100。
        LLM 不可用或异常 → ('NO', 0)（不冒进）。
        """
        provider = self._get_llm()
        if provider is None:
            return ("NO", 0)
        try:
            raw = provider.complete(
                WEAK_CLASSIFIER_SYSTEM,
                f'用户的话："{text}"',
                max_tokens=20,
                temperature=0.0,
            )
        except Exception as e:
            logger.warning(f"[wechat-dispatch] weak classifier failed: {e}")
            return ("NO", 0)
        result = (raw or "").strip().upper()
        # 解析 "YES|85" 这种
        decision = "NO"
        confidence = 0
        if "|" in result:
            left, _, right = result.partition("|")
            left = left.strip()
            right = right.strip()
            if left in ("YES", "NO", "UNCLEAR"):
                decision = left
            try:
                confidence = int("".join(c for c in right if c.isdigit())[:3])
            except ValueError:
                confidence = 0
        else:
            # 兜底：旧格式 YES/NO 单行
            if result.startswith("YES"):
                decision = "YES"
                confidence = 70
            elif result.startswith("UNCLEAR"):
                decision = "UNCLEAR"
                confidence = 40
            else:
                decision = "NO"
                confidence = 70
        logger.info(f"[wechat-dispatch] weak classifier: {result!r} → {decision}|{confidence}")
        return (decision, confidence)

    def _classify_pending_reply(self, text: str) -> str:
        """在 Claude pending 状态下，把用户回复分类为 confirm / cancel / refine。

        优先精确匹配；不命中再调 LLM。LLM 异常时回落到 'refine'（最安全：继续讨论方案）。
        """
        t = (text or "").strip()
        tl = t.lower()
        if t in CLAUDE_CONFIRM_WORDS or tl in CLAUDE_CONFIRM_WORDS:
            return "confirm"
        if t in CLAUDE_CANCEL_WORDS or tl in CLAUDE_CANCEL_WORDS:
            return "cancel"

        provider = self._get_llm()
        if provider is None:
            return "refine"
        try:
            raw = provider.complete(
                PENDING_INTENT_CLASSIFIER_SYSTEM,
                f'用户消息："{t}"',
                max_tokens=8,
                temperature=0.0,
            )
        except Exception as e:
            logger.warning(f"[wechat-dispatch] pending classifier failed: {e}")
            return "refine"
        result = (raw or "").strip().upper()
        if "CANCEL" in result:
            decision = "cancel"
        elif "CONFIRM" in result:
            decision = "confirm"
        else:
            decision = "refine"
        logger.info(f"[wechat-dispatch] pending classifier: {result!r} → {decision}")
        return decision

    def _check_claude_trigger(self, msg: IncomingMessage, channel: IlinkChannel) -> bool:
        """检测是否要进 Claude 元代理 phase-1。命中并启动返回 True。"""
        text = (msg.text or "").strip()
        kind = self._detect_claude_trigger(text)
        if kind is None:
            return False

        if kind == "weak":
            decision, confidence = self._classify_weak_trigger(text)
            if decision == "NO":
                routing_log.log_route(msg.from_user_id, text,
                                      "claude_trigger -> weak_NO",
                                      intent="not_claude", confidence=confidence,
                                      model_used="deepseek")
                return False  # 不是改代码 → 不拦截，让原流程接管
            # UNCLEAR 或 YES 但置信度 < 60 → CLARIFY 反问，不冒进 phase-1
            if decision == "UNCLEAR" or (decision == "YES" and confidence < 60):
                channel.send_text(
                    msg.from_user_id,
                    voice_ack(
                        f"用户说『{text}』，听不太懂他想干啥",
                        "clarify",
                        user_msg=text,
                        provider=self._get_llm(),
                    ),
                )
                routing_log.log_route(msg.from_user_id, text,
                                      "claude_trigger -> CLARIFY",
                                      intent="clarify", confidence=confidence,
                                      model_used="deepseek")
                return True

        # 白名单（fail-closed：未配置或不在名单 → 拒绝）
        allowed = self.config.claude_allowed_users
        if not allowed:
            channel.send_text(
                msg.from_user_id,
                "🛑 Claude Code 入口未启用。\n\n"
                "如需启用，请在 .env 中添加：\n"
                f"CLAUDE_ALLOWED_USERS={msg.from_user_id}\n\n"
                "然后重启 bot。"
            )
            return True
        if msg.from_user_id not in allowed:
            channel.send_text(msg.from_user_id, "🛑 Claude Code 仅授权账号可用。")
            return True

        # P1.5 · 解析 "起名 X" / "命名为 X" / "叫 X" → 创建命名持久化 session
        session_name: Optional[str] = None
        name_match = NAMING_HINT_RE.search(text)
        if name_match:
            candidate = name_match.group(1)
            ok, result = claude_sessions.create_branch(
                msg.from_user_id, candidate, description=text[:80]
            )
            if not ok:
                channel.send_text(
                    msg.from_user_id,
                    f"❌ {result}\n\n"
                    f"发『列出 Claude 分支』查看现有分支，或先『删除 {candidate} 分支』再重试。"
                )
                return True
            session_name = candidate
            session_id = result
        else:
            session_id = str(uuid.uuid4())

        # 立即在 pending 里挂上 running 状态，这样 "退出" 能在 phase-1 跑的过程中起效
        self._claude_pending[msg.from_user_id] = {
            "request": text,
            "proposal": None,
            "created_at": time.time(),
            "running": "phase1",
            "cancelled": False,
            "session_id": session_id,
            "session_name": session_name,  # 命名 session → str；匿名 → None
            "is_first_call": True,  # 决定首次用 --session-id 还是后续用 --resume
        }
        # 12.1 · voice_ack 代替工程师文档腔；命名分支信息**不**主动广播
        ack = voice_ack("看这个改代码需求，先想想方案", "ack",
                        user_msg=text, provider=self._get_llm())
        channel.send_text(msg.from_user_id, ack)
        # 12.2 · 记录"进入 phase-1"路由决策（kind=strong/weak）
        routing_log.log_route(
            msg.from_user_id, text,
            f"claude_trigger -> {kind} -> phase1",
            intent="claude_trigger",
            confidence=100 if kind == "strong" else None,
            model_used=None if kind == "strong" else "deepseek",
        )
        threading.Thread(
            target=self._run_claude_phase1,
            args=(msg, False),
            daemon=True,
            name="claude-phase1",
        ).start()
        return True

    def _check_claude_pending(self, msg: IncomingMessage, channel: IlinkChannel) -> bool:
        """有 Claude pending 时优先处理。用 LLM 分类用户回复的意图。"""
        pending = self._claude_pending.get(msg.from_user_id)
        if not pending:
            return False

        text = (msg.text or "").strip()
        running = pending.get("running")
        intent = self._classify_pending_reply(text)

        provider = self._get_llm()

        # CANCEL：在任何阶段都尊重
        if intent == "cancel":
            pending["cancelled"] = True
            self._claude_pending.pop(msg.from_user_id, None)
            channel.send_text(
                msg.from_user_id,
                voice_ack("用户说不弄了", "cancel_done", user_msg=text, provider=provider),
            )
            # 12.2 · 用户取消 = 上一次"进 phase-1"决策可能误触发了；标 miss
            last = routing_log.get_last_route_for_user(msg.from_user_id)
            if last and last.get("decision_path", "").startswith("claude_trigger"):
                routing_log.mark_miss(last["id"])
            routing_log.log_route(msg.from_user_id, text, "claude_pending -> cancel",
                                  intent="cancel")
            return True

        # 阶段进行中：除取消外其他一律提示稍等
        if running == "phase1":
            channel.send_text(msg.from_user_id,
                voice_ack("还在分析", "running", user_msg=text, provider=provider))
            routing_log.log_route(msg.from_user_id, text,
                                  "claude_pending -> running_phase1", intent="running")
            return True
        if running == "phase2":
            channel.send_text(msg.from_user_id,
                voice_ack("还在改代码", "running", user_msg=text, provider=provider))
            routing_log.log_route(msg.from_user_id, text,
                                  "claude_pending -> running_phase2", intent="running")
            return True

        # 已等待用户确认：confirm → phase-2；refine → 二次 phase-1
        if intent == "confirm":
            pending["running"] = "phase2"
            channel.send_text(msg.from_user_id,
                voice_ack("好，开始改代码", "doing", user_msg=text, provider=provider))
            snapshot = dict(pending)
            threading.Thread(
                target=self._run_claude_phase2,
                args=(msg, snapshot),
                daemon=True,
                name="claude-phase2",
            ).start()
            routing_log.log_route(msg.from_user_id, text,
                                  "claude_pending -> confirm -> phase2", intent="confirm")
            return True

        # refine：当成自然语言补充意见 → 二次 phase-1
        pending["running"] = "phase1"
        channel.send_text(msg.from_user_id,
            voice_ack("收到补充意见，再改改方案", "refine_doing",
                      user_msg=text, provider=provider))
        routing_log.log_route(msg.from_user_id, text,
                              "claude_pending -> refine -> phase1", intent="refine")
        threading.Thread(
            target=self._run_claude_phase1,
            args=(msg, True),
            daemon=True,
            name="claude-phase1-refine",
        ).start()
        return True

    def _run_claude_subprocess(self, prompt: str, timeout: int,
                               allow_edits: bool = False,
                               session_id: Optional[str] = None,
                               resume_session_id: Optional[str] = None) -> tuple[bool, str]:
        """订阅模式跑 `claude --print`。返回 (success, output_or_error)。

        allow_edits=True 时传 `--permission-mode acceptEdits`，让 Claude 真的能改文件
        （phase-2 必须，否则它只会"想改"不实际写）。phase-1 用 False，更安全。

        session_id：首次创建一个 session 时用 `--session-id <uuid>`。
        resume_session_id：接续既有 session 用 `--resume <uuid>`（refinement / phase-2 / 命名分支）。
        两者互斥；都不传则是完全独立的 ad-hoc session。
        """
        claude_path = _find_claude_cli()
        if claude_path is None:
            return False, (
                "❌ 找不到 claude CLI。\n"
                "已搜索 PATH 和 %APPDATA%\\npm、%USERPROFILE%\\.claude\\local 等常见位置。\n"
                "请确认 Claude Code 已安装，并在 cmd 里 `where claude` 能看到路径。"
            )
        env = os.environ.copy()
        env.pop("ANTHROPIC_API_KEY", None)   # 强制走订阅
        env.pop("CLAUDE_API_KEY", None)

        argv = [claude_path, "--print"]

        # P4 · MCP 启用（项目根有 .mcp.json 才挂；没有就静默跳过）
        mcp_config = _PROJECT_ROOT / ".mcp.json"
        mcp_on = mcp_config.exists()
        if mcp_on:
            argv += ["--mcp-config", str(mcp_config)]

        # 权限模式：
        # - MCP 启用 → bypassPermissions（acceptEdits 不足以让 Claude 调 MCP read 工具，
        #   测试结果：acceptEdits 下 mcp__github__list_commits 仍被拒）
        # - MCP 未启用 + 需要改文件 → acceptEdits（够用）
        # - MCP 未启用 + 不需要改文件 → 默认（最安全）
        if mcp_on:
            argv += ["--permission-mode", "bypassPermissions"]
        elif allow_edits:
            argv += ["--permission-mode", "acceptEdits"]

        # P12.6 · 沙盒分级：phase-1 是"只分析不动手"，即便 bypassPermissions
        # 模式下也用 --disallowedTools 把写操作硬拦截。phase-2 (allow_edits=True)
        # 完全放开。这是 belt-and-suspenders：prompt 说"严禁修改"是软约束，
        # disallowedTools 是 CLI 层硬约束。
        if not allow_edits:
            disallowed = " ".join([
                "Write", "Edit", "MultiEdit", "NotebookEdit",
                "mcp__filesystem__write_file",
                "mcp__filesystem__edit_file",
                "mcp__filesystem__move_file",
                "mcp__filesystem__create_directory",
                "mcp__github__create_issue",
                "mcp__github__update_issue",
                "mcp__github__create_or_update_file",
                "mcp__github__create_pull_request",
                "mcp__github__merge_pull_request",
                "mcp__github__create_branch",
                "mcp__github__push_files",
                "mcp__github__add_issue_comment",
            ])
            argv += ["--disallowedTools", disallowed]

        # session 控制（P1.5）：resume 优先于 session-id
        if resume_session_id:
            argv += ["--resume", resume_session_id]
        elif session_id:
            argv += ["--session-id", session_id]
        try:
            t0 = time.time()
            # 关键：prompt 走 stdin 而非命令行 arg。
            # Windows 上 claude.cmd 是 cmd.exe 包装；多行 prompt 走 argv 会被 cmd.exe
            # 截断成首行，导致 Claude 看到的 user_request 是空的。stdin 喂完整。
            proc = subprocess.run(
                argv,
                input=prompt,
                cwd=str(_PROJECT_ROOT),
                env=env,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
                shell=False,
            )
            elapsed = time.time() - t0
            stdout_preview = (proc.stdout or "")[:200].replace("\n", " ⏎ ")
            stderr_preview = (proc.stderr or "")[:200].replace("\n", " ⏎ ") if proc.stderr else ""
            logger.info(
                f"[wechat-dispatch] claude --print finished in {elapsed:.1f}s "
                f"(exit={proc.returncode}, stdout={len(proc.stdout or '')}B)"
            )
            logger.info(f"[wechat-dispatch] claude stdout preview: {stdout_preview!r}")
            if stderr_preview:
                logger.info(f"[wechat-dispatch] claude stderr preview: {stderr_preview!r}")
        except subprocess.TimeoutExpired:
            return False, f"⏱️ Claude Code 超时（{timeout}s），已终止"
        except FileNotFoundError:
            return False, f"❌ 解析到 claude 路径但无法执行：{claude_path}"
        except Exception as e:
            logger.exception(f"[wechat-dispatch] claude subprocess failed: {e}")
            return False, f"❌ Claude Code 启动异常：{e}"

        if proc.returncode != 0:
            err = ((proc.stderr or "") + (proc.stdout or "")).strip()[:800]
            return False, f"❌ Claude Code 出错 (exit {proc.returncode}):\n{err or '(无输出)'}"
        out = (proc.stdout or "").strip()
        if not out:
            return False, "❌ Claude Code 返回空输出"
        return True, out

    def _run_claude_phase1(self, msg: IncomingMessage, refined: bool):
        user_id = msg.from_user_id
        text = msg.text or ""

        # 构造 recent_msgs（剔除当前这条本身）
        buf = list(self._recent_msgs.get(user_id, []))
        if buf and buf[-1] == text:
            buf = buf[:-1]
        recent_lines = "\n".join(f"- {m}" for m in buf) if buf else "（无历史）"

        if refined:
            cur = self._claude_pending.get(user_id) or {}
            original_request = cur.get("request", "")
            prev_proposal = cur.get("proposal", "")
            current_block = (
                f"【原始请求】\n{original_request}\n\n"
                f"【用户对方案的修订意见】\n{text}\n\n"
                f"【上一版方案】\n{prev_proposal}"
            )
        else:
            current_block = text

        # 12.3 · 在 PHASE_1_PROMPT 前注入 SOUL + AGENTS + 现有 tools 摘要
        prompt = self._persona_prefix(include_skills=True) + PHASE_1_PROMPT.format(
            recent_msgs=recent_lines,
            current_request=current_block,
        )

        # session 控制（P1.5）：首次用 --session-id 起；refinement 用 --resume 接续
        cur_before = self._claude_pending.get(user_id, {})
        sid = cur_before.get("session_id")
        is_first = cur_before.get("is_first_call", True)
        if is_first:
            ok, output = self._run_claude_subprocess(prompt, timeout=600, session_id=sid)
        else:
            ok, output = self._run_claude_subprocess(prompt, timeout=600, resume_session_id=sid)

        # 跑完后回查 pending，看是否在过程中被取消
        cur = self._claude_pending.get(user_id)
        if cur is None or cur.get("cancelled"):
            logger.info(f"[wechat-dispatch] phase-1 result discarded (cancelled) user={user_id}")
            return

        if not ok:
            # phase-1 失败 → 直接清掉 pending，避免下次普通聊天被误判成 CONFIRM 复活
            self._claude_pending.pop(user_id, None)
            # 失败原话照发（output 里有真错误信息），但口语化收尾、不要"已自动退出 Claude 模式"工程腔
            self.channel.send_text(user_id, output)
            self.channel.send_text(
                user_id,
                voice_ack("失败了，要不再发一次触发词重试", "fail",
                          user_msg=text, provider=self._get_llm()),
            )
            return

        cur["proposal"] = output
        cur["running"] = False
        cur["is_first_call"] = False  # 后续 refinement / phase-2 都走 --resume
        if not refined:
            cur["request"] = text or cur.get("request", "")

        # 12.1 · 不加 emoji 头、不加分隔线、不加"回复 '执行' / '退出'" 提示
        # PHASE_1_PROMPT 已经要求 Claude 用口语自然语言；用户回什么由 LLM 三选一分类自动处理
        self._send_chunked(user_id, output)

    def _run_claude_phase2(self, msg: IncomingMessage, pending_snapshot: dict):
        user_id = msg.from_user_id
        original_request = pending_snapshot.get("request", "")
        proposal = pending_snapshot.get("proposal", "")
        confirmation = msg.text or "执行"
        sid = pending_snapshot.get("session_id")
        session_name = pending_snapshot.get("session_name")

        # P1.6 · 在跑 phase-2 之前 snapshot 一份"dirty 文件 + mtime"基线
        try:
            verify_baseline = verify_phase2.snapshot_files_with_mtime()
        except Exception as e:
            logger.warning(f"[wechat-dispatch] verify baseline snapshot failed: {e}")
            verify_baseline = None

        # 12.3 · 在 PHASE_2_PROMPT 前注入 SOUL + AGENTS（不需要 skills 摘要，phase-2 只动方案）
        prompt = self._persona_prefix(include_skills=False) + PHASE_2_PROMPT.format(
            user_id=user_id,
            proposal=proposal,
            original_request=original_request,
            confirmation_text=confirmation,
        )

        # phase-2 一定是 --resume（session 已在 phase-1 起好）
        ok, output = self._run_claude_subprocess(
            prompt, timeout=1800, allow_edits=True, resume_session_id=sid,
        )

        cur = self._claude_pending.get(user_id)
        if cur is None or cur.get("cancelled"):
            logger.info(f"[wechat-dispatch] phase-2 result discarded (cancelled) user={user_id}")
            return

        if not ok:
            # phase-2 失败 → 清掉 pending
            self._claude_pending.pop(user_id, None)
            self.channel.send_text(user_id, output)
            self.channel.send_text(
                user_id,
                voice_ack("失败了，可能部分代码已改，自己 git status 看一下",
                          "fail", user_msg=confirmation, provider=self._get_llm()),
            )
            return

        # 成功 → 命名 session 更新 last_used / task_count
        if session_name:
            claude_sessions.touch_branch(user_id, session_name)

        # P1.6 · 客观自动验证：对比 baseline → 跑 py_compile + import 检查
        verify_ok = True
        verify_section = ""
        if verify_baseline is not None:
            try:
                verify_ok, verify_section = verify_phase2.run_verify(verify_baseline)
            except Exception as e:
                logger.exception(f"[wechat-dispatch] verify crashed: {e}")
                # 静默：verify 自己挂了不打扰用户

        # 清掉 pending，发结果
        self._claude_pending.pop(user_id, None)
        # 12.1 · 成功路径**不**加 emoji 头、**不**广播分支元数据、verify 通过时**沉默**
        # PHASE_2_PROMPT 已经要求 Claude 用口语 1-2 句话告知用户改了啥 + 下一步
        # 只有 verify 失败时才主动展示报告（保证用户能看到问题）
        if not verify_ok and verify_section:
            self._send_chunked(user_id, output + "\n\n" + verify_section)
        else:
            self._send_chunked(user_id, output)

    def _send_chunked(self, user_id: str, text: str, chunk: int = 1500):
        """微信单条消息过长会被截断；按行拆分，每段加 [i/n] 头。"""
        if not text:
            return
        # 按行累积，超过 chunk 就切
        parts: list[str] = []
        cur = ""
        for line in text.split("\n"):
            if cur and len(cur) + 1 + len(line) > chunk:
                parts.append(cur)
                cur = line
            else:
                cur = (cur + "\n" + line) if cur else line
        if cur:
            parts.append(cur)
        total = len(parts)
        for i, part in enumerate(parts, 1):
            prefix = f"[{i}/{total}]\n" if total > 1 else ""
            self.channel.send_text(user_id, prefix + part)

    # ── 确认状态机 ──────────────────────────────────────────────────────────

    def _check_pending_confirmation(self, msg: IncomingMessage, channel: IlinkChannel) -> bool:
        """如果当前消息是对某个待确认意图的回复，处理它并返回 True。否则 False。"""
        pending = self._pending.get(msg.from_user_id)
        if not pending:
            return False
        if pending["expires"] < time.time():
            # 过期了
            del self._pending[msg.from_user_id]
            return False

        text = (msg.text or "").strip()

        # 用户取消
        if text in self.CONFIRM_NO:
            del self._pending[msg.from_user_id]
            channel.send_text(msg.from_user_id, "✅ 已取消")
            return True

        # 用户确认
        if text in self.CONFIRM_YES:
            intent = pending["intent"]
            del self._pending[msg.from_user_id]
            self._handle_analyze(msg, intent)
            return True

        # 用户从多选项里选了一个（"以色列" / "1" 等）
        if "options" in pending:
            opts = pending["options"]
            # 数字选项
            if text.isdigit():
                idx = int(text) - 1
                if 0 <= idx < len(opts):
                    zh = opts[idx]
                    intent = self._make_analyze_intent(zh, pending)
                    del self._pending[msg.from_user_id]
                    self._handle_analyze(msg, intent)
                    return True
            # 文本选项（直接说"以色列"）
            for zh in opts:
                if zh in text:
                    intent = self._make_analyze_intent(zh, pending)
                    del self._pending[msg.from_user_id]
                    self._handle_analyze(msg, intent)
                    return True

        # 没识别为确认/取消 → 视为新对话，丢弃 pending
        del self._pending[msg.from_user_id]
        return False

    def _make_analyze_intent(self, zh: str, pending: dict) -> Intent:
        return Intent(
            action="analyze",
            keyword=COUNTRY_ALIASES.get(zh, zh),
            country_zh=zh,
            week=pending.get("week", False),
            image=pending.get("image", False),
            pdf=pending.get("pdf", False),
        )

    def _handle_confirm_analyze(self, msg: IncomingMessage, intent: Intent):
        """收到歧义的分析请求 → 发确认提示，记录到 _pending。"""
        from .intent_parser import COUNTRY_ALIASES as _CA  # 避免循环

        if intent.multi_options:
            # 多个国家命中：列选项让用户选
            opts = intent.multi_options
            lines = [f"🤔 你想分析哪个？（你说了：「{intent.raw_text}」）", ""]
            for i, zh in enumerate(opts, 1):
                lines.append(f"{i}. {zh}")
            lines.append("")
            lines.append("回复数字 (1/2/..) 或国家名 / '取消'")
            self.channel.send_text(msg.from_user_id, "\n".join(lines))
            self._pending[msg.from_user_id] = {
                "intent": None,  # 取决于用户选
                "options": opts,
                "week": intent.week,
                "image": intent.image,
                "pdf": intent.pdf,
                "expires": time.time() + self.PENDING_TTL_SECONDS,
            }
            return

        if intent.keyword:
            # 长 keyword 提取出来了但不在已知国家里：建议简化
            # 同时尝试 fuzzy 匹配第一个可能的国家
            fuzzy_candidates = [zh for zh in _CA if zh in intent.keyword]
            if fuzzy_candidates:
                zh = fuzzy_candidates[0]
                self.channel.send_text(
                    msg.from_user_id,
                    f"🤔 你说的「{intent.raw_text}」我没完全理解。\n"
                    f"是想分析「{zh}」吗？\n\n"
                    f"回复 '是' 确认 / '不' 取消 / 或者直接说"
                )
                resolved = Intent(
                    action="analyze",
                    keyword=_CA[zh],
                    country_zh=zh,
                    week=intent.week,
                    image=intent.image,
                    pdf=intent.pdf,
                )
                self._pending[msg.from_user_id] = {
                    "intent": resolved,
                    "expires": time.time() + self.PENDING_TTL_SECONDS,
                }
                return

        # 完全无法识别 → 给清单
        sample = "、".join(list(_CA.keys())[:8])
        self.channel.send_text(
            msg.from_user_id,
            f"🤔 没识别出具体话题。\n\n"
            f"试试这种格式：\n"
            f"  · 分析以色列\n"
            f"  · 加沙本周分析\n"
            f"  · 分析<国家名> 图片\n\n"
            f"支持的国家：{sample}... (共 {len(_CA)} 个)"
        )

    # ── LLM 兜底：先做意图救援，没救出来再当闲聊 ──────────────────────────

    def _handle_chat_fallback(self, msg: IncomingMessage):
        """关键词匹配未命中的消息 → 让 LLM 看一眼。

        二选一：
        1. LLM 判定是 AI_NEWS 指令意图 → 转成 Intent 走原流程
        2. LLM 判定是闲聊 → 直接用它生成的回复
        """
        provider = self._get_llm()
        if provider is None:
            if msg.is_voice:
                self.channel.send_text(msg.from_user_id, f"我听到：{msg.text}（LLM 没连上）")
            return

        # 12.2 · 历史感知：把最近 3 条对话喂给 intent rescue 帮助判断指代
        buf = list(self._recent_msgs.get(msg.from_user_id, []))
        # 剔除当前这条（最后一条）
        if buf and buf[-1] == msg.text:
            buf = buf[:-1]
        recent_lines = "\n".join(f"- {m}" for m in buf[-3:]) if buf else "（无历史）"
        user_prompt_with_history = (
            f"<recent>\n{recent_lines}\n</recent>\n\n"
            f"<current>{msg.text}</current>"
        )

        try:
            # 12.3 · system prompt 前面注入 SOUL + AGENTS（不需要 skills）
            sys_prompt = self._persona_prefix(include_skills=False) + self.INTENT_RESCUE_SYSTEM
            raw = provider.complete(
                sys_prompt,
                user_prompt_with_history,
                max_tokens=300,  # 12.2 chat reply ≤ 30 字了，不需要 600
                temperature=0.6,  # 让 chat 回复多样
                json_mode=True,
            )
        except Exception as e:
            logger.exception(f"[wechat-dispatch] intent rescue failed: {e}")
            # 12.2 · 不暴露技术异常给用户；让 voice_ack 口语化
            self.channel.send_text(
                msg.from_user_id,
                voice_ack("意图识别失败", "fail",
                          user_msg=msg.text, provider=provider),
            )
            return

        # 解析 JSON
        data = self._safe_parse_json(raw)
        if not data:
            # JSON 解析失败 → 当成闲聊回复
            self._send_voice_aware(msg, raw)
            return

        action = data.get("action", "chat")
        logger.info(f"[wechat-dispatch] LLM rescue: {action} {data}")

        if action == "analyze":
            topic = (data.get("topic") or "").strip()
            week = bool(data.get("week", False))
            if topic:
                # 优先在 COUNTRY_ALIASES 里找匹配，否则当自由话题
                from .intent_parser import COUNTRY_ALIASES
                keyword = COUNTRY_ALIASES.get(topic, topic)
                intent = Intent(
                    action="analyze",
                    keyword=keyword,
                    country_zh=topic if topic in COUNTRY_ALIASES else None,
                    week=week,
                )
                # 12.2 · 语音消息确认时也口语化（之前 "🎤 我听到 / 🤖 理解为" 是机器人腔）
                if msg.is_voice:
                    week_word = "本周" if week else "今天"
                    self.channel.send_text(
                        msg.from_user_id,
                        f"你说的是『{msg.text}』吧，分析{week_word}的 {topic}。",
                    )
                # 12.2 · 记录路由：LLM 救援命中分析意图
                routing_log.log_route(msg.from_user_id, msg.text,
                                      "intent_rescue -> analyze",
                                      intent=f"analyze:{topic}", model_used="deepseek")
                self._handle_analyze(msg, intent)
                return

        elif action == "heat":
            if msg.is_voice:
                self.channel.send_text(
                    msg.from_user_id,
                    f"听到了，看下热度榜。"
                )
            routing_log.log_route(msg.from_user_id, msg.text,
                                  "intent_rescue -> heat",
                                  intent="heat", model_used="deepseek")
            self._handle_heat(msg)
            return

        elif action == "articles":
            from .intent_parser import COUNTRY_ALIASES, COUNTRY_ZH_TO_EN
            country_zh = (data.get("country_zh") or "").strip()
            if country_zh in COUNTRY_ALIASES:
                intent = Intent(
                    action="articles",
                    country=COUNTRY_ZH_TO_EN.get(country_zh, country_zh),
                    country_zh=country_zh,
                    week=bool(data.get("week", False)),
                )
                if msg.is_voice:
                    self.channel.send_text(
                        msg.from_user_id,
                        f"听到了，{country_zh}的报道。",
                    )
                routing_log.log_route(msg.from_user_id, msg.text,
                                      f"intent_rescue -> articles",
                                      intent=f"articles:{country_zh}", model_used="deepseek")
                self._handle_articles(msg, intent)
                return

        elif action == "brief_list":
            routing_log.log_route(msg.from_user_id, msg.text,
                                  "intent_rescue -> brief_list",
                                  intent="brief_list", model_used="deepseek")
            self._handle_briefs(msg)
            return

        # action == "chat" 或者上面任何分支没拿到必要字段 → 走闲聊
        reply = data.get("reply") or ""
        if not reply:
            # 没有 reply 字段，再调一次纯闲聊（极少情况）
            try:
                # 12.3 · CHAT_FALLBACK 也注入 persona
                sys_prompt = self._persona_prefix() + self.CHAT_FALLBACK_SYSTEM
                reply = provider.complete(
                    sys_prompt, msg.text,
                    max_tokens=120, temperature=0.7,
                )
            except Exception as e:
                logger.warning(f"[wechat-dispatch] chat fallback failed: {e}")
                reply = voice_ack("说话出错了", "fail",
                                  user_msg=msg.text, provider=provider)
        routing_log.log_route(msg.from_user_id, msg.text,
                              "intent_rescue -> chat",
                              intent="chat", model_used="deepseek")
        self._send_voice_aware(msg, reply)

    @staticmethod
    def _safe_parse_json(raw: str):
        import json
        s = (raw or "").strip()
        # 容错：偶尔模型加上 ```json 围栏
        if s.startswith("```"):
            s = s.strip("`")
            if s.lower().startswith("json"):
                s = s[4:].lstrip()
        try:
            return json.loads(s)
        except Exception:
            return None

    def _send_voice_aware(self, msg: IncomingMessage, reply: str):
        """12.2 · 语音消息确认 + 回复合并；去掉 🎤 / 🤖 机器人腔。"""
        if msg.is_voice:
            # 自然口语：直接说"你刚说的是 X 吧，<回复>" 简化为单段
            full = f"听到了：{msg.text}\n\n{reply}"
        else:
            full = reply
        self.channel.send_text(msg.from_user_id, full)

    # ── P2 · 命令式工具插件路由 ────────────────────────────────────────────

    def _try_tools(self, msg: IncomingMessage) -> bool:
        """命中 wechat/tools/ 里的工具就调它返回 True；否则 False 让下游兜底。

        异常隔离：工具自己挂掉不影响 bot；回一条 `❌ 工具 X 出错: ...` 给用户。
        工具返回 falsy（空串 / None）→ 视为"没接住"，让 chat fallback 处理。
        """
        tool = wechat_tools.find_tool(msg.text)
        if tool is None:
            return False
        logger.info(f"[wechat-dispatch] tool match: {tool.name} (keywords={tool.keywords})")
        # 12.4 · 让 handler 能拿到 user_id（reminders 工具需要）
        self._current_user_id = msg.from_user_id
        try:
            reply = tool.handle(msg.text, self)
        except Exception as e:
            logger.exception(f"[wechat-dispatch] tool {tool.name} crashed: {e}")
            self.channel.send_text(
                msg.from_user_id,
                voice_ack(f"工具 {tool.name} 挂了", "fail",
                          user_msg=msg.text, provider=self._get_llm()),
            )
            return True
        finally:
            self._current_user_id = None
        if not reply:
            return False
        self.channel.send_text(msg.from_user_id, str(reply))
        return True

    # ── 分支处理 ───────────────────────────────────────────────────────────

    def _handle_heat(self, msg: IncomingMessage):
        try:
            heat = self.api_get("/map/heat") or {}
            self.channel.send_text(msg.from_user_id, format_heat(heat))
        except Exception as e:
            self.channel.send_text(msg.from_user_id, f"❌ 拉取热度榜失败：{e}")

    def _handle_briefs(self, msg: IncomingMessage):
        try:
            briefs = self.api_get("/briefs") or []
            self.channel.send_text(msg.from_user_id, format_briefs(briefs))
        except Exception as e:
            self.channel.send_text(msg.from_user_id, f"❌ 拉取简报失败：{e}")

    def _handle_articles(self, msg: IncomingMessage, intent: Intent):
        try:
            params = {"country": intent.country, "week": "true" if intent.week else "false"}
            articles = self.api_get("/map/articles", params=params) or []
            self.channel.send_text(
                msg.from_user_id,
                format_articles(articles, intent.country_zh or intent.country, intent.week),
            )
        except Exception as e:
            self.channel.send_text(msg.from_user_id, f"❌ 拉取文章失败：{e}")

    def _handle_analyze(self, msg: IncomingMessage, intent: Intent):
        ack = f"🔍 正在分析「{intent.keyword.split('|')[0]}」"
        if intent.week:
            ack += "（本周综合）"
        ack += "，预计 2–5 分钟，请稍候…"
        self.channel.send_text(msg.from_user_id, ack)

        threading.Thread(
            target=self._run_analyze_and_push,
            args=(intent, msg.from_user_id),
            daemon=True,
            name="wechat-analyze",
        ).start()

    def _run_analyze_and_push(self, intent: Intent, to_user_id: str):
        try:
            result, _job_id = self.run_analyze_blocking(intent.keyword, week_mode=intent.week)
            brief_id = result.get("_brief_id")
            display_topic = intent.keyword.split("|")[0]

            if intent.pdf:
                self._send_pdf(to_user_id, brief_id, display_topic)
            elif intent.image:
                self._send_image_for_brief(to_user_id, brief_id, display_topic, result)
            else:
                text = format_analysis(result, display_topic, brief_id)
                self.channel.send_text(to_user_id, text)
        except Exception as e:
            logger.exception(f"[wechat-dispatch] analyze failed: {e}")
            self.channel.send_text(to_user_id, f"❌ 分析失败：{e}")

    def _send_image_for_brief(self, to_user_id: str, brief_id: Optional[str],
                              topic: str, result: dict):
        if brief_id and renderer_available():
            try:
                png = render_brief_png(self._brief_render_url(brief_id))
                self.channel.send_image(to_user_id, png)
                return
            except Exception as e:
                logger.warning(f"[wechat-dispatch] Playwright PNG failed: {e}")
        png = render_analysis_card(result, topic)
        self.channel.send_image(to_user_id, png)

    def _send_pdf(self, to_user_id: str, brief_id: Optional[str], topic: str):
        if not brief_id:
            self.channel.send_text(to_user_id, "❌ 未保存 brief_id，无法生成 PDF。")
            return
        if not renderer_available():
            self.channel.send_text(
                to_user_id,
                "❌ PDF 需要 Playwright。请运行：pip install playwright && playwright install chromium",
            )
            return
        try:
            pdf_bytes = render_brief_pdf(self._brief_render_url(brief_id))
            pdf_path = write_pdf_to_temp(pdf_bytes, topic)
            self.channel.send_file(to_user_id, pdf_path)
        except Exception as e:
            logger.exception(f"[wechat-dispatch] PDF render failed: {e}")
            self.channel.send_text(to_user_id, f"❌ PDF 生成失败：{e}")

    def _brief_render_url(self, brief_id: str) -> str:
        encoded = urllib.parse.quote(brief_id, safe="")
        return f"{self.api_base}/briefs/{encoded}/render"

    # ── HTTP 客户端 ────────────────────────────────────────────────────────

    def api_get(self, path: str, params: dict = None):
        r = requests.get(f"{self.api_base}{path}", params=params, timeout=30)
        r.raise_for_status()
        return r.json()

    def run_analyze_blocking(self, keyword: str, week_mode: bool = False) -> tuple[dict, str]:
        body = {
            "keyword": keyword,
            "max_articles": self.config.analyze_max_articles,
            "track_people": True,
            "auto_synonyms": True,
            "week_mode": week_mode,
        }
        r = requests.post(f"{self.api_base}/analyze", json=body, timeout=30)
        r.raise_for_status()
        job_id = r.json()["job_id"]

        deadline = time.time() + self.config.analyze_timeout_seconds
        while time.time() < deadline:
            time.sleep(5)
            poll = requests.get(f"{self.api_base}/analyze/{job_id}/result", timeout=30)
            if poll.status_code == 200:
                return poll.json(), job_id
            if poll.status_code == 500:
                raise RuntimeError(poll.text)
        raise TimeoutError(f"analyze timed out after {self.config.analyze_timeout_seconds}s")

    # ── 兼容 scheduler.py 的接口（旧 plugin 风格 + 几个属性） ───────────────

    @property
    def _user_contexts(self) -> dict:
        """scheduler 用 plugin._user_contexts 判断有没有可推送的用户。
        我们映射为 iLink known_users → 假 entry。"""
        return {uid: (self.channel, None) for uid in self.channel.known_users()}

    def send_to_user(self, nickname: str, text: str,
                     reply_type=ReplyType.TEXT, content=None) -> bool:
        """scheduler 主动推送入口。nickname 这里就是 user_id。"""
        target_uid = nickname
        # 空 target / 找不到时 fallback 到唯一已知用户
        known = self.channel.known_users()
        if not target_uid:
            if len(known) == 1:
                target_uid = known[0]
            else:
                logger.warning(f"[wechat-dispatch] no target for push (known={len(known)})")
                logger.info(f"[wechat-dispatch] (dropped) {text[:200]}")
                return False
        if target_uid not in known:
            if len(known) == 1:
                target_uid = known[0]
                logger.info(f"[wechat-dispatch] target {nickname!r} unknown, falling back to sole user")
            else:
                logger.warning(f"[wechat-dispatch] target {nickname!r} not in known users")
                return False

        if reply_type == ReplyType.TEXT:
            return self.channel.send_text(target_uid, text)
        if reply_type == ReplyType.IMAGE:
            return self.channel.send_image(target_uid, content if content is not None else text)
        if reply_type == ReplyType.FILE:
            return self.channel.send_file(target_uid, str(content if content is not None else text))
        return False
