# encoding:utf-8
"""Hooks / 事件总线（13.4）。

OpenClaw 风格的内部 pub/sub。dispatcher 在关键节点 emit 事件，外部模块可
on(event, handler) 订阅——解耦"主流程"和"横切关注点"（审计 / 遥测 /
外部 webhook）。

设计原则：
- 进程内、单线程同步派发（不引 Redis 等组件）
- 订阅者异常隔离：单个 handler 挂掉不影响其他 handler、不影响主流程
- emit 接受任意关键字参数，handler 按需取
- 全局单例 registry，模块 import 时自动可用

emit 的事件命名约定（动名词时态）：
- `message_received`     收到消息（路由前）
- `intent_classified`    分类完毕（intent_rescue / weak_classifier）
- `tool_called`          工具调用完毕
- `claude_phase1_started`/`claude_phase1_completed`
- `claude_phase2_started`/`claude_phase2_completed`
- `claude_pending_resolved` cancel / confirm / refine 完毕
- `reminder_fired`       提醒推送出去
- `pairing_requested`    陌生人申请配对
- `pairing_approved`     管理员批准配对

新加事件不需要改 events.py，dispatcher 那边直接 emit 即可。订阅者按
约定字段读 kwargs。
"""
from __future__ import annotations

import logging
from collections import defaultdict
from typing import Callable

logger = logging.getLogger(__name__)

# event_name → [handler, handler, ...]
_subscribers: dict[str, list[Callable]] = defaultdict(list)


def on(event: str, handler: Callable) -> None:
    """订阅事件。handler 签名 `def h(**kwargs): ...`。重复注册同一 handler 不去重。"""
    _subscribers[event].append(handler)
    logger.info(f"[events] subscribed to '{event}': {handler.__qualname__}")


def emit(event: str, **kwargs) -> None:
    """发布事件。所有订阅 handler 同步调用，异常隔离。"""
    handlers = _subscribers.get(event, [])
    if not handlers:
        return
    for h in handlers:
        try:
            h(**kwargs)
        except Exception as e:
            # 永远不让订阅者挂掉影响主流程
            logger.warning(
                f"[events] handler {h.__qualname__} for '{event}' raised: {e}"
            )


def unsubscribe(event: str, handler: Callable) -> bool:
    """取消订阅。返回是否找到并移除。"""
    if event not in _subscribers:
        return False
    try:
        _subscribers[event].remove(handler)
        return True
    except ValueError:
        return False


def subscribers_for(event: str) -> list[Callable]:
    """看某事件有哪些订阅者。debug 用。"""
    return list(_subscribers.get(event, []))


def all_events() -> dict[str, int]:
    """所有有订阅者的事件名 → 订阅者数。debug / 路由日志展示用。"""
    return {ev: len(handlers) for ev, handlers in _subscribers.items() if handlers}
