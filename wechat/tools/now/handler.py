# encoding:utf-8
"""当前时间 / 日期工具——纯 datetime，不调 LLM 不发请求。"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta

TOOL_NAME = "now"
TRIGGER_KEYWORDS = (
    "现在几点", "几点了", "现在时间",
    "今天几号", "今天日期", "今天星期几",
    "now time", "current time",
)

_WEEKDAY_ZH = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
_SGT = timezone(timedelta(hours=8))


def handle(text: str, ctx) -> str:
    now = datetime.now(tz=_SGT)
    # 根据触发词决定输出粒度
    if "星期" in text:
        return f"今天{_WEEKDAY_ZH[now.weekday()]}。"
    if "几号" in text or "日期" in text:
        return f"今天 {now.strftime('%Y-%m-%d')}（{_WEEKDAY_ZH[now.weekday()]}）。"
    # 默认：全量
    return f"{now.strftime('%Y-%m-%d %H:%M')}（{_WEEKDAY_ZH[now.weekday()]}）。"
