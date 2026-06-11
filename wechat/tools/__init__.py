# encoding:utf-8
"""命令式工具插件 registry —— 自动发现 + 路由（P2 + P12.3）。

支持两种工具结构（向后兼容）：

1. **目录结构**（推荐，P12.3+）：
   wechat/tools/<name>/
     ├── handler.py    含 TOOL_NAME / TRIGGER_KEYWORDS / handle
     └── SKILL.md      人类可读 + LLM 可读的工具说明

2. **单文件**（旧版，兼容）：
   wechat/tools/<name>.py    含 TOOL_NAME / TRIGGER_KEYWORDS / handle

新加工具用结构 1；旧的可以原样跑。dispatcher 在 parse_intent 失败、
chat_fallback 之前调 find_tool(text)。命中谁就调谁。

每个工具必须提供：
    TOOL_NAME: str             — 唯一标识
    TRIGGER_KEYWORDS: tuple    — substring 匹配（大小写不敏感）
    handle(text, ctx) -> str   — 返回回复文本

SKILL.md（仅目录结构）会被 dispatcher 在 @claude 调用前注入 prompt，
让 Claude 知道现有工具能干啥，能避免重复造轮子或瞎触发 @claude。
"""
from __future__ import annotations

import importlib
import logging
import pkgutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

logger = logging.getLogger(__name__)

_TOOLS_DIR = Path(__file__).resolve().parent


@dataclass
class Tool:
    name: str
    keywords: tuple[str, ...]
    handle: Callable[[str, "object"], str]
    module_path: str
    skill_md: str = ""  # SKILL.md 全文（如果有），用于注入 @claude prompt


_REGISTRY: list[Tool] = []


def _try_register(mod, module_path: str, skill_md: str = ""):
    """从已 import 的模块抽取契约字段并注册。"""
    required = ("TOOL_NAME", "TRIGGER_KEYWORDS", "handle")
    missing = [a for a in required if not hasattr(mod, a)]
    if missing:
        logger.warning(f"[tools] {module_path} missing {missing}; skipping")
        return
    _REGISTRY.append(Tool(
        name=getattr(mod, "TOOL_NAME"),
        keywords=tuple(getattr(mod, "TRIGGER_KEYWORDS")),
        handle=getattr(mod, "handle"),
        module_path=module_path,
        skill_md=skill_md,
    ))
    logger.info(
        f"[tools] registered: {mod.TOOL_NAME} "
        f"(keywords: {tuple(mod.TRIGGER_KEYWORDS)}, skill_md: {len(skill_md)}B)"
    )


def _load_tools():
    """扫 wechat/tools/ 子项：先目录（推荐），再单文件（兼容）。"""
    for entry in sorted(_TOOLS_DIR.iterdir()):
        name = entry.name
        if name.startswith("_") or name == "README.md":
            continue

        # 情况 1：目录形式 wechat/tools/<name>/handler.py + SKILL.md
        if entry.is_dir():
            handler_path = entry / "handler.py"
            if not handler_path.exists():
                continue
            try:
                mod = importlib.import_module(f"wechat.tools.{name}.handler")
            except Exception as e:
                logger.exception(f"[tools] failed to import {name}/handler.py: {e}")
                continue
            skill_md_path = entry / "SKILL.md"
            skill_md = ""
            if skill_md_path.exists():
                try:
                    skill_md = skill_md_path.read_text(encoding="utf-8")
                except Exception as e:
                    logger.warning(f"[tools] failed to read {name}/SKILL.md: {e}")
            _try_register(mod, f"wechat.tools.{name}.handler", skill_md=skill_md)
            continue

        # 情况 2：单文件 wechat/tools/<name>.py（向后兼容）
        if entry.suffix == ".py":
            try:
                mod = importlib.import_module(f"wechat.tools.{entry.stem}")
            except Exception as e:
                logger.exception(f"[tools] failed to import {entry.stem}.py: {e}")
                continue
            _try_register(mod, f"wechat.tools.{entry.stem}")


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


def all_skills_summary() -> str:
    """把所有工具的 SKILL.md 拼成一段，给 @claude 注入用。

    没 SKILL.md 的工具只列出 name + keywords 一行。
    """
    parts = ["# 当前已注册的 wechat tools（每个工具的 SKILL.md / 简介）"]
    for tool in _REGISTRY:
        parts.append(f"\n## {tool.name}")
        if tool.skill_md:
            parts.append(tool.skill_md)
        else:
            parts.append(f"触发词：{', '.join(tool.keywords)}\n（无 SKILL.md）")
    return "\n".join(parts)
