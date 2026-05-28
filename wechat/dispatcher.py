# encoding:utf-8
"""微信消息分发器 — AI_NEWS 同进程版。

CoW 时代要走 HTTP 调 localhost:8000；现在直接 import pipeline 函数，
省一跳，也避免微信 daemon 启动早于 FastAPI 时的连接失败。
"""
from __future__ import annotations

import io
import logging
import threading
import time
import urllib.parse
import uuid
from typing import Optional

import requests

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
        logger.info(f"[wechat-dispatch] {prefix} {msg.from_user_id}: {text[:60]}")

        # 优先检查是否在回应一个待确认的意图
        if self._check_pending_confirmation(msg, channel):
            return

        # 管理类指令（不进 intent_parser）
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
        if msg.is_voice:
            channel.send_text(msg.from_user_id, f"🎤 我听到：{msg.text}\n♻️ 收到，3 秒后重启…")
        else:
            channel.send_text(msg.from_user_id, "♻️ 收到，3 秒后重启…\n(用 .bat 启动才会自动重启回来)")

        def _delayed_exit():
            time.sleep(3)
            logger.warning("[wechat-dispatch] self-restart triggered, exiting")
            # 用 os._exit(0) 而非 sys.exit()，绕开 uvicorn 的 graceful shutdown
            # 因为 uvicorn 内有些线程不会响应 SIGTERM，graceful 可能挂住几十秒。
            os._exit(0)

        threading.Thread(target=_delayed_exit, daemon=True, name="self-restart").start()

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
