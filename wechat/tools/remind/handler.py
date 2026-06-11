# encoding:utf-8
"""单次定时提醒工具（P12.4）。

触发后用 DeepSeek 解析自然语言时间表达 → 落 SQLite reminders 表 →
scheduler 后台扫一遍 → 到点用 voice_ack 推送到微信。
"""
from __future__ import annotations

import json
import logging
import re
import time
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

TOOL_NAME = "remind"
TRIGGER_KEYWORDS = (
    "提醒我", "提醒一下", "提醒",
    "remind me", "remind",
    "我要的提醒", "查提醒", "列提醒", "取消提醒",
)


_PARSER_SYSTEM = """\
你是个时间表达解析器。用户用自然语言说『几时几分干啥』，你输出 JSON 一行：
{"ts_due": <unix 时间戳，秒，整数>, "message": "<提醒内容简短一句>"}

输入会附带当前时间（unix 秒）作为参考，你必须基于这个时间算未来时间点。

示例：
当前 2026-06-11 14:30，用户：『30 分钟后看锅』
→ {"ts_due": <计算结果>, "message": "看锅"}

当前 2026-06-11 14:30，用户：『明天 8 点开会』
→ {"ts_due": <计算结果>, "message": "开会"}

当前 2026-06-11 14:30，用户：『晚上 10 点吃药』
→ {"ts_due": <计算结果>, "message": "吃药"}

规则：
- ts_due 必须是 unix 秒（整数），未来时间
- message 抽出"干啥"那部分，5-15 字
- 模糊时间（"晚点" / "等会"）→ 默认 30 分钟后
- 解析不出 → {"error": "解析失败，请明确时间"}
- 只输出 JSON 一行，不要其他文字"""


def _parse_with_llm(user_text: str, provider) -> tuple[float, str] | tuple[None, str]:
    """返回 (ts_due, message) 或 (None, err_msg)。"""
    now = time.time()
    now_str = datetime.fromtimestamp(now).strftime("%Y-%m-%d %H:%M:%S")
    user_prompt = f"当前时间：{now_str}（unix={int(now)}）\n用户：『{user_text}』"
    try:
        raw = provider.complete(
            _PARSER_SYSTEM,
            user_prompt,
            max_tokens=120,
            temperature=0.0,
            json_mode=True,
        )
    except Exception as e:
        logger.warning(f"[remind] llm parse failed: {e}")
        return None, "时间解析挂了，再说一次？"
    try:
        data = json.loads(raw)
    except Exception:
        # 容错：去掉 ``` 围栏再试一次
        s = raw.strip().strip("`").strip()
        if s.lower().startswith("json"):
            s = s[4:].strip()
        try:
            data = json.loads(s)
        except Exception:
            return None, "时间没听懂，能具体点吗？比如『30 分钟后』『明天 8 点』"
    if "error" in data:
        return None, data["error"]
    ts = data.get("ts_due")
    msg = data.get("message", user_text)
    if not ts or ts <= now:
        return None, "时间得是未来的，再说一次？"
    return float(ts), str(msg)[:120]


def _format_due(ts: float) -> str:
    """提醒时间的自然语言描述。"""
    delta = ts - time.time()
    if delta < 60:
        return "马上"
    if delta < 3600:
        return f"{int(delta/60)} 分钟后"
    if delta < 86400:
        return f"{int(delta/3600)} 小时后"
    days = int(delta / 86400)
    return f"{days} 天后"


def handle(text: str, ctx) -> str:
    """ctx 是 Dispatcher。"""
    from wechat import routing_log

    # user_id 从 ctx 不太好拿（handler 签名是 text + ctx），但 dispatcher 的
    # _try_tools 调 handle 时只传了 text + ctx；ctx 是 self（Dispatcher），
    # 不知道当前 user_id。我们改用 ctx._current_user_id 协议。
    user_id = getattr(ctx, "_current_user_id", None) or "unknown"

    # 列出 / 取消 操作（不要进 LLM 解析）
    if any(k in text for k in ("列提醒", "查提醒", "我的提醒", "list reminders")):
        pending = routing_log.list_pending_reminders(user_id)
        if not pending:
            return "你现在没有等的提醒。"
        lines = [f"等着的 {len(pending)} 条："]
        for r in pending:
            lines.append(f"  [#{r['id']}] {_format_due(r['ts_due'])}: {r['message']}")
        lines.append("\n发『取消提醒 #N』可以撤掉某条。")
        return "\n".join(lines)

    cancel_match = re.search(r"取消提醒[\s#]*(\d+)", text)
    if cancel_match:
        rid = int(cancel_match.group(1))
        ok = routing_log.cancel_reminder(rid)
        return f"撤了。" if ok else f"#{rid} 不存在或已经触发。"

    # 落库
    provider = ctx._get_llm() if hasattr(ctx, "_get_llm") else None
    if provider is None:
        return "时间解析挂了，回头再试。"
    ts, message_or_err = _parse_with_llm(text, provider)
    if ts is None:
        return message_or_err
    rid = routing_log.add_reminder(user_id, ts, message_or_err)
    if not rid:
        return "落库失败了，再说一次？"
    return f"好，{_format_due(ts)}提醒你：『{message_or_err}』。"
