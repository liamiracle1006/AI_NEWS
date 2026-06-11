# encoding:utf-8
"""Workspace 抽象（13.3）——OpenClaw 的 `~/.openclaw/workspace/` 风格。

让用户的本地定制（自加的工具 / 自定义 SOUL.md / 自己的 config.json）跟代码仓库
分离。升级 AI_NEWS 代码不影响本地定制；多设备同步只需要同步 workspace 目录。

布局：
    ~/.ai_news/workspace/
    ├── tools/<name>/handler.py + SKILL.md   ← 用户加的工具（优先级 > wechat/tools/）
    ├── SOUL.md                              ← 覆盖 wechat/SOUL.md
    ├── AGENTS.md                            ← 覆盖 wechat/AGENTS.md
    ├── config.json                          ← 覆盖 wechat/config.json
    └── agents/<name>.json                   ← 用户加的 subagent

加载优先级（高 → 低）：
    workspace/X → wechat/X → 内置默认

Workspace 不存在 / 文件不存在时静默回落到 wechat/ 目录里的版本。100% 向后兼容。
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


def workspace_dir() -> Path:
    """workspace 根目录。可被 AI_NEWS_WORKSPACE 环境变量覆盖（测试 / CI 用）。"""
    override = os.environ.get("AI_NEWS_WORKSPACE")
    if override:
        return Path(override).expanduser()
    return Path.home() / ".ai_news" / "workspace"


def resolve(rel_path: str) -> Optional[Path]:
    """workspace 下找 rel_path；存在返回 Path，不存在返回 None。

    给 persona/config loader 用："先 workspace，没就回落 wechat/" 这个模式。
    """
    p = workspace_dir() / rel_path
    return p if p.exists() else None


def tools_dirs() -> list[Path]:
    """所有应该扫描的 tools 目录。tools loader 用。

    顺序：workspace/tools 优先（用户覆盖），然后 wechat/tools（内置 + 项目自带）。
    """
    out = []
    ws = workspace_dir() / "tools"
    if ws.exists() and ws.is_dir():
        out.append(ws)
    return out  # wechat/tools 由原 loader 用自己 path，这里只返工作区的


def agents_dirs() -> list[Path]:
    """所有应该扫描的 agents 目录。"""
    out = []
    ws = workspace_dir() / "agents"
    if ws.exists() and ws.is_dir():
        out.append(ws)
    return out
