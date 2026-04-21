"""Markdown briefing renderer.

Takes (facts_bundle, CrossReferenceResult) and produces a human-readable
Chinese briefing with bias-camp attribution.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import List, Optional

from .models import ArticleFacts, CrossReferenceResult, EntityTrackingResult

# Short Chinese labels for each bias_tag we ship in sources.yaml.
# Unknown tags fall back to the tag itself — harmless.
BIAS_LABEL_ZH: dict[str, str] = {
    "western-wire":       "西方通讯社",
    "western-uk":         "英国视角",
    "middle-east":        "中东视角",
    "russia-state":       "俄方官方",
    "china-state":        "中国官方",
    "china-nationalist":  "中国民族主义",
    "overseas-chinese":   "海外中文",
}


def _label(bias_tag: str) -> str:
    return BIAS_LABEL_ZH.get(bias_tag, bias_tag)


def render_markdown(
    topic: str,
    facts_bundle: List[ArticleFacts],
    cross: CrossReferenceResult,
    entities: Optional[EntityTrackingResult] = None,
) -> str:
    camps = sorted({f.bias_tag for f in facts_bundle})
    when_str = cross.generated_at.strftime("%Y-%m-%d %H:%M UTC")

    lines: list[str] = []
    lines.append(f"# 每日简报：{topic}")
    lines.append("")
    lines.append(
        f"> 生成时间：{when_str}  ·  "
        f"命中报道 **{len(facts_bundle)}** 篇  ·  "
        f"覆盖 **{len(camps)}** 个立场阵营（{', '.join(_label(c) for c in camps)}）"
    )
    lines.append("")

    # ── 共识事实 ────────────────────────────────────────────────
    lines.append("## 🤝 共识事实")
    lines.append("")
    lines.append("_以下事实在多个对立阵营的报道中都被承认，可信度相对较高。_")
    lines.append("")
    if cross.consensus_facts:
        for c in cross.consensus_facts:
            lines.append(f"- {c}")
    else:
        lines.append("- （本轮分析未识别出跨阵营共识。）")
    lines.append("")

    # ── 叙事分歧 ────────────────────────────────────────────────
    lines.append("## ⚔️ 叙事分歧")
    lines.append("")
    if cross.divergences:
        for i, d in enumerate(cross.divergences, 1):
            lines.append(f"### 分歧 {i}：{d.point}")
            lines.append("")
            for tag, claim in d.camp_claims.items():
                lines.append(f"- **{_label(tag)}**：{claim}")
            if d.observation:
                lines.append("")
                lines.append(f"> 📝 观察：{d.observation}")
            lines.append("")
    else:
        lines.append("_本轮分析未识别出显著分歧。_")
        lines.append("")

    # ── 可疑缺口 ────────────────────────────────────────────────
    if cross.suspicious_gaps:
        lines.append("## 🕳️ 可疑缺口")
        lines.append("")
        lines.append("_仅单一阵营提及、但若属实对立阵营理应跟进的信息点。_")
        lines.append("")
        for g in cross.suspicious_gaps:
            lines.append(f"- {g}")
        lines.append("")

    # ── 人物状态速览 ─────────────────────────────────────────────
    if entities and entities.entities:
        lines.append("## 👤 人物状态速览")
        lines.append("")
        for e in entities.entities:
            alias_str = " · ".join(e.aliases) if e.aliases else ""
            header = e.canonical_name
            if e.position:
                header += f"（{e.position}）"
            lines.append(f"### {header}")
            if alias_str:
                lines.append(f"别名：{alias_str}  ")
            lines.append(f"**动作**：{e.action_or_status}  ")
            lines.append(f"**状态变化**：{e.status_change or '—'}  ")
            if e.per_source_framing:
                lines.append("**阵营差异**：")
                for tag, framing in e.per_source_framing.items():
                    lines.append(f"- {_label(tag)}：{framing}")
            lines.append("")

    # ── 原文链接 ────────────────────────────────────────────────
    lines.append("## 🔗 原文链接")
    lines.append("")
    for s in cross.sources_covered:
        lines.append(f"- [{_label(s.bias_tag)}] [{s.title}]({s.url}) — {s.source_name}")
    lines.append("")

    # ── 附录：事实提取明细（折叠） ──────────────────────────────
    lines.append("<details>")
    lines.append("<summary>附录：各篇文章的事实提取明细</summary>")
    lines.append("")
    for f in facts_bundle:
        lines.append(f"#### {_label(f.bias_tag)} — {f.source_name}")
        lines.append(f"**标题**：[{f.title}]({f.article_url})")
        lines.append("")
        fx = f.facts
        lines.append(f"- 时间：{fx.when or '—'}")
        lines.append(f"- 地点：{fx.where or '—'}")
        lines.append(f"- 人物：{'、'.join(fx.who) if fx.who else '—'}")
        lines.append(f"- 动作：{fx.action or '—'}")
        if fx.context:
            lines.append(f"- 背景：{fx.context}")
        if fx.numbers:
            lines.append(f"- 数据：{'；'.join(fx.numbers)}")
        if fx.key_quotes:
            lines.append("- 关键引言：")
            for q in fx.key_quotes:
                lines.append(f"  - {q}")
        if fx.source_claims_verbatim:
            lines.append("- 官方表态/引述：")
            for claim in fx.source_claims_verbatim:
                lines.append(f"  - {claim}")
        lines.append("")
    lines.append("</details>")
    lines.append("")

    return "\n".join(lines)


def write_brief(
    output_dir: Path,
    topic: str,
    md_content: str,
) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    safe_topic = topic.replace("|", "_").replace("/", "_").replace(" ", "_")
    fname = f"{safe_topic}_{datetime.now().strftime('%Y%m%d_%H%M')}.md"
    path = output_dir / fname
    path.write_text(md_content, encoding="utf-8")
    return path
