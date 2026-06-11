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
    """从已 import 的模块抽取契约字段并注册。

    13.3 · 同名工具去重：workspace 先注册 → 后续内置同名跳过（workspace 胜出）。
    """
    required = ("TOOL_NAME", "TRIGGER_KEYWORDS", "handle")
    missing = [a for a in required if not hasattr(mod, a)]
    if missing:
        logger.warning(f"[tools] {module_path} missing {missing}; skipping")
        return
    tool_name = getattr(mod, "TOOL_NAME")
    # 已存在同名 → 跳过（workspace 先扫，覆盖内置）
    if any(t.name == tool_name for t in _REGISTRY):
        logger.info(f"[tools] {module_path} skipped (name '{tool_name}' already registered)")
        return
    _REGISTRY.append(Tool(
        name=tool_name,
        keywords=tuple(getattr(mod, "TRIGGER_KEYWORDS")),
        handle=getattr(mod, "handle"),
        module_path=module_path,
        skill_md=skill_md,
    ))
    logger.info(
        f"[tools] registered: {tool_name} from {module_path} "
        f"(keywords: {tuple(mod.TRIGGER_KEYWORDS)}, skill_md: {len(skill_md)}B)"
    )


def _import_file(name: str, file_path: "Path"):
    """用 file_path 加载 .py 模块（workspace 的 tools 不在包路径下）。"""
    import importlib.util
    spec = importlib.util.spec_from_file_location(name, str(file_path))
    if spec is None or spec.loader is None:
        return None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _load_tools_in_dir(tools_dir: "Path", source_label: str = "builtin"):
    """从指定目录扫工具。source_label 用于日志区分来源。"""
    from pathlib import Path
    if not tools_dir.exists() or not tools_dir.is_dir():
        return
    for entry in sorted(tools_dir.iterdir()):
        name = entry.name
        if name.startswith("_") or name == "README.md":
            continue

        # 情况 1：目录形式 <name>/handler.py + SKILL.md
        if entry.is_dir():
            handler_path = entry / "handler.py"
            if not handler_path.exists():
                continue
            try:
                if source_label == "builtin":
                    # 内置走包路径，让 import 链正常（handler 里可以 from .. import X）
                    mod = importlib.import_module(f"wechat.tools.{name}.handler")
                else:
                    # workspace 走文件路径加载
                    mod = _import_file(f"ws_tool_{name}", handler_path)
                    if mod is None:
                        continue
            except Exception as e:
                logger.exception(f"[tools] failed to import {source_label}/{name}/handler.py: {e}")
                continue
            skill_md_path = entry / "SKILL.md"
            skill_md = ""
            if skill_md_path.exists():
                try:
                    skill_md = skill_md_path.read_text(encoding="utf-8")
                except Exception as e:
                    logger.warning(f"[tools] failed to read {name}/SKILL.md: {e}")
            _try_register(mod, f"{source_label}.{name}", skill_md=skill_md)
            continue

        # 情况 2：单文件 <name>.py（兼容旧版本）
        if entry.suffix == ".py":
            try:
                if source_label == "builtin":
                    mod = importlib.import_module(f"wechat.tools.{entry.stem}")
                else:
                    mod = _import_file(f"ws_tool_{entry.stem}", entry)
                    if mod is None:
                        continue
            except Exception as e:
                logger.exception(f"[tools] failed to import {source_label}/{entry.stem}.py: {e}")
                continue
            _try_register(mod, f"{source_label}.{entry.stem}")


def _load_tools():
    """13.3 · 先扫 workspace（优先级高 = 用户覆盖），再扫内置。

    同名工具时第一个注册的胜出（list 顺序决定 find_tool 优先级）。所以 workspace
    在前可以覆盖同名内置工具。
    """
    # workspace 优先
    try:
        from .. import workspace as _ws
        for ws_dir in _ws.tools_dirs():
            _load_tools_in_dir(ws_dir, source_label="workspace")
    except Exception as e:
        logger.warning(f"[tools] workspace scan failed: {e}")
    # 内置
    _load_tools_in_dir(_TOOLS_DIR, source_label="builtin")


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
