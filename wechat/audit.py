# encoding:utf-8
"""审计订阅者——示范怎么用 events.py（13.4）。

订阅几个关键事件，进程内累加计数 + 按小时分桶。`审计` 管理命令展示数据。

设计：纯进程内统计，不落 SQLite（routing_log 已经做了持久化审计）；这里只
是"运行时心率"——bot 启动以来的活动概况。重启清零。
"""
from __future__ import annotations

import time
from collections import Counter, defaultdict

from . import events


# ── 全局计数器 ────────────────────────────────────────────────────────────


_event_counts: Counter = Counter()
_intent_counts: Counter = Counter()
_tool_counts: Counter = Counter()
_claude_phase_durations: list[tuple[str, float]] = []  # [(phase, elapsed_ms)]
_hourly_messages: dict[str, int] = defaultdict(int)  # "HH" → count
_start_ts: float = time.time()


# ── 订阅 handler ─────────────────────────────────────────────────────────


def _on_message_received(**kw):
    _event_counts["message_received"] += 1
    hour = time.strftime("%H", time.localtime())
    _hourly_messages[hour] += 1


def _on_intent_classified(**kw):
    _event_counts["intent_classified"] += 1
    intent = kw.get("intent")
    if intent:
        _intent_counts[intent] += 1


def _on_tool_called(**kw):
    _event_counts["tool_called"] += 1
    tool = kw.get("tool")
    if tool:
        _tool_counts[tool] += 1


def _on_claude_phase_completed(**kw):
    phase = kw.get("phase", "?")
    elapsed = kw.get("elapsed_ms")
    _event_counts[f"claude_{phase}_completed"] += 1
    if elapsed is not None:
        _claude_phase_durations.append((phase, elapsed))
        # 只保留最近 100 条避免无限增长
        if len(_claude_phase_durations) > 100:
            del _claude_phase_durations[:50]


def _on_reminder_fired(**kw):
    _event_counts["reminder_fired"] += 1


def _on_pairing_requested(**kw):
    _event_counts["pairing_requested"] += 1


def _on_pairing_approved(**kw):
    _event_counts["pairing_approved"] += 1


# ── 注册（模块 import 时自动跑）──────────────────────────────────────────


def register_default_audit_subscribers():
    """启动时调一次。dispatcher.__init__ 会调。"""
    events.on("message_received", _on_message_received)
    events.on("intent_classified", _on_intent_classified)
    events.on("tool_called", _on_tool_called)
    events.on("claude_phase1_completed", _on_claude_phase_completed)
    events.on("claude_phase2_completed", _on_claude_phase_completed)
    events.on("reminder_fired", _on_reminder_fired)
    events.on("pairing_requested", _on_pairing_requested)
    events.on("pairing_approved", _on_pairing_approved)


# ── 展示给用户的报告 ──────────────────────────────────────────────────────


def format_audit_report() -> str:
    """给 `审计` 管理命令用的人类可读报告。"""
    uptime_s = int(time.time() - _start_ts)
    uptime_str = _format_uptime(uptime_s)

    lines = [f"运行了 {uptime_str}。"]

    # 事件计数
    if _event_counts:
        lines.append("\n事件计数：")
        for ev, cnt in _event_counts.most_common():
            lines.append(f"  {ev}: {cnt}")

    # intent 分布
    if _intent_counts:
        lines.append("\n意图分布（前 8）：")
        for intent, cnt in _intent_counts.most_common(8):
            lines.append(f"  {intent}: {cnt}")

    # 工具使用
    if _tool_counts:
        lines.append("\n工具使用：")
        for tool, cnt in _tool_counts.most_common():
            lines.append(f"  {tool}: {cnt}")

    # Claude 耗时统计
    if _claude_phase_durations:
        by_phase: dict[str, list[float]] = defaultdict(list)
        for phase, ms in _claude_phase_durations:
            by_phase[phase].append(ms)
        lines.append("\nClaude 耗时（ms）：")
        for phase, msl in by_phase.items():
            avg = sum(msl) / len(msl)
            lines.append(f"  {phase}: n={len(msl)} avg={avg:.0f}")

    # 时段分布
    if _hourly_messages:
        lines.append("\n按小时消息数：")
        for hour in sorted(_hourly_messages.keys()):
            lines.append(f"  {hour}h: {_hourly_messages[hour]}")

    # 当前订阅者
    subs = events.all_events()
    if subs:
        lines.append(f"\n事件订阅：{sum(subs.values())} 个 handlers 覆盖 {len(subs)} 种事件")

    return "\n".join(lines)


def _format_uptime(seconds: int) -> str:
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        return f"{seconds // 60}m {seconds % 60}s"
    h = seconds // 3600
    m = (seconds % 3600) // 60
    return f"{h}h {m}m"
