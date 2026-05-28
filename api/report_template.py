"""HTML report template for brief render endpoint.

Single-page report rendered server-side. Designed for both browser viewing
and headless capture (Playwright → PNG / PDF). Width 800px so the screenshot
fits standard WeChat image aspect ratio comfortably.
"""
from __future__ import annotations

from datetime import datetime
from html import escape
from typing import Any

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

CAMP_COLORS = {
    "western-wire": "#3b82f6",
    "western-uk": "#0ea5e9",
    "us-liberal": "#6366f1",
    "us-conservative": "#f59e0b",
    "middle-east": "#10b981",
    "russia-state": "#f97316",
    "china-state": "#ef4444",
    "china-nationalist": "#e11d48",
    "overseas-chinese": "#8b5cf6",
    "china-hk": "#14b8a6",
}


def _camp_label(tag: str) -> str:
    return CAMP_LABELS.get(tag, tag)


def _camp_color(tag: str) -> str:
    return CAMP_COLORS.get(tag, "#9ca3af")


def _camp_badge(tag: str) -> str:
    color = _camp_color(tag)
    return (
        f'<span class="badge" style="background:{color}1A;color:{color};'
        f'border-color:{color}33;">{escape(_camp_label(tag))}</span>'
    )


def _bar_row(label: str, value: int, max_value: int) -> str:
    pct = max(2, int(value / max(max_value, 1) * 100))
    return (
        f'<div class="bar-row">'
        f'<span class="bar-label">{escape(label)}</span>'
        f'<div class="bar-track"><div class="bar-fill" style="width:{pct}%"></div></div>'
        f'<span class="bar-value">{value}</span>'
        f'</div>'
    )


def render_brief_html(result: dict[str, Any], topic: str) -> str:
    """Render the analysis result as a standalone HTML page."""
    facts = result.get("facts_bundle") or []
    cross = result.get("cross") or {}
    entities = (result.get("entities") or {}).get("entities") or []
    weekly = result.get("weekly")

    camps = sorted({f.get("bias_tag") for f in facts if f.get("bias_tag")})

    # ── Consensus facts ──
    consensus_html = ""
    for i, c in enumerate(cross.get("consensus_facts") or [], 1):
        consensus_html += f'<li><span class="num">{i}</span>{escape(c)}</li>'

    # ── Divergences ──
    div_html = ""
    for d in cross.get("divergences") or []:
        point = d.get("point") or d.get("claim") or ""
        obs = d.get("observation") or d.get("explanation") or ""
        camp_claims = d.get("camp_claims") or {}
        claim_rows = ""
        for camp, claim in camp_claims.items():
            claim_rows += (
                f'<div class="claim-row">{_camp_badge(camp)}'
                f'<span class="claim-text">{escape(claim)}</span></div>'
            )
        div_html += (
            f'<div class="card">'
            f'<div class="card-title">{escape(point)}</div>'
            f'{claim_rows}'
            + (f'<div class="card-foot">💡 {escape(obs)}</div>' if obs else "")
            + '</div>'
        )

    # ── Gaps ──
    gaps_html = ""
    for g in cross.get("suspicious_gaps") or []:
        gaps_html += f'<li>{escape(g)}</li>'

    # ── Entities ──
    entity_html = ""
    for e in entities:
        name = e.get("canonical_name") or e.get("name") or "?"
        position = e.get("position") or ""
        action = e.get("action_or_status") or ""
        framing = e.get("per_source_framing") or {}
        framing_rows = ""
        for camp, desc in framing.items():
            framing_rows += (
                f'<div class="claim-row">{_camp_badge(camp)}'
                f'<span class="claim-text">{escape(desc)}</span></div>'
            )
        entity_html += (
            f'<div class="card">'
            f'<div class="card-title">{escape(name)}'
            + (f' <span class="muted">（{escape(position)}）</span>' if position else "")
            + f'</div>'
            f'<div class="entity-action">{escape(action)}</div>'
            + (f'<div class="entity-framing">{framing_rows}</div>' if framing_rows else "")
            + '</div>'
        )

    # ── Weekly modules ──
    weekly_html = ""
    if weekly:
        # Daily counts bar chart
        daily_counts = weekly.get("daily_counts") or {}
        if daily_counts:
            max_count = max(daily_counts.values())
            bars = ""
            for day, count in daily_counts.items():
                bars += _bar_row(day[5:].replace("-", "/"), count, max_count)
            weekly_html += (
                f'<section><h2>📈 报道热度趋势</h2>'
                f'<div class="bar-chart">{bars}</div></section>'
            )
        # Story arc
        arc = weekly.get("story_arc") or []
        if arc:
            arc_items = ""
            for n in arc:
                reactions = ""
                for tag, reaction in (n.get("camp_reactions") or {}).items():
                    reactions += (
                        f'<div class="claim-row">{_camp_badge(tag)}'
                        f'<span class="claim-text">{escape(reaction)}</span></div>'
                    )
                arc_items += (
                    f'<div class="arc-node">'
                    f'<div class="arc-date">{escape(n.get("date_range", ""))}</div>'
                    f'<div class="arc-event">{escape(n.get("main_event", ""))}</div>'
                    f'{reactions}'
                    + (f'<div class="arc-sig">💡 {escape(n.get("significance") or "")}</div>'
                       if n.get("significance") else "")
                    + '</div>'
                )
            weekly_html += f'<section><h2>🕰️ 叙事时间线</h2>{arc_items}</section>'

        # Info lag
        lag = weekly.get("camp_first_seen") or []
        if lag:
            lag_rows = ""
            for c in lag:
                hrs = c.get("lag_hours", 0)
                badge_class = "lag-bad" if hrs > 72 else ("lag-ok" if hrs == 0 else "lag-mid")
                lag_rows += (
                    f'<tr>'
                    f'<td>{_camp_badge(c.get("bias_tag", ""))}</td>'
                    f'<td>{escape(c.get("source_name", ""))}</td>'
                    f'<td>{escape(c.get("first_date", ""))}</td>'
                    f'<td class="{badge_class}">{"最早" if hrs == 0 else f"+{hrs:.0f}h"}</td>'
                    f'</tr>'
                )
            weekly_html += (
                f'<section><h2>⏱️ 信息响应速度</h2>'
                f'<table><thead><tr><th>阵营</th><th>来源</th><th>首报</th><th>滞后</th></tr></thead>'
                f'<tbody>{lag_rows}</tbody></table></section>'
            )

    # ── Source list ──
    sources_html = ""
    for f in facts:
        sources_html += (
            f'<li>{_camp_badge(f.get("bias_tag", ""))}'
            f'<a href="{escape(f.get("article_url", "#"))}">{escape(f.get("title", ""))}</a>'
            f'<span class="muted"> — {escape(f.get("source_name", ""))}</span></li>'
        )

    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    camps_summary = " / ".join(_camp_label(c) for c in camps)

    return f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>{escape(topic)} · 分析报告</title>
<style>
  * {{ box-sizing: border-box; }}
  body {{
    font-family: "Microsoft YaHei", "PingFang SC", system-ui, sans-serif;
    margin: 0;
    background: #f9fafb;
    color: #111827;
    -webkit-print-color-adjust: exact;
    print-color-adjust: exact;
  }}
  .report {{
    width: 800px;
    margin: 0 auto;
    padding: 40px 36px;
    background: #fff;
  }}
  .hero {{
    border-bottom: 3px solid #3b82f6;
    padding-bottom: 18px;
    margin-bottom: 28px;
  }}
  .hero h1 {{
    margin: 0;
    font-size: 28px;
    color: #1e3a8a;
    line-height: 1.2;
  }}
  .hero .meta {{
    margin-top: 8px;
    font-size: 13px;
    color: #6b7280;
  }}
  .hero .meta span {{ margin-right: 12px; }}
  section {{ margin-bottom: 28px; }}
  section > h2 {{
    font-size: 18px;
    color: #1f2937;
    border-left: 4px solid #3b82f6;
    padding-left: 10px;
    margin: 0 0 12px 0;
  }}
  ol, ul {{ padding-left: 0; list-style: none; margin: 0; }}
  ol li, ul li {{
    padding: 8px 12px;
    background: #f9fafb;
    border-radius: 6px;
    margin-bottom: 6px;
    font-size: 14px;
    line-height: 1.55;
  }}
  ol li .num {{
    display: inline-block;
    width: 22px;
    height: 22px;
    line-height: 22px;
    border-radius: 11px;
    background: #3b82f6;
    color: #fff;
    text-align: center;
    font-size: 12px;
    font-weight: bold;
    margin-right: 8px;
  }}
  .badge {{
    display: inline-block;
    font-size: 11px;
    padding: 2px 8px;
    border-radius: 10px;
    border: 1px solid;
    font-weight: 500;
    margin-right: 6px;
    line-height: 1.4;
  }}
  .card {{
    background: #f9fafb;
    border: 1px solid #e5e7eb;
    border-radius: 8px;
    padding: 12px 14px;
    margin-bottom: 12px;
  }}
  .card-title {{ font-weight: 600; font-size: 14px; margin-bottom: 8px; }}
  .card-foot {{
    margin-top: 8px;
    font-size: 12px;
    color: #6b7280;
    font-style: italic;
    padding-top: 8px;
    border-top: 1px dashed #e5e7eb;
  }}
  .claim-row {{
    display: flex;
    align-items: flex-start;
    gap: 6px;
    margin: 4px 0;
    font-size: 13px;
    line-height: 1.5;
  }}
  .claim-text {{ flex: 1; color: #374151; }}
  .entity-action {{ font-size: 13px; color: #374151; margin-bottom: 6px; }}
  .entity-framing {{
    margin-top: 8px;
    padding-top: 8px;
    border-top: 1px dashed #e5e7eb;
  }}
  .muted {{ color: #9ca3af; font-size: 12px; }}
  .bar-chart {{ padding: 8px 4px; }}
  .bar-row {{
    display: flex;
    align-items: center;
    gap: 8px;
    margin: 6px 0;
    font-size: 12px;
  }}
  .bar-label {{ width: 50px; color: #6b7280; }}
  .bar-track {{ flex: 1; background: #e5e7eb; border-radius: 3px; height: 14px; }}
  .bar-fill {{
    background: linear-gradient(90deg, #60a5fa, #3b82f6);
    height: 100%;
    border-radius: 3px;
  }}
  .bar-value {{ width: 30px; text-align: right; color: #1f2937; font-weight: 500; }}
  .arc-node {{
    border-left: 3px solid #3b82f6;
    padding: 6px 0 6px 14px;
    margin-bottom: 12px;
  }}
  .arc-date {{ font-size: 12px; color: #3b82f6; font-weight: 600; }}
  .arc-event {{ font-size: 14px; color: #1f2937; margin: 4px 0; }}
  .arc-sig {{ font-size: 12px; color: #6b7280; font-style: italic; margin-top: 6px; }}
  table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
  th, td {{ text-align: left; padding: 6px 8px; border-bottom: 1px solid #e5e7eb; }}
  th {{ background: #f3f4f6; color: #6b7280; font-weight: 500; font-size: 12px; }}
  .lag-ok {{ color: #10b981; font-weight: 600; }}
  .lag-mid {{ color: #6b7280; }}
  .lag-bad {{ color: #ef4444; font-weight: 600; }}
  .footer {{
    margin-top: 32px;
    padding-top: 16px;
    border-top: 1px solid #e5e7eb;
    text-align: center;
    color: #9ca3af;
    font-size: 11px;
  }}
  @media print {{
    body {{ background: #fff; }}
    .report {{ padding: 24px; }}
  }}
</style>
</head>
<body>
<div class="report">
  <div class="hero">
    <h1>📰 {escape(topic)} · 分析报告</h1>
    <div class="meta">
      <span>命中 <b>{len(facts)}</b> 篇</span>
      <span>覆盖 <b>{len(camps)}</b> 个阵营</span>
      <span class="muted">{escape(camps_summary)}</span>
    </div>
  </div>

  {f'<section><h2>✅ 共识事实</h2><ol>{consensus_html}</ol></section>' if consensus_html else ''}
  {f'<section><h2>⚔️ 主要分歧</h2>{div_html}</section>' if div_html else ''}
  {f'<section><h2>🕳️ 可疑缺口</h2><ul>{gaps_html}</ul></section>' if gaps_html else ''}
  {f'<section><h2>👤 关键人物</h2>{entity_html}</section>' if entity_html else ''}
  {weekly_html}
  {f'<section><h2>🔗 信息来源</h2><ul style="font-size:12px;">{sources_html}</ul></section>' if sources_html else ''}

  <div class="footer">AI_NEWS · 生成于 {now}</div>
</div>
</body>
</html>
"""
