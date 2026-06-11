# encoding:utf-8
"""周分析 · 纯确定性数据层（P12.5）。

这里只放**不调 LLM** 的周分析模块——pandas / datetime 算就能得出结果的部分。
LLM 解读部分（story arc / attention shift / narrative elasticity）保留在
pipeline.py，跟这层互补：

- 这层：周时间窗内的"事实数据"（按日计数、按阵营首报时间）
- pipeline 那层：LLM 解读"事实数据背后的叙事"（故事弧线、注意力转移、叙事弹性）

为什么分开：
- 这层结果可独立缓存（同样的 facts_bundle → 永远同样的 stats）
- 这层是确定性的，测试简单
- 未来想加新的数据维度（如每日 sentiment 平均值）放这里，不污染 LLM 路径
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import List

from .models import ArticleFacts, CampFirstSeen

_SGT = timezone(timedelta(hours=8))


def compute_info_lag(facts_bundle: List[ArticleFacts]) -> List[CampFirstSeen]:
    """每个阵营第一次报这个话题的时间，按到达时间排序。

    lag_hours 是相对最早报道阵营的时差（小时）。纯确定性计算。
    """
    camp_min: dict[str, datetime] = {}
    camp_source: dict[str, str] = {}
    for f in facts_bundle:
        if not f.published_at:
            continue
        dt = f.published_at.astimezone(_SGT)
        if f.bias_tag not in camp_min or dt < camp_min[f.bias_tag]:
            camp_min[f.bias_tag] = dt
            camp_source[f.bias_tag] = f.source_name

    if not camp_min:
        return []

    global_first = min(camp_min.values())
    return [
        CampFirstSeen(
            bias_tag=bias_tag,
            source_name=camp_source[bias_tag],
            first_date=first_dt.strftime("%Y-%m-%d"),
            lag_hours=round((first_dt - global_first).total_seconds() / 3600, 1),
        )
        for bias_tag, first_dt in sorted(camp_min.items(), key=lambda x: x[1])
    ]


def compute_daily_counts(facts_bundle: List[ArticleFacts]) -> dict[str, int]:
    """按 UTC+8 日历日统计文章数，给覆盖动量图用。"""
    counts: Counter[str] = Counter()
    for f in facts_bundle:
        if f.published_at:
            day = f.published_at.astimezone(_SGT).date().isoformat()
            counts[day] += 1
    return dict(sorted(counts.items()))
