# encoding:utf-8
"""命令式工具插件 registry —— 自动发现 + 路由（P2）。

每个 .py 文件 = 一个工具。dispatcher 在 parse_intent 失败后、chat_fallback 之前
调 find_tool(text) 看有没有工具能接住。

每个工具必须提供（违反则启动时跳过 + warning 日志）：
    TOOL_NAME: str             — 唯一标识，用于日志
    TRIGGER_KEYWORDS: tuple    — substring 匹配；命中任一即触发
    handle(text, ctx) -> str   — 返回回复文本

写完丢进 wechat/tools/ → 重启 bot 即生效。
"""
from __future__ import annotations

import importlib
import logging
import pkgutil
from dataclasses import dataclass
from typing import Callable, Optional

logger = logging.getLogger(__name__)


@dataclass
class Tool:
    name: str
    keywords: tuple[str, ...]
    handle: Callable[[str, "object"], str]
    module_path: str


_REGISTRY: list[Tool] = []


def _load_tools():
    """启动时一次性扫描所有 wechat.tools.* 子模块。"""
    import wechat.tools as pkg

    for _, name, _ in pkgutil.iter_modules(pkg.__path__):
        if name.startswith("_"):
            continue
        try:
            mod = importlib.import_module(f"wechat.tools.{name}")
        except Exception as e:
            logger.exception(f"[tools] failed to import {name}: {e}")
            continue

        required = ("TOOL_NAME", "TRIGGER_KEYWORDS", "handle")
        missing = [a for a in required if not hasattr(mod, a)]
        if missing:
            logger.warning(f"[tools] {name} missing {missing}; skipping")
            continue

        _REGISTRY.append(Tool(
            name=getattr(mod, "TOOL_NAME"),
            keywords=tuple(getattr(mod, "TRIGGER_KEYWORDS")),
            handle=getattr(mod, "handle"),
            module_path=f"wechat.tools.{name}",
        ))
        logger.info(
            f"[tools] registered: {mod.TOOL_NAME} "
            f"(keywords: {tuple(mod.TRIGGER_KEYWORDS)})"
        )


_load_tools()


def find_tool(text: str) -> Optional[Tool]:
    """找第一个 keyword 命中 text 的工具。"""
    if not text:
        return None
    s_lower = text.lower()
    for tool in _REGISTRY:
        for kw in tool.keywords:
            if kw in text or kw.lower() in s_lower:
                return tool
    return None


def list_tools() -> list[Tool]:
    return list(_REGISTRY)
