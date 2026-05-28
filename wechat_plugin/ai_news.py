# encoding:utf-8
"""AI_NEWS 微信插件主入口。

对接已运行的 FastAPI 后端（默认 http://localhost:8000），把微信消息翻译成
API 调用并把结构化结果格式化回微信文本/图片。
"""
from __future__ import annotations

import io
import json
import os
import threading
import time
import urllib.parse
from typing import Optional

import requests

import plugins
from bridge.context import ContextType
from bridge.reply import Reply, ReplyType
from common.log import logger
from plugins import Plugin, Event, EventContext, EventAction

from .formatter import (
    format_analysis,
    format_articles,
    format_briefs,
    format_heat,
    format_help,
    render_analysis_card,
)
from .intent_parser import COUNTRY_ALIASES, Intent, parse_intent
from .renderer import is_available as renderer_available, render_brief_png, render_brief_pdf, write_pdf_to_temp
from .scheduler import start_scheduler


@plugins.register(
    name="AINews",
    desc="多视角新闻分析 — 微信版（接入本地 AI_NEWS FastAPI 后端）",
    version="0.1",
    author="Wang Ziyu",
    desire_priority=100,
)
class AINews(Plugin):

    def __init__(self):
        super().__init__()
        try:
            self.config = super().load_config() or self._load_config_template()
            self.api_base = self.config.get("api_base", "http://localhost:8000/api")
            self.whitelist = self.config.get("whitelist_nicknames", []) or []
            self.timeout = int(self.config.get("analyze_timeout_seconds", 600))

            self.handlers[Event.ON_HANDLE_CONTEXT] = self.on_handle_context

            # 启动定时任务
            try:
                start_scheduler(self)
            except Exception as e:
                logger.exception(f"[AINews] scheduler start failed: {e}")

            logger.info(f"[AINews] inited; api_base={self.api_base}, whitelist={self.whitelist}")
        except Exception as e:
            logger.error(f"[AINews] init failed: {e}")
            raise

    # ───── 主消息回调 ─────────────────────────────────────────────────────────

    def on_handle_context(self, e_context: EventContext):
        ctx = e_context["context"]
        if ctx.type != ContextType.TEXT:
            return

        msg = ctx.get("msg")
        nickname = getattr(msg, "from_user_nickname", "") or getattr(msg, "actual_user_nickname", "")

        # 白名单（空列表 = 任何人可用）
        if self.whitelist and nickname not in self.whitelist:
            return  # 不响应非白名单，让默认 LLM 流程处理

        intent = parse_intent(ctx.content)
        if intent is None:
            return  # 识别不到指令，放给默认 LLM 流程

        logger.info(f"[AINews] {nickname} → intent={intent}")

        if intent.action == "help":
            self._send_text(e_context, format_help())
        elif intent.action == "heat":
            self._handle_heat(e_context)
        elif intent.action == "brief_list":
            self._handle_briefs(e_context)
        elif intent.action == "articles":
            self._handle_articles(e_context, intent)
        elif intent.action == "analyze":
            self._handle_analyze(e_context, intent)
        else:
            return  # 未知 action，放给默认 LLM

    # ───── 各分支处理 ─────────────────────────────────────────────────────────

    def _handle_heat(self, e_context: EventContext):
        try:
            heat = self.api_get("/map/heat") or {}
            self._send_text(e_context, format_heat(heat))
        except Exception as e:
            self._send_text(e_context, f"❌ 拉取热度榜失败：{e}")

    def _handle_briefs(self, e_context: EventContext):
        try:
            briefs = self.api_get("/briefs") or []
            self._send_text(e_context, format_briefs(briefs))
        except Exception as e:
            self._send_text(e_context, f"❌ 拉取简报失败：{e}")

    def _handle_articles(self, e_context: EventContext, intent: Intent):
        try:
            params = {"country": intent.country, "week": "true" if intent.week else "false"}
            articles = self.api_get("/map/articles", params=params) or []
            self._send_text(e_context, format_articles(articles, intent.country_zh or intent.country, intent.week))
        except Exception as e:
            self._send_text(e_context, f"❌ 拉取文章失败：{e}")

    def _handle_analyze(self, e_context: EventContext, intent: Intent):
        # 立即回个"分析中"（同步 reply 走 e_context，这一条用户先收到）
        ack = f"🔍 正在分析「{intent.keyword.split('|')[0]}」"
        if intent.week:
            ack += "（本周综合）"
        ack += "，预计 2–5 分钟，请稍候…"
        self._send_text(e_context, ack)

        # 关键：原 e_context 在同步 handler 返回后就消费完了，
        # 后续异步推送必须直接调 channel.send()，不能再改 e_context。
        # 把 channel + context 捕获进闭包传给后台线程。
        channel = e_context["channel"]
        context = e_context["context"]

        threading.Thread(
            target=self._run_analyze_and_push,
            args=(intent, channel, context),
            daemon=True,
            name="AINews-analyze",
        ).start()

        # 拦截，不走默认 LLM
        e_context.action = EventAction.BREAK_PASS

    def _run_analyze_and_push(self, intent: Intent, channel, context):
        """后台线程：跑完分析后直接 channel.send()，绕开 EventContext。"""
        try:
            result, _job_id = self.run_analyze_blocking(intent.keyword, week_mode=intent.week)
            # brief_id 是文件名 stem（如 "Israel_以色列_20260528_1245"），由后端在保存时写入 result。
            # 区别于 job_id（任务内存 UUID，无法用于 /briefs/{id} 路由）。
            brief_id = result.get("_brief_id")
            display_topic = intent.keyword.split("|")[0]

            # 渲染优先级：PDF > 图片 > 文本
            if intent.pdf:
                self._send_pdf(channel, context, brief_id, display_topic)
            elif intent.image:
                self._send_image_for_brief(channel, context, brief_id, display_topic, result)
            else:
                text = format_analysis(result, display_topic, brief_id)
                channel.send(Reply(ReplyType.TEXT, text), context)
        except Exception as e:
            logger.exception(f"[AINews] analyze failed: {e}")
            try:
                channel.send(Reply(ReplyType.TEXT, f"❌ 分析失败：{e}"), context)
            except Exception:
                pass

    def _brief_render_url(self, brief_id: str) -> str:
        """构造 /briefs/<id>/render 的 URL，brief_id 含中文需 URL 编码。"""
        encoded = urllib.parse.quote(brief_id, safe="")
        return f"{self.api_base}/briefs/{encoded}/render"

    def _send_image_for_brief(self, channel, context, brief_id: str | None,
                              topic: str, result: dict):
        """发图片：优先用 Playwright 截图 HTML 报告，失败时回退到 Pillow 文字卡。"""
        if brief_id and renderer_available():
            try:
                png = render_brief_png(self._brief_render_url(brief_id))
                channel.send(Reply(ReplyType.IMAGE, io.BytesIO(png)), context)
                return
            except Exception as e:
                logger.warning(f"[AINews] Playwright PNG failed, fallback to Pillow: {e}")
        # Fallback：Pillow 简朴文字卡
        png = render_analysis_card(result, topic)
        channel.send(Reply(ReplyType.IMAGE, io.BytesIO(png)), context)

    def _send_pdf(self, channel, context, brief_id: str | None, topic: str):
        """发 PDF：必须有 Playwright，否则告知用户无法生成。"""
        if not brief_id:
            channel.send(Reply(ReplyType.TEXT, "❌ 分析未保存 brief_id，无法生成 PDF。"), context)
            return
        if not renderer_available():
            channel.send(Reply(
                ReplyType.TEXT,
                "❌ PDF 渲染需要安装 Playwright。请在 CoW 环境运行：\n"
                "  pip install playwright\n  playwright install chromium",
            ), context)
            return
        try:
            pdf_bytes = render_brief_pdf(self._brief_render_url(brief_id))
            pdf_path = write_pdf_to_temp(pdf_bytes, topic)
            channel.send(Reply(ReplyType.FILE, pdf_path), context)
        except Exception as e:
            logger.exception(f"[AINews] PDF render failed: {e}")
            channel.send(Reply(ReplyType.TEXT, f"❌ PDF 生成失败：{e}"), context)

    # ───── HTTP 客户端 ───────────────────────────────────────────────────────

    def api_get(self, path: str, params: dict | None = None):
        url = f"{self.api_base}{path}"
        r = requests.get(url, params=params, timeout=30)
        r.raise_for_status()
        return r.json()

    def run_analyze_blocking(self, keyword: str, week_mode: bool = False) -> tuple[dict, str | None]:
        """启动 analyze 任务并阻塞轮询直到出结果。返回 (result_json, brief_id)。"""
        body = {
            "keyword": keyword,
            "max_articles": int(self.config.get("analyze_max_articles", 10)),
            "track_people": True,
            "auto_synonyms": True,
            "week_mode": week_mode,
        }
        r = requests.post(f"{self.api_base}/analyze", json=body, timeout=30)
        r.raise_for_status()
        job_id = r.json()["job_id"]

        deadline = time.time() + self.timeout
        while time.time() < deadline:
            time.sleep(5)
            poll = requests.get(f"{self.api_base}/analyze/{job_id}/result", timeout=30)
            if poll.status_code == 200:
                return poll.json(), job_id
            if poll.status_code == 500:
                raise RuntimeError(poll.text)
            # 202 = still running, keep polling

        raise TimeoutError(f"analyze timed out after {self.timeout}s")

    # ───── 主动发送 ──────────────────────────────────────────────────────────

    def send_to_user(self, nickname: str, text: str):
        """供 scheduler 用的主动发送接口。

        CoW 不同 channel 主动发送 API 不统一，这里走通用 bot 路径。
        nickname 应是好友昵称或群名。
        """
        try:
            from channel import channel_factory
            from config import conf

            channel = channel_factory.create_channel(conf().get("channel_type"))
            # 简化：直接构造一个 Reply 给 channel.send
            # 实际可能需要先查 UserName，这里留作 TODO
            logger.warning(
                "[AINews] send_to_user not fully implemented — "
                "needs channel-specific UserName lookup. text=%s",
                text[:60],
            )
        except Exception as e:
            logger.exception(f"[AINews] send_to_user failed: {e}")

    # ───── 工具 ──────────────────────────────────────────────────────────────

    def _send_text(self, e_context: EventContext, text: str):
        reply = Reply(ReplyType.TEXT, text)
        e_context["reply"] = reply
        e_context.action = EventAction.BREAK_PASS

    def _send_image(self, e_context: EventContext, png_bytes: bytes):
        reply = Reply(ReplyType.IMAGE, io.BytesIO(png_bytes))
        e_context["reply"] = reply
        e_context.action = EventAction.BREAK_PASS

    def _load_config_template(self) -> dict:
        path = os.path.join(self.path, "config.json.template")
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        return {}

    def get_help_text(self, **kwargs):
        return format_help()
