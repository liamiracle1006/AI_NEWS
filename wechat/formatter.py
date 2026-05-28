# encoding:utf-8
"""把 AI_NEWS 的 JSON 结果格式化为微信文本 / 图片。"""
from __future__ import annotations

import io
import os
import textwrap
from datetime import datetime
from typing import Any

# Pillow is required (CoW already depends on it)
from PIL import Image, ImageDraw, ImageFont


WX_MAX_TEXT_LEN = 1800  # 单条微信消息建议上限


CAMP_LABELS = {
    "western-wire": "西方通讯社",
    "western-uk": "英国视角",
    "us-liberal": "美国主流",
    "us-conservative": "美国保守",
    "middle-east": "中东视角",
    "russia-state": "俄方官方",
    "china-state": "中国官方",
    "china-nationalist": "中国民族主义",
    "overseas-chinese": "海外中文",
    "china-hk": "香港视角",
}


def _camp(tag: str) -> str:
    return CAMP_LABELS.get(tag, tag)


def _truncate(s: str, n: int) -> str:
    s = (s or "").strip()
    return s if len(s) <= n else s[: n - 1] + "…"


def format_analysis(result: dict, topic: str, brief_id: str | None = None) -> str:
    """主分析结果 → 微信文本（≤ 1800 字）。"""
    facts = result.get("facts_bundle") or []
    cross = result.get("cross") or {}
    entities = (result.get("entities") or {}).get("entities") or []
    weekly = result.get("weekly")

    camps = sorted({f.get("bias_tag") for f in facts if f.get("bias_tag")})
    lines = [
        f"🗞️ {topic} · 分析摘要",
        f"📊 命中 {len(facts)} 篇 · 覆盖 {len(camps)} 个阵营（{' / '.join(_camp(c) for c in camps)}）",
        "",
    ]

    # 共识事实（最多 5 条）
    consensus = cross.get("consensus_facts") or []
    if consensus:
        lines.append("✅ 共识事实")
        for i, c in enumerate(consensus[:5], 1):
            lines.append(f"{i}. {_truncate(c, 140)}")
        lines.append("")

    # 主要分歧（最多 3 条）
    divs = cross.get("divergences") or []
    if divs:
        lines.append(f"⚔️ 主要分歧（共 {len(divs)} 处）")
        for d in divs[:3]:
            point = d.get("point") or d.get("claim") or ""
            obs = d.get("observation") or d.get("explanation") or ""
            lines.append(f"• {_truncate(point, 80)}")
            if obs:
                lines.append(f"  ↳ {_truncate(obs, 100)}")
        lines.append("")

    # 可疑缺口（最多 2 条）
    gaps = cross.get("suspicious_gaps") or []
    if gaps:
        lines.append("🕳️ 可疑缺口")
        for g in gaps[:2]:
            lines.append(f"• {_truncate(g, 120)}")
        lines.append("")

    # 关键人物（最多 4 个）
    if entities:
        lines.append("👤 关键人物")
        for e in entities[:4]:
            name = e.get("canonical_name") or e.get("name") or "?"
            act = e.get("action_or_status") or "—"
            lines.append(f"• {name}：{_truncate(act, 90)}")
        lines.append("")

    # 周分析摘要
    if weekly:
        arc = weekly.get("story_arc") or []
        lag = weekly.get("camp_first_seen") or []
        if arc:
            lines.append("🕰️ 叙事时间线")
            for n in arc[:3]:
                lines.append(f"• {n.get('date_range', '')}：{_truncate(n.get('main_event', ''), 80)}")
            lines.append("")
        if lag and any(c.get("lag_hours", 0) > 72 for c in lag):
            slow = [c for c in lag if c.get("lag_hours", 0) > 72][:2]
            lines.append("⏱️ 显著信息延迟")
            for c in slow:
                lines.append(f"• {_camp(c.get('bias_tag', ''))} 滞后 {c.get('lag_hours', 0):.0f}h")
            lines.append("")

    if brief_id:
        lines.append(f"🔗 完整版：http://localhost:5173/?brief={brief_id}")

    out = "\n".join(lines).strip()
    return _truncate(out, WX_MAX_TEXT_LEN)


def format_heat(heat: dict[str, int], top_n: int = 15) -> str:
    """全球热度榜 → 微信文本。"""
    if not heat:
        return "📡 今日暂无新闻热度数据。"

    today = datetime.now().strftime("%Y-%m-%d")
    sorted_pairs = sorted(heat.items(), key=lambda x: x[1], reverse=True)[:top_n]

    # 中文名映射
    from .intent_parser import COUNTRY_ZH
    lines = [f"🌡️ 今日全球新闻热度榜 ({today})", ""]
    for i, (country, count) in enumerate(sorted_pairs, 1):
        zh = COUNTRY_ZH.get(country, country)
        bar = "█" * min(count, 20)
        lines.append(f"{i:>2}. {zh:<6} {bar} {count}")
    lines.append("")
    lines.append("💬 回复 '分析 <国家>' 查看深度报告")
    return "\n".join(lines)


def format_articles(articles: list[dict], country_zh: str, week: bool = False) -> str:
    """国家文章列表 → 微信文本。"""
    label = "本周" if week else "今天"
    if not articles:
        return f"📭 {country_zh} {label} 暂无标题命中的报道。"

    lines = [f"📰 {country_zh} · {label}相关报道（{len(articles)} 篇）", ""]
    for i, a in enumerate(articles[:8], 1):
        camp = _camp(a.get("bias_tag", ""))
        src = a.get("source_name", "")
        title = _truncate(a.get("title", ""), 80)
        lines.append(f"{i}. [{camp}] {src}")
        lines.append(f"   {title}")
        if a.get("url"):
            lines.append(f"   🔗 {a['url']}")
        lines.append("")
    if len(articles) > 8:
        lines.append(f"... 还有 {len(articles) - 8} 篇未列出。")
    return _truncate("\n".join(lines), WX_MAX_TEXT_LEN)


def format_briefs(briefs: list[dict]) -> str:
    """历史简报列表 → 微信文本。"""
    if not briefs:
        return "📚 暂无历史简报。"
    lines = ["📚 历史分析简报（最近 10 条）", ""]
    for b in briefs[:10]:
        topic = _truncate(b.get("topic", ""), 30)
        when = b.get("generated_at", "")[:16].replace("T", " ")
        lines.append(f"• {when} · {topic}（{b.get('article_count', '?')} 篇）")
    return "\n".join(lines)


def format_help() -> str:
    return (
        "🤖 AI News 指令速查\n\n"
        "📊 深度分析\n"
        "  · 分析以色列 / 分析加沙\n"
        "  · 加沙本周分析 / 本周以色列\n"
        "  · 在指令后加 '图片' → 截图版（HTML 美化）\n"
        "  · 在指令后加 'PDF' / '报告' → PDF 完整版\n\n"
        "🌡️ 全球热度\n"
        "  · 今日热点 / 热度榜\n\n"
        "📰 单国文章\n"
        "  · 中国新闻 / 以色列新闻本周\n\n"
        "📚 历史\n"
        "  · 历史简报 / 历史分析\n\n"
        "💬 直接对话（非以上指令）则进入 LLM 闲聊模式。"
    )


# ──────────────────────────────────────────────────────────────────────────────
# 图片渲染（Pillow）
# ──────────────────────────────────────────────────────────────────────────────

_FONT_CANDIDATES = [
    "C:/Windows/Fonts/msyh.ttc",      # 微软雅黑
    "C:/Windows/Fonts/simhei.ttf",
    "/System/Library/Fonts/PingFang.ttc",
    "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
]


def _load_font(size: int) -> ImageFont.ImageFont:
    for path in _FONT_CANDIDATES:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                continue
    return ImageFont.load_default()


def _wrap_text(text: str, width: int) -> list[str]:
    out = []
    for raw_line in (text or "").split("\n"):
        if not raw_line:
            out.append("")
            continue
        # 中文按字符宽度断行（简单实现，每行最多 width 个等效中文字符）
        line = ""
        line_len = 0
        for ch in raw_line:
            ch_w = 2 if ord(ch) > 127 else 1
            if line_len + ch_w > width * 2:
                out.append(line)
                line, line_len = ch, ch_w
            else:
                line += ch
                line_len += ch_w
        if line:
            out.append(line)
    return out


# Emoji → 纯文字 token，渲染图片时替换（普通字体不含 emoji 字形会变豆腐块）。
# 选用方括号包裹，让标题在 PNG 里仍然醒目可辨识。
_EMOJI_TO_TEXT_TITLE = {
    "🗞️": "■ ", "🌡️": "■ ", "📰": "■ ",
    "📚": "■ ", "🤖": "■ ",
}
_EMOJI_TO_TEXT_SECTION = {
    "✅": "● ", "⚔️": "● ", "🕳️": "● ",
    "👤": "● ", "🕰️": "● ", "⏱️": "● ",
    "📊": "  ", "💬": "  ", "📡": "  ", "📭": "  ",
}
_EMOJI_TO_TEXT_INLINE = {
    "🔍": "[查] ", "🔗": "[链接] ", "⚠️": "[!] ",
    "•": "·", "→": "→", "↳": "→",
}


def _strip_emojis_for_image(text: str) -> tuple[str, set[str], set[str]]:
    """把 emoji 换成纯文字 token。返回 (新文本, 标题行起始词集合, 章节行起始词集合)。"""
    title_starts = set()
    section_starts = set()
    for e, t in _EMOJI_TO_TEXT_TITLE.items():
        if e in text:
            text = text.replace(e, t)
            title_starts.add(t.strip())
    for e, t in _EMOJI_TO_TEXT_SECTION.items():
        if e in text:
            text = text.replace(e, t)
            if t.strip():
                section_starts.add(t.strip())
    for e, t in _EMOJI_TO_TEXT_INLINE.items():
        text = text.replace(e, t)
    return text, title_starts, section_starts


def render_analysis_card(result: dict, topic: str) -> bytes:
    """渲染一张分析结果卡片，返回 PNG bytes。"""
    text = format_analysis(result, topic)
    text, title_starts, section_starts = _strip_emojis_for_image(text)
    lines = _wrap_text(text, width=36)

    line_height = 32
    padding = 40
    width = 800
    height = max(600, padding * 2 + len(lines) * line_height)

    img = Image.new("RGB", (width, height), "#ffffff")
    draw = ImageDraw.Draw(img)

    font_h1 = _load_font(28)
    font_body = _load_font(18)
    font_small = _load_font(14)

    # 顶部装饰条
    draw.rectangle([(0, 0), (width, 8)], fill="#3b82f6")

    y = padding
    for line in lines:
        stripped = line.lstrip()
        # 标题（项目名 / 模块大类）→ 深色大字
        if any(stripped.startswith(t) for t in title_starts):
            draw.text((padding, y), line, font=font_h1, fill="#1f2937")
            y += line_height + 4
        # 章节小标题 → 蓝色大字
        elif any(stripped.startswith(s) for s in section_starts):
            draw.text((padding, y), line, font=font_h1, fill="#2563eb")
            y += line_height
        else:
            draw.text((padding, y), line, font=font_body, fill="#374151")
            y += line_height

    # 底部签名
    draw.text(
        (padding, height - padding + 4),
        f"AI_NEWS · {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        font=font_small,
        fill="#9ca3af",
    )

    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()
