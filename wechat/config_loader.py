# encoding:utf-8
"""统一配置加载层（13.1）——OpenClaw 的 `openclaw.json` 风格。

设计：
- `wechat/config.json`（gitignored，本地）= 最高优先级；存在就用它
- `wechat/config.example.json`（提交进 git）= 模板 + 内置默认值，注释里写明字段语义
- `.env` env vars 永远胜过 JSON（保密字段如 API key 只能走 env）

注意这层不替代 `.env`：那是放敏感凭证和"机器本地"配置（路径、端口）；
这里放"行为可调"配置（触发词、超时、人设路径等）。

外部用法：
    cfg = load_unified_config()
    triggers = cfg.get("claude", {}).get("strong_triggers", [...])
    或者直接：
    triggers = get_path("claude.strong_triggers", default=[...])
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_CONFIG_PATH = Path(__file__).resolve().parent / "config.json"
_EXAMPLE_PATH = Path(__file__).resolve().parent / "config.example.json"

_cached_config: dict | None = None


# ── 内置默认值（永远兜底，即使 .json 都不存在）─────────────────────────
# 这里的值必须跟 dispatcher.py 原硬编码常量一致，确保行为不变

_BUILTIN_DEFAULTS: dict = {
    "claude": {
        "strong_triggers": [
            "@claude", "@Claude",
            "让 claude", "让claude", "让 Claude", "让Claude",
            "新增加功能", "新增功能", "加个功能", "添加功能", "添加新功能",
            "给 bot 加", "给bot加", "帮 bot 加", "帮bot加",
        ],
        "weak_triggers": [
            "帮我加", "帮我做", "帮我写", "帮我修", "帮我看",
            "实现一下", "实现这个", "做个", "做一个",
        ],
        "cancel_words": [
            "退出", "取消", "不要了", "算了", "停",
            "exit", "cancel", "quit",
            "/exit", "/quit", "/cancel",
            "退出claude", "退出 claude", "取消claude", "取消 claude",
        ],
        "confirm_words": [
            "执行", "好", "好的", "ok", "go", "干", "继续", "yes", "y", "1",
            "确认", "确定", "改吧", "动手", "开干",
        ],
        "phase1_timeout_seconds": 600,
        "phase2_timeout_seconds": 1800,
        "weak_confidence_threshold": 60,  # 低于此值走 CLARIFY
    },
    "voice_ack": {
        "max_chars": 35,  # voice_ack 超过这个就走兜底
    },
    "tools": {
        "case_insensitive_matching": True,
    },
    "audit": {
        "max_durations_retained": 100,  # claude_phase_durations 保留多少条
    },
}


def _deep_merge(base: dict, override: dict) -> dict:
    """递归合并 override 到 base 副本，返回新 dict。"""
    result = dict(base)
    for k, v in override.items():
        if k in result and isinstance(result[k], dict) and isinstance(v, dict):
            result[k] = _deep_merge(result[k], v)
        else:
            result[k] = v
    return result


def _load_json_safe(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            logger.warning(f"[config] {path.name} root is not an object; ignoring")
            return {}
        # 去掉以 _ 开头的注释字段
        return {k: v for k, v in data.items() if not k.startswith("_")}
    except Exception as e:
        logger.warning(f"[config] failed to load {path}: {e}")
        return {}


def load_unified_config(force_reload: bool = False) -> dict:
    """加载并合并配置：BUILTIN_DEFAULTS ← config.example.json ← config.json ← workspace/config.json。

    13.3 · workspace 覆盖优先级最高。
    实例缓存，重复调用零成本。force_reload=True 重新读盘。
    """
    global _cached_config
    if _cached_config is not None and not force_reload:
        return _cached_config

    cfg = dict(_BUILTIN_DEFAULTS)
    example = _load_json_safe(_EXAMPLE_PATH)
    if example:
        cfg = _deep_merge(cfg, example)
    local = _load_json_safe(_CONFIG_PATH)
    if local:
        cfg = _deep_merge(cfg, local)
    # 13.3 · workspace/config.json 覆盖（最高优先级）
    try:
        from . import workspace as _ws
        ws_cfg_path = _ws.resolve("config.json")
        if ws_cfg_path:
            ws_data = _load_json_safe(ws_cfg_path)
            if ws_data:
                cfg = _deep_merge(cfg, ws_data)
    except Exception as e:
        logger.warning(f"[config] workspace overlay failed: {e}")

    _cached_config = cfg
    return cfg


def get_path(dotted_path: str, default: Any = None) -> Any:
    """按 'a.b.c' 取值，缺失返回 default。"""
    cfg = load_unified_config()
    node = cfg
    for key in dotted_path.split("."):
        if not isinstance(node, dict) or key not in node:
            return default
        node = node[key]
    return node


def reload() -> dict:
    """强制重读 .json 并清缓存。运行时让配置生效用。"""
    return load_unified_config(force_reload=True)
