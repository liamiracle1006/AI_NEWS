# encoding:utf-8
"""AI_NEWS 内嵌的微信 (iLink) 守护进程。

启用方式：在 .env 设 WECHAT_ENABLED=true，然后 uvicorn 启动 AI_NEWS 即可。
所有配置统一从 .env / 环境变量读取（见 types.IlinkConfig）。
"""
from __future__ import annotations

import logging
import os
import threading
from typing import Optional

from .dispatcher import Dispatcher
from .ilink_channel import IlinkChannel
from .scheduler import start_scheduler
from .types import IlinkConfig

logger = logging.getLogger(__name__)

_DAEMON: Optional["Daemon"] = None


def _envbool(name: str, default: bool = False) -> bool:
    val = os.getenv(name, "").strip().lower()
    if not val:
        return default
    return val in ("1", "true", "yes", "on")


def _envint(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)).strip())
    except Exception:
        return default


def _envfloat(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)).strip())
    except Exception:
        return default


def _envlist(name: str) -> list[str]:
    raw = os.getenv(name, "").strip()
    if not raw:
        return []
    return [x.strip() for x in raw.split(",") if x.strip()]


def load_config_from_env() -> IlinkConfig:
    return IlinkConfig(
        enabled=_envbool("WECHAT_ENABLED", False),
        base_url=os.getenv("WECHAT_BASE_URL", ""),
        cdn_base_url=os.getenv("WECHAT_CDN_BASE_URL", ""),
        token=os.getenv("WECHAT_TOKEN", ""),
        credentials_path=os.getenv("WECHAT_CREDENTIALS_PATH", "~/.ai_news_wechat.json"),
        whitelist_user_ids=_envlist("WECHAT_WHITELIST_USER_IDS"),
        daily_push_enabled=_envbool("WECHAT_DAILY_PUSH_ENABLED", False),
        daily_push_cron_hour=_envint("WECHAT_DAILY_PUSH_HOUR", 8),
        daily_push_cron_minute=_envint("WECHAT_DAILY_PUSH_MINUTE", 0),
        daily_push_top_n=_envint("WECHAT_DAILY_PUSH_TOP_N", 3),
        daily_push_target=os.getenv("WECHAT_DAILY_PUSH_TARGET", ""),
        hot_alert_enabled=_envbool("WECHAT_HOT_ALERT_ENABLED", False),
        hot_alert_interval_minutes=_envint("WECHAT_HOT_ALERT_INTERVAL_MIN", 60),
        hot_alert_min_count=_envint("WECHAT_HOT_ALERT_MIN_COUNT", 5),
        hot_alert_jump_ratio=_envfloat("WECHAT_HOT_ALERT_JUMP_RATIO", 3.0),
        hot_alert_target=os.getenv("WECHAT_HOT_ALERT_TARGET", ""),
        analyze_max_articles=_envint("WECHAT_ANALYZE_MAX_ARTICLES", 10),
        analyze_timeout_seconds=_envint("WECHAT_ANALYZE_TIMEOUT", 600),
        claude_allowed_users=_envlist("CLAUDE_ALLOWED_USERS"),
        dm_policy=os.getenv("WECHAT_DM_POLICY", "open"),
        admin_user_id=os.getenv("WECHAT_ADMIN_USER_ID", ""),
        api_base=os.getenv("WECHAT_API_BASE", "http://localhost:8000/api"),
    )


class Daemon:
    def __init__(self, config: IlinkConfig):
        self.config = config
        self.channel = IlinkChannel(
            credentials_path=config.credentials_path,
            base_url=config.base_url,
            cdn_base_url=config.cdn_base_url,
            token=config.token,
        )
        self.dispatcher = Dispatcher(self.channel, config)

    def start(self):
        logger.info("[wechat] starting daemon...")
        if not self.channel.start():
            logger.error("[wechat] channel start failed (QR login timeout?)")
            return False
        # 在 channel 跑起来之后再启动 scheduler（避免 scheduler 早于通道 ready）
        start_scheduler(self.dispatcher)
        logger.info("[wechat] daemon started")
        return True

    def stop(self):
        self.channel.stop()


def start_daemon_async() -> Optional[Daemon]:
    """从 .env 读配置，启动微信守护进程。在新线程里完成扫码登录。
    若 WECHAT_ENABLED!=true，不启动；返回 None。
    """
    global _DAEMON
    cfg = load_config_from_env()
    if not cfg.enabled:
        logger.info("[wechat] WECHAT_ENABLED is not set, skipping daemon startup")
        return None

    daemon = Daemon(cfg)
    _DAEMON = daemon

    def _bootstrap():
        try:
            daemon.start()
        except Exception as e:
            logger.exception(f"[wechat] daemon bootstrap failed: {e}")

    threading.Thread(target=_bootstrap, daemon=True, name="wechat-bootstrap").start()
    return daemon


def get_daemon() -> Optional[Daemon]:
    return _DAEMON
