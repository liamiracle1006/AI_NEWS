# encoding:utf-8
"""轻量类型定义，替代 CoW 的 bridge/context + bridge/reply。

设计原则：只保留 AI_NEWS 真正用到的字段，不重复 CoW 的事件/插件抽象。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional


class ReplyType(Enum):
    TEXT = "text"
    IMAGE = "image"    # content = bytes / BytesIO
    FILE = "file"      # content = absolute file path


@dataclass
class IncomingMessage:
    """一条收到的微信消息（已解析）。"""
    msg_id: str
    text: str
    from_user_id: str               # 必须用于回复（iLink 用 user_id 不用 nickname）
    context_token: str = ""         # iLink session token，发消息时必须 echo
    create_time: int = 0
    nickname: str = ""              # 可能为空（iLink 通常只返回 user_id）
    is_voice: bool = False          # 是否由语音转录而来（True → text 来自腾讯 ASR）


@dataclass
class OutgoingReply:
    type: ReplyType
    content: Any                    # str / bytes / BytesIO / path


@dataclass
class IlinkConfig:
    """微信守护进程配置。从 .env 读，避免硬依赖 CoW 的 conf()。"""
    enabled: bool = False
    base_url: str = ""              # 留空走默认
    cdn_base_url: str = ""
    token: str = ""                 # 留空则首次启动扫码
    credentials_path: str = "~/.ai_news_wechat.json"
    # 行为相关
    whitelist_user_ids: list[str] = field(default_factory=list)   # 空 = 任何人都可用
    daily_push_enabled: bool = False
    daily_push_cron_hour: int = 8
    daily_push_cron_minute: int = 0
    daily_push_top_n: int = 3
    daily_push_target: str = ""     # 留空时 fallback 到最近发消息的用户
    hot_alert_enabled: bool = False
    hot_alert_interval_minutes: int = 60
    hot_alert_min_count: int = 5
    hot_alert_jump_ratio: float = 3.0
    hot_alert_target: str = ""
    analyze_max_articles: int = 10
    analyze_timeout_seconds: int = 600
    # API 后端地址（同进程时就是 localhost）
    api_base: str = "http://localhost:8000/api"

    # 字典风格访问，让 scheduler.py 的 cfg.get(...) 兼容 IlinkConfig
    def get(self, key: str, default=None):
        return getattr(self, key, default)

    def __getitem__(self, key: str):
        return getattr(self, key)
