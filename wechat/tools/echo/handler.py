# encoding:utf-8
"""Echo 复读机 —— 最简工具模板（约 30 行；新工具仿这个写）。

P12.3：tools/<name>.py 升级为 tools/<name>/ 目录，目录内：
- handler.py：本文件，逻辑代码
- SKILL.md：人类可读 + LLM 可读的工具说明
"""
from __future__ import annotations

TOOL_NAME = "echo"
TRIGGER_KEYWORDS = ("echo", "回声", "复读")


def handle(text: str, ctx) -> str:
    """ctx 是 Dispatcher 实例。"""
    rest = text
    for kw in TRIGGER_KEYWORDS:
        if kw in rest:
            rest = rest.replace(kw, "", 1).strip()
            break
    if not rest:
        return "请在触发词后面跟一段文字，比如『echo 你好』"
    return f"📣 {rest}"
