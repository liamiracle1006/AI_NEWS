# encoding:utf-8
"""翻译工具——复用项目已配置的 DeepSeek provider。"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

TOOL_NAME = "translate"
TRIGGER_KEYWORDS = ("翻译", "translate", "trans")


_SYS = (
    "你是个翻译。判断用户输入是中文还是英文，自动翻成另一种。"
    "其他语言（日韩法德等）默认翻译成中文，除非用户明确说要别的目标语言。"
    "**只输出翻译结果**，不要 '翻译：' / '译文如下' 这种前缀，"
    "不要解释、不要双语对照、不要 emoji。"
    "如果原文有歧义，挑最常见的意思翻；不要列多个版本。"
)


def handle(text: str, ctx) -> str:
    """ctx 是 Dispatcher。"""
    provider = ctx._get_llm() if hasattr(ctx, "_get_llm") else None
    if provider is None:
        return "LLM 没连上，翻不了。"

    # 去掉触发词，剩下的就是要翻的内容
    rest = text
    for kw in TRIGGER_KEYWORDS:
        if kw in rest:
            rest = rest.replace(kw, "", 1).strip()
            break
    if not rest:
        return "翻译啥？比如『翻译 hello world』。"

    try:
        result = provider.complete(_SYS, rest, max_tokens=600, temperature=0.0)
    except Exception as e:
        logger.warning(f"[translate] llm failed: {e}")
        return f"翻译挂了：{type(e).__name__}"

    return (result or "").strip() or "没翻出东西，再试一次？"
