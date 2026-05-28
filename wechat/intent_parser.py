# encoding:utf-8
"""自然语言指令 → 结构化意图。

设计原则：能用关键词/正则识别就用，绝不调 LLM；识别不到就返回 None，
让 CoW 走默认对话流程，避免误触发。
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional


# 常见国家/地区中英文别名 → 用于 analyze 的关键词
# 复用 AI_NEWS 的 geo_keywords 不现实（跨项目），这里维护一份精简版
COUNTRY_ALIASES = {
    "以色列": "以色列|Israel",
    "加沙": "加沙|Gaza|巴勒斯坦|Palestinian",
    "巴勒斯坦": "巴勒斯坦|Palestinian|Gaza|加沙",
    "伊朗": "伊朗|Iran",
    "黎巴嫩": "黎巴嫩|Lebanon|Hezbollah",
    "叙利亚": "叙利亚|Syria",
    "也门": "也门|Yemen|Houthi",
    "乌克兰": "乌克兰|Ukraine|Kyiv|Kiev",
    "俄罗斯": "俄罗斯|Russia|Putin|普京",
    "中国": "中国|China|Beijing|北京",
    "台湾": "台湾|Taiwan|Taipei|台北",
    "美国": "美国|United States|Washington|Biden|Trump",
    "日本": "日本|Japan|Tokyo",
    "韩国": "韩国|South Korea|Seoul",
    "朝鲜": "朝鲜|North Korea|DPRK|Kim Jong Un",
    "印度": "印度|India|Modi",
    "巴基斯坦": "巴基斯坦|Pakistan",
    "土耳其": "土耳其|Turkey|Erdogan",
    "沙特": "沙特|Saudi Arabia|MBS",
    "埃及": "埃及|Egypt",
    "委内瑞拉": "委内瑞拉|Venezuela|Maduro",
    "古巴": "古巴|Cuba",
    "苏丹": "苏丹|Sudan|RSF",
    "缅甸": "缅甸|Myanmar",
    "阿富汗": "阿富汗|Afghanistan|Taliban",
    "德国": "德国|Germany",
    "法国": "法国|France|Macron",
    "英国": "英国|United Kingdom|Britain|UK",
    "意大利": "意大利|Italy|Meloni",
    "波兰": "波兰|Poland",
}

# 国家英文名 → 中文（用于 articles 命令）
COUNTRY_ZH = {
    "Israel": "以色列", "China": "中国", "Taiwan": "台湾", "Ukraine": "乌克兰",
    "Russia": "俄罗斯", "United States of America": "美国", "Iran": "伊朗",
    "Palestine": "巴勒斯坦", "Lebanon": "黎巴嫩", "Syria": "叙利亚",
    "Japan": "日本", "South Korea": "韩国", "North Korea": "朝鲜",
    "India": "印度", "Pakistan": "巴基斯坦", "Turkey": "土耳其",
}
COUNTRY_ZH_TO_EN = {v: k for k, v in COUNTRY_ZH.items()}


@dataclass
class Intent:
    action: str  # "analyze" | "heat" | "articles" | "help" | "brief_list" | "confirm_analyze"
    keyword: Optional[str] = None       # for analyze: pipe-separated query
    country: Optional[str] = None       # for articles: English country name
    country_zh: Optional[str] = None    # for articles: Chinese display name
    week: bool = False
    image: bool = False                 # 是否要 PNG 截图输出
    pdf: bool = False                   # 是否要 PDF 报告输出
    # confirm_analyze 用：歧义时给用户选项
    multi_options: list[str] = None     # 多个国家命中时，让用户选哪个
    raw_text: str = ""                  # 原始文本，确认提示中显示


# ─── 各种触发词 ──────────────────────────────────────────────────────────────

ANALYZE_VERBS = ("分析", "深度分析", "解读")
WEEK_HINTS = ("本周", "这周", "近一周", "近七天", "7天", "一周")
IMAGE_HINTS = ("图片", "图卡", "海报", "图表", "截图")
PDF_HINTS = ("pdf", "PDF", "报告", "完整版", "详细版")
HEAT_HINTS = ("热点", "热度榜", "今日热点", "新闻热度", "全球热度")
ARTICLES_VERBS = ("新闻", "报道", "看新闻", "看看")
HELP_HINTS = ("帮助", "怎么用", "指令", "menu", "help")


def parse_intent(text: str) -> Optional[Intent]:
    """主入口。识别不到返回 None。"""
    if not text:
        return None
    s = text.strip()

    # 1. 帮助
    if any(h in s.lower() for h in HELP_HINTS):
        return Intent(action="help")

    # 2. 热点榜
    if any(h in s for h in HEAT_HINTS):
        return Intent(action="heat")

    # 3. 历史简报列表
    if "历史" in s and ("简报" in s or "分析" in s):
        return Intent(action="brief_list")

    want_pdf = any(h in s for h in PDF_HINTS)
    want_image = any(h in s for h in IMAGE_HINTS)

    # 4. 深度分析（关键词 + verb）
    if any(v in s for v in ANALYZE_VERBS):
        week = any(h in s for h in WEEK_HINTS)

        # 策略一：扫文本里有没有已知国家名（不管位置，"分析以色列的国际形势" 也能命中）
        matched_countries = [zh for zh in COUNTRY_ALIASES if zh in s]
        if len(matched_countries) == 1:
            zh = matched_countries[0]
            return Intent(
                action="analyze",
                keyword=COUNTRY_ALIASES[zh],
                country_zh=zh,
                week=week,
                image=want_image,
                pdf=want_pdf,
            )
        if len(matched_countries) > 1:
            # 多个国家命中 → 让用户确认选哪个
            return Intent(
                action="confirm_analyze",
                multi_options=matched_countries,
                week=week,
                image=want_image,
                pdf=want_pdf,
                raw_text=s,
            )

        # 策略二：fallback 自由提取（用户可能在分析非国家话题，比如"分析比特币"）
        keyword = _extract_keyword(s, ANALYZE_VERBS)
        if keyword:
            # 短词（< 6 字）直接尝试分析；长词大概率是"分析XX的YY"这种歧义表述
            if len(keyword) <= 6:
                return Intent(
                    action="analyze",
                    keyword=COUNTRY_ALIASES.get(keyword, keyword),
                    week=week,
                    image=want_image,
                    pdf=want_pdf,
                )
            else:
                # 长词 → 不确定，让用户确认或重新表述
                return Intent(
                    action="confirm_analyze",
                    keyword=keyword,
                    week=week,
                    image=want_image,
                    pdf=want_pdf,
                    raw_text=s,
                )

    # 5. "X 新闻" / "X 本周分析" / "X 今天" — 简写
    for zh, alias in COUNTRY_ALIASES.items():
        if zh in s:
            # "X 新闻" → articles
            if any(v in s for v in ARTICLES_VERBS):
                return Intent(
                    action="articles",
                    country=COUNTRY_ZH_TO_EN.get(zh, zh),
                    country_zh=zh,
                    week=any(h in s for h in WEEK_HINTS),
                )
            # 仅 "X 本周" / "本周 X" → 本周分析
            if any(h in s for h in WEEK_HINTS):
                return Intent(
                    action="analyze",
                    keyword=alias,
                    week=True,
                    image=want_image,
                    pdf=want_pdf,
                )

    return None


def _extract_keyword(s: str, verbs: tuple) -> Optional[str]:
    """从 '分析以色列' / '深度分析 加沙 本周' 中抽出主语。"""
    rest = s
    # 先替换长触发词，避免 '分析' 先替换导致 '深度分析' 残留 '深度'
    for v in sorted(verbs, key=len, reverse=True):
        rest = rest.replace(v, " ")
    for h in sorted(WEEK_HINTS + IMAGE_HINTS + PDF_HINTS, key=len, reverse=True):
        rest = rest.replace(h, " ")
    # 留下的连续中文/英文/数字片段
    m = re.search(r"[一-鿿]+|[A-Za-z][A-Za-z\s]+", rest)
    if not m:
        return None
    kw = m.group(0).strip()
    # 太短不算（避免"分析"自身被理解为关键词）
    if len(kw) < 2:
        return None
    return kw
