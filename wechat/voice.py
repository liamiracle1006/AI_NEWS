# encoding:utf-8
"""voice_ack：让 bot 回复从模板化变口语化（批 12.1 对话感重塑核心）。

调用方场景：所有 dispatcher 写死的固定 ack 模板都该走这个：
- 旧："🧠 收到，正在让 Claude 做可行性分析（约 30 秒 – 2 分钟）..."
- 新：voice_ack("看这个需求", "ack", user_msg) → "嗯，让我想想看。"

设计原则：
- ≤ 25 字
- 口语化，像朋友顺嘴说一句
- 不带 emoji（emoji 是机器人腔）
- LLM 不可用时走 tone-based 兜底（4-6 条短句轮换）
- 调用失败永远不抛——返回兜底文字
"""
from __future__ import annotations

import logging
import random
from typing import Optional

logger = logging.getLogger(__name__)


# tone → 兜底短句池（LLM 挂了就用这个）
_FALLBACK_BY_TONE: dict[str, list[str]] = {
    "ack": ["嗯，看一下。", "好，让我想想。", "稍等。", "嗯。"],
    "doing": ["好，开干。", "在改了。", "嗯，做着呢。"],
    "done": ["改完了。", "好了。", "搞定。"],
    "fail": ["出问题了，看看日志吧。", "卡住了，先这样。", "没搞定。"],
    "clarify": ["不太懂你是想干啥，能再说一下吗？"],
    "refine_doing": ["再改改。", "想想再调一下。", "嗯，再改改。"],
    "running": ["还在跑，再等等。", "马上好。", "稍等。"],
    "cancel_done": ["好的，不弄了。", "停了。", "嗯，撤了。"],
    "restart_ack": ["收到，重启一下。", "好，重启。"],
    "branch_resume": ["接着上次的来。", "好，从上次那里继续。"],
}


_SYSTEM_PROMPT = """你是一个微信助手的语气包装层。
给你一个简短的意图描述 + 用户原话 + 语气类型，你输出一句口语回复。

要求：
- 最多 25 个汉字
- 像朋友顺嘴说一句话，不要装模作样
- 不要带 emoji
- 不要说"已开始""正在为您""请稍候"这种客服腔
- 不要重复用户原话
- 直接输出回复，不要加引号、不要前言

语气说明：
- ack：刚接到任务，先回个"嗯，看一下"这种
- doing：开始干活了
- done：完成
- fail：出错了
- clarify：没听懂，反问
- refine_doing：收到补充意见，继续改方案
- running：用户催了一下，告诉他还在跑
- cancel_done：用户取消了，确认一下
- restart_ack：要重启
- branch_resume：接续一个旧任务"""


def _random_fallback(tone: str) -> str:
    pool = _FALLBACK_BY_TONE.get(tone) or _FALLBACK_BY_TONE["ack"]
    return random.choice(pool)


def voice_ack(intent: str, tone: str, user_msg: str = "", provider=None) -> str:
    """生成一句口语化的 ack 回复。

    Args:
        intent: 简短意图描述，给 LLM 看的（如"看这个改代码需求"/"开始改"/"还在跑"）
        tone: 语气类型，见 _FALLBACK_BY_TONE 的 key
        user_msg: 用户原消息（给 LLM 上下文用；不强制传）
        provider: LLM provider 实例（Dispatcher._get_llm() 返回的）；None 直接走兜底

    Returns:
        ≤ 25 字的口语回复。绝不抛异常。
    """
    if not provider:
        return _random_fallback(tone)

    user_prompt = (
        f'意图：{intent}\n'
        f'语气：{tone}\n'
        f'用户原话：{user_msg[:80]}'
    )
    try:
        raw = provider.complete(
            _SYSTEM_PROMPT,
            user_prompt,
            max_tokens=80,
            temperature=0.8,  # 让回复多样一点
        )
    except Exception as e:
        logger.warning(f"[voice_ack] LLM failed for tone={tone}: {e}")
        return _random_fallback(tone)

    reply = (raw or "").strip()
    # 去引号 / 去 markdown 残留
    reply = reply.strip('"\'`').strip('「」『』').strip()
    if not reply:
        return _random_fallback(tone)
    # 超长截断（≤ 25 中文字大概对应 75 字节）
    if len(reply) > 35:
        # 保险起见还是兜底，避免 LLM 写了一大段
        logger.info(f"[voice_ack] reply too long ({len(reply)}), falling back: {reply[:60]}")
        return _random_fallback(tone)
    return reply
