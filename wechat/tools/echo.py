# encoding:utf-8
"""Echo 复读机 —— 最简工具模板（约 30 行；新工具仿这个写）。

触发：消息含 'echo' / '回声' / '复读'
返回：触发词后面那段文字

用法示例：
    微信发 "echo 你好"     → bot 回 "📣 你好"
    微信发 "回声 hello"    → bot 回 "📣 hello"
"""
from __future__ import annotations

TOOL_NAME = "echo"
TRIGGER_KEYWORDS = ("echo", "回声", "复读")


def handle(text: str, ctx) -> str:
    """ctx 是 Dispatcher 实例；这个最简工具用不到，但复杂工具可以拿来调
    ctx.channel.send_text() / ctx._get_llm() 等。
    """
    # 去掉触发词，剩下的就是要复读的内容
    rest = text
    for kw in TRIGGER_KEYWORDS:
        if kw in rest:
            rest = rest.replace(kw, "", 1).strip()
            break
    if not rest:
        return "请在触发词后面跟一段文字，比如『echo 你好』"
    return f"📣 {rest}"
