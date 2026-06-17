# encoding:utf-8
"""Subagents loader（13.2）——OpenClaw .agents/ 风格。

每个 .json 定义一个 agent：
- name: 唯一标识
- description: 给用户看的简短说明
- model: 传给 claude --model（haiku-4-5 / sonnet-4-6 / opus-4-7 / 留空=默认）
- system_prompt: 追加到默认 PHASE_1/2_PROMPT 之前（留空=只用默认 prompt）
- allowed_tools: 白名单，传给 --allowedTools（留空=默认全部）
- disallowed_tools: 黑名单，追加到 --disallowedTools（合并已有 sandbox 黑名单）

用户在 @claude 触发文本里用 `(agent_name)` 选 agent：
- `@claude 加查股票工具` → 用默认 'code' agent（当前行为）
- `@claude (research) 看下最近 5 个 commit` → 用 'research'（Haiku + 只读）
- `@claude (summary) 总结这段: ...` → 用 'summary'（Haiku + 零工具）

dispatcher 拿到 agent_name 后传给 _run_claude_subprocess 构 argv。
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

_AGENTS_DIR = Path(__file__).resolve().parent


@dataclass
class Agent:
    name: str
    description: str = ""
    model: str = ""  # 留空 = claude --print 默认
    system_prompt: str = ""  # 追加到 PHASE_*_PROMPT 前
    allowed_tools: list[str] = field(default_factory=list)
    disallowed_tools: list[str] = field(default_factory=list)
    # 13.5 · 子进程 env 覆盖（如 deepseek_coder 用 ANTHROPIC_BASE_URL 切代理）
    env: dict[str, str] = field(default_factory=dict)


_REGISTRY: dict[str, Agent] = {}


def _load_agents_in_dir(agents_dir: Path, source_label: str):
    """从指定目录扫 .json agent 定义。"""
    if not agents_dir.exists() or not agents_dir.is_dir():
        return
    for f in sorted(agents_dir.glob("*.json")):
        if f.name.startswith("_"):
            continue
        try:
            with open(f, encoding="utf-8") as fh:
                data = json.load(fh)
        except Exception as e:
            logger.warning(f"[agents] failed to load {source_label}/{f.name}: {e}")
            continue
        if not isinstance(data, dict):
            logger.warning(f"[agents] {f.name} root is not object; skipping")
            continue
        # 去 _ 开头的注释字段
        data = {k: v for k, v in data.items() if not k.startswith("_")}
        name = data.get("name") or f.stem
        # 13.3 · 同名覆盖：workspace 先扫 → 后续内置同名跳过（workspace 胜出）
        if name in _REGISTRY:
            logger.info(f"[agents] {source_label}/{f.name} skipped (name '{name}' already registered)")
            continue
        try:
            agent = Agent(
                name=name,
                description=data.get("description", ""),
                model=data.get("model", ""),
                system_prompt=data.get("system_prompt", ""),
                allowed_tools=list(data.get("allowed_tools", [])),
                disallowed_tools=list(data.get("disallowed_tools", [])),
                env=dict(data.get("env", {})),
            )
        except Exception as e:
            logger.warning(f"[agents] {f.name} schema mismatch: {e}")
            continue
        _REGISTRY[name] = agent
        logger.info(f"[agents] registered: {name} from {source_label} (model={agent.model or 'default'})")


def _load_agents():
    """13.3 · 先 workspace（优先），后内置。"""
    try:
        from .. import workspace as _ws
        for ws_dir in _ws.agents_dirs():
            _load_agents_in_dir(ws_dir, "workspace")
    except Exception as e:
        logger.warning(f"[agents] workspace scan failed: {e}")
    _load_agents_in_dir(_AGENTS_DIR, "builtin")


_load_agents()


# ── trigger 文本里解析 (agent_name) 语法 ─────────────────────────────────

# 例：@claude (research) 看 commits  → group(1)="research"
_AGENT_RE = re.compile(r"\(([a-zA-Z][\w\-]{0,31})\)")


def parse_agent_from_trigger(text: str) -> tuple[Optional[str], str]:
    """从 trigger 文本里抽出 agent 名 + 剩余文本。

    返回 (agent_name, cleaned_text)；没声明 agent 返回 (None, text 原样)。
    只识别已注册的 agent；未注册的 `(xxx)` 不消耗。
    """
    if not text:
        return None, text
    m = _AGENT_RE.search(text)
    if not m:
        return None, text
    candidate = m.group(1).lower()
    if candidate not in _REGISTRY:
        return None, text
    # 删掉 (agent) 这段
    cleaned = (text[: m.start()] + text[m.end():]).strip()
    return candidate, cleaned


def get(name: str) -> Optional[Agent]:
    return _REGISTRY.get(name)


def get_default() -> Agent:
    """默认 'code' agent；不存在就构造一个空壳。"""
    if "code" in _REGISTRY:
        return _REGISTRY["code"]
    return Agent(name="code", description="default")


def list_agents() -> list[Agent]:
    return list(_REGISTRY.values())
