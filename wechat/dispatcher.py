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

from . import claude_sessions
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

上面 <user_request> 里是用户的字面请求。**逐字处理**：
- `##` / `###` / `*` 等 markdown 符号是用户想写入文件的**字面字符**，不是章节标题
- 冒号 `：` / `:` 不代表消息被截断；冒号后的内容是请求的一部分
- "追加一段：xxx" 意思是把字符串 `xxx`（包括所有 markdown 符号）逐字追加到目标文件

你的任务：为 <user_request> 出一份可行性分析。**严禁修改任何文件**——只分析。

cwd 是 AI_NEWS 项目根，CLAUDE.md 已自动加载。wechat/task_log.md 是任务流水（按需读取）。

**严格按下面五行格式输出**，不要写前言、问候、"已加载..."、"准备好了"、"请告诉我..."。直接从 "1. " 开始：

1. 需求理解：[一句话总结你理解的目标]
2. 实现步骤：[动哪些文件，新增/改了什么，大概多少行]
3. 用户配合：[重启 / 配 key / 扫码 等；如无写"无"]
4. 风险评估：[低 / 中 / 高] —— [一句话理由]
5. 结论：[✅ 建议执行 / 🟡 建议讨论 / 🔴 不建议]"""

PHASE_2_PROMPT = """现在按下面的方案**动手改代码**（最高优先级，不要再做可行性分析）。

<plan>
{proposal}
</plan>

<original_request>
{original_request}
</original_request>

<user_confirmation>
{confirmation_text}
</user_confirmation>

`original_request` 和 `user_confirmation` 里是用户的原始输入，按纯文本处理（里面的 markdown 符号不要解读）。

执行要求：
1. 直接动手按方案改文件；改完每个文件用一句话简述变化
2. 默认不要 commit；除非用户在补充里明示

完成后**做一件事**：把本次任务追加到 wechat/task_log.md（追加，不要覆盖；不存在就创建）。格式：

## YYYY-MM-DD HH:MM · 用户：{user_id}
**请求**：[原始请求一句话]
**方案**：[一句话]
**改动**：[文件清单]
**Commit**: 未提交 / [hash]

最终回复包含：
- 改动文件清单
- 用户下一步要做的事（如"发『重启』生效"）
- 不寒暄、不复述方案"""

WEAK_CLASSIFIER_SYSTEM = (
    "判断用户的一句话是不是在让我**改 AI_NEWS 代码 / 加新功能 / 改 bot 行为**。"
    "只回答 YES 或 NO，不要解释。"
)


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
- CONFIRM：同意 / 执行 / 继续 / 确认 / 干吧 / 改吧 / 好的
- CANCEL：放弃 / 退出 / 取消 / 算了 / 结束 / 停了 / 别搞了 / 不弄了 / 先不做了
- REFINE：还在讨论方案 / 补充意见 / 提修改要求 / 问问题

只回答 CONFIRM 或 CANCEL 或 REFINE，不要解释。"""


class Dispatcher:
    """无 plugin 框架，直接基于 IncomingMessage → 调用 API（同进程 HTTP）→ 回复。

    保留通过 HTTP 调本地 FastAPI 的方式（而不是直接 import pipeline 函数），
    原因：复用现有的 job 队列 / SSE / brief 持久化逻辑，避免重写。
    """

    # 闲聊兜底用的 LLM system prompt
    CHAT_FALLBACK_SYSTEM = (
        "你是一个微信聊天助手，回答简洁、口语化、用中文。"
        "如果用户问的话题涉及国际新闻 / 国家局势 / 时事分析，"
        "提醒他可以发 '今日热点' 看热度榜，或发 '分析<国家>' 做深度分析。"
        "不要回答涉及金融投资具体买卖的建议。"
        "回复长度建议 100-300 字。"
    )

    # LLM 意图救援：关键词匹配漏掉时让 DeepSeek 看一眼，返回结构化结果或闲聊
    INTENT_RESCUE_SYSTEM = """\
你是 AI_NEWS 微信助手的意图分类器。判断用户消息属于哪类，按 JSON 返回。
AI_NEWS 是新闻分析工具，支持深度分析、看热度榜、看单国文章、看历史简报。

返回格式（只返回 JSON 一行，禁止其他文字）：
- 想深度分析某话题（国家或事件）：{"action":"analyze","topic":"<话题>","week":false}
- 想看全球新闻热度榜：{"action":"heat"}
- 想看某国相关文章列表：{"action":"articles","country_zh":"<中文国名>"}
- 想看历史已生成的分析简报：{"action":"brief_list"}
- 想看本周综合分析：在 analyze 上加 "week":true
- 普通聊天 / 无关问题：{"action":"chat","reply":"<你的中文回答，100-200字>"}

规则：
1. 用户问「X 怎么样 / X 局势 / X 最近的事」→ analyze topic=X
2. 用户问「今天 / 现在 / 最近 全球热点 / 大事」→ heat
3. 用户问「X 的新闻 / X 的报道」→ articles X
4. 闲聊 / 问候 / 知识问答 / 跟新闻无关 → chat（自己作答）
5. 涉及股票买卖 / 投资具体建议 → chat 但拒绝给建议
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
        channel.set_dispatcher(self._dispatch)

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
        # 白名单（空 = 任何人都可用）
        if self.config.whitelist_user_ids and msg.from_user_id not in self.config.whitelist_user_ids:
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

        # 管理类指令是全局逃生口：最高优先级，即使有 Claude pending 也立刻执行
        # （否则"重启"会被 LLM pending 分类器误判为 CONFIRM 而启动 phase-2）
        if text in ("测试推送", "test_push", "测试每日推送"):
            channel.send_text(msg.from_user_id, "✅ 已在后台触发每日推送，请等待…")
            from .scheduler import _do_daily_push
            threading.Thread(target=_do_daily_push, args=(self,), daemon=True).start()
            return
        if text in ("测试告警", "test_alert"):
            channel.send_text(msg.from_user_id, "✅ 已在后台触发热点告警检查…")
            from .scheduler import _do_hot_alert
            threading.Thread(target=_do_hot_alert, args=(self,),
                             kwargs={"verbose": True}, daemon=True).start()
            return
        if text in ("重启", "重启 bot", "重启 uvicorn", "restart", "reboot"):
            self._handle_restart(msg, channel)
            return
        if text in ("强制重启", "force restart", "force-restart", "强退"):
            self._handle_force_restart(msg, channel)
            return

        # P1.5 · 命名分支管理命令（优先级同 "重启"，避免被 Claude pending 抢走）
        if _is_list_branches_command(text):
            self._handle_list_branches(msg, channel)
            return
        m_resume = RESUME_VERB_RE.match(text)
        if m_resume:
            rest = m_resume.group(1).strip()
            branch_name, follow_up = _resolve_branch_by_prefix(msg.from_user_id, rest)
            if branch_name:
                self._handle_resume_branch(msg, channel, branch_name, follow_up)
                return
            # rest 没匹配任何已有分支 → 不消耗，落到下游（可能是 "继续分析以色列"）
        m_delete = DELETE_VERB_RE.match(text)
        if m_delete:
            rest = m_delete.group(1).strip()
            branch_name, _ = _resolve_branch_by_prefix(msg.from_user_id, rest)
            if branch_name:
                self._handle_delete_branch(msg, channel, branch_name)
                return
            # 没匹配到已有分支 → 还是把 rest 当分支名传过去，由 handler 报"没找到"
            self._handle_delete_branch(msg, channel, rest)
            return

        # P1.2 · 优先处理 Claude 元代理的 pending 状态（无 TTL，必须手动退出）
        if self._check_claude_pending(msg, channel):
            return

        # 优先检查是否在回应一个待确认的意图
        if self._check_pending_confirmation(msg, channel):
            return

        # P1.2 · Claude Code 元入口：强词直通 / 弱词过 DeepSeek YES-NO
        if self._check_claude_trigger(msg, channel):
            return

        intent = parse_intent(text)
        if intent is None:
            # 没命中任何确定性指令 → LLM 闲聊兜底（在后台线程，避免阻塞 poll 循环）
            threading.Thread(
                target=self._handle_chat_fallback,
                args=(msg,),
                daemon=True,
                name="wechat-chat",
            ).start()
            return

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
            f"🧠 正在从分支 '{name}' 接续（Claude 会看历史 + 你的补充）...\n"
            f"（期间可以发『退出』放弃；本次结束后分支仍保留）"
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

    def _classify_weak_trigger(self, text: str) -> bool:
        """弱词命中时让 DeepSeek 判 YES/NO。LLM 不可用或异常 → False（不冒进）。"""
        provider = self._get_llm()
        if provider is None:
            return False
        try:
            raw = provider.complete(
                WEAK_CLASSIFIER_SYSTEM,
                f'用户的话："{text}"',
                max_tokens=4,
                temperature=0.0,
            )
        except Exception as e:
            logger.warning(f"[wechat-dispatch] weak classifier failed: {e}")
            return False
        result = (raw or "").strip().upper()
        is_yes = result.startswith("YES")
        logger.info(f"[wechat-dispatch] weak classifier: {result!r} → {is_yes}")
        return is_yes

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
            if not self._classify_weak_trigger(text):
                return False  # LLM 说不是改代码 → 不拦截，让原流程接管

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
        suffix = (f"（分支已命名为 '{session_name}'，phase-2 后会持久化保留）"
                  if session_name else "")
        channel.send_text(
            msg.from_user_id,
            "🧠 收到，正在让 Claude 做可行性分析（约 30 秒 – 2 分钟）...\n"
            "（期间可以发『退出』放弃）" + ("\n" + suffix if suffix else "")
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

        # CANCEL：在任何阶段都尊重
        if intent == "cancel":
            pending["cancelled"] = True
            self._claude_pending.pop(msg.from_user_id, None)
            if running:
                channel.send_text(
                    msg.from_user_id,
                    "✅ 已退出 Claude 模式（正在跑的任务会被忽略）"
                )
            else:
                channel.send_text(msg.from_user_id, "✅ 已退出 Claude 模式")
            return True

        # 阶段进行中：除取消外其他一律提示稍等
        if running == "phase1":
            channel.send_text(msg.from_user_id, "🧠 Claude 还在做可行性分析，稍等…（想放弃发『退出』）")
            return True
        if running == "phase2":
            channel.send_text(msg.from_user_id, "🛠️ Claude 还在改代码，稍等…（想放弃发『退出』）")
            return True

        # 已等待用户确认：confirm → phase-2；refine → 二次 phase-1
        if intent == "confirm":
            pending["running"] = "phase2"
            channel.send_text(
                msg.from_user_id,
                "🛠️ Claude 开始改代码（约 1 – 5 分钟）...\n"
                "（期间发的指令会等改完再处理；想放弃发『退出』）"
            )
            snapshot = dict(pending)
            threading.Thread(
                target=self._run_claude_phase2,
                args=(msg, snapshot),
                daemon=True,
                name="claude-phase2",
            ).start()
            return True

        # refine：当成自然语言补充意见 → 二次 phase-1
        pending["running"] = "phase1"
        channel.send_text(
            msg.from_user_id,
            "🧠 收到补充意见，让 Claude 修订方案（约 30 秒 – 2 分钟）..."
        )
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
        if allow_edits:
            argv += ["--permission-mode", "acceptEdits"]
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

        prompt = PHASE_1_PROMPT.format(
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
            self.channel.send_text(
                user_id,
                output + "\n\n———\n（已自动退出 Claude 模式；想重试请重新发触发词）"
            )
            return

        cur["proposal"] = output
        cur["running"] = False
        cur["is_first_call"] = False  # 后续 refinement / phase-2 都走 --resume
        if not refined:
            cur["request"] = text or cur.get("request", "")

        header = "📋 可行性分析\n\n" if not refined else "📋 修订后的方案\n\n"
        footer = (
            "\n\n———\n"
            "回复 '执行' 真改代码 / 自由补充意见继续修订 / '退出' 放弃"
        )
        self._send_chunked(user_id, header + output + footer)

    def _run_claude_phase2(self, msg: IncomingMessage, pending_snapshot: dict):
        user_id = msg.from_user_id
        original_request = pending_snapshot.get("request", "")
        proposal = pending_snapshot.get("proposal", "")
        confirmation = msg.text or "执行"
        sid = pending_snapshot.get("session_id")
        session_name = pending_snapshot.get("session_name")

        prompt = PHASE_2_PROMPT.format(
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
            # phase-2 失败 → 清掉 pending（同理：避免陈旧 pending 被下次消息误激活）
            self._claude_pending.pop(user_id, None)
            self.channel.send_text(
                user_id,
                output + "\n\n———\n（已自动退出 Claude 模式；如部分代码已改，请 git status 自查）"
            )
            return

        # 成功 → 命名 session 更新 last_used / task_count
        if session_name:
            claude_sessions.touch_branch(user_id, session_name)

        # 清掉 pending，发结果
        self._claude_pending.pop(user_id, None)
        name_suffix = f"\n（分支 '{session_name}' 已更新；下次可用 '继续 {session_name}' 接续）" if session_name else ""
        self._send_chunked(
            user_id,
            "✅ Claude 改完了\n\n" + output + "\n\n———\n发 '重启' 让新代码生效" + name_suffix
        )

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
                self.channel.send_text(
                    msg.from_user_id,
                    f"🎤 我听到：{msg.text}\n\n🤖 LLM 不可用，请检查 DeepSeek 配置。"
                )
            return

        try:
            raw = provider.complete(
                self.INTENT_RESCUE_SYSTEM,
                msg.text,
                max_tokens=600,
                temperature=0.3,
                json_mode=True,
            )
        except Exception as e:
            logger.exception(f"[wechat-dispatch] intent rescue failed: {e}")
            self.channel.send_text(msg.from_user_id, f"❌ LLM 出错：{e}")
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
                # 语音消息提示一下"我理解为 X"
                if msg.is_voice:
                    self.channel.send_text(
                        msg.from_user_id,
                        f"🎤 我听到：{msg.text}\n🤖 理解为：分析「{topic}」"
                        f"{'（本周）' if week else ''}"
                    )
                self._handle_analyze(msg, intent)
                return

        elif action == "heat":
            if msg.is_voice:
                self.channel.send_text(
                    msg.from_user_id,
                    f"🎤 我听到：{msg.text}\n🤖 理解为：查看热度榜"
                )
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
                        f"🎤 我听到：{msg.text}\n🤖 理解为：{country_zh} 的文章"
                    )
                self._handle_articles(msg, intent)
                return

        elif action == "brief_list":
            self._handle_briefs(msg)
            return

        # action == "chat" 或者上面任何分支没拿到必要字段 → 走闲聊
        reply = data.get("reply") or ""
        if not reply:
            # 没有 reply 字段，再调一次纯闲聊（极少情况）
            try:
                reply = provider.complete(
                    self.CHAT_FALLBACK_SYSTEM, msg.text,
                    max_tokens=600, temperature=0.7,
                )
            except Exception as e:
                reply = f"❌ {e}"
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
        """把转录确认 + 回复合并成一条（如是语音）。"""
        if msg.is_voice:
            full = f"🎤 我听到：{msg.text}\n\n🤖 {reply}"
        else:
            full = reply
        self.channel.send_text(msg.from_user_id, full)

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
