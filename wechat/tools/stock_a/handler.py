# encoding:utf-8
"""A 股股价查询——东方财富 push2 接口，免 key 免登录，毫秒级响应。"""
from __future__ import annotations

import logging
import re
from typing import Optional

import requests

logger = logging.getLogger(__name__)

TOOL_NAME = "stock_a"
TRIGGER_KEYWORDS = ("股价", "股票", "A股", "a股")


# 中文名 → 6 位代码（按需扩；用户也可以直接发代码）
_NAME_TO_CODE = {
    "贵州茅台": "600519", "茅台": "600519",
    "宁德时代": "300750", "宁德": "300750",
    "比亚迪": "002594", "比亚迪股份": "002594",
    "工商银行": "601398", "工行": "601398",
    "中国平安": "601318", "平安": "601318",
    "招商银行": "600036", "招行": "600036",
    "腾讯控股": "00700", "腾讯": "00700",  # 港股
    "阿里巴巴": "09988", "阿里": "09988",  # 港股
    "中芯国际": "688981", "中芯": "688981",
    "京东方": "000725", "京东方A": "000725",
    "上证指数": "000001", "上证": "000001", "大盘": "000001",
    "深证成指": "399001", "深成指": "399001",
    "创业板指": "399006", "创业板": "399006",
    "沪深300": "000300", "300": "000300",
    "上证50": "000016", "50": "000016",
}


def _resolve_code(text: str) -> Optional[tuple[str, str]]:
    """返回 (code, market_code)。market_code: '1'=上交所/沪深指数, '0'=深交所/创业板, '116'=港股。"""
    # 数字代码：6 位 A 股，5 位港股
    m = re.search(r"\b(\d{5,6})\b", text)
    if m:
        code = m.group(1)
        return code, _market_code(code)
    # 中文名匹配
    for name, code in _NAME_TO_CODE.items():
        if name in text:
            return code, _market_code(code)
    return None


def _market_code(code: str) -> str:
    """6 位 A 股代码 → 东方财富 secid 的 market 前缀。"""
    if len(code) == 5:  # 港股
        return "116"
    # 沪市：60 开头主板 / 68 科创板 / 沪深指数 000001/000300/000016 / 港股通
    if code.startswith(("60", "68", "11", "15")) or code in ("000001", "000300", "000016"):
        return "1"
    # 沪深指数还有 399 开头的深市指数
    if code.startswith("399"):
        return "0"
    # 深市：00 / 30
    return "0"


def handle(text: str, ctx) -> str:
    resolved = _resolve_code(text)
    if not resolved:
        return ("没识别出股票。试试：\n"
                "  · 茅台股价 / 600519 股价\n"
                "  · 上证指数 / 大盘 / 50 / 300\n"
                "  · 腾讯股价（港股 5 位代码也行）")
    code, market = resolved
    secid = f"{market}.{code}"
    try:
        r = requests.get(
            "https://push2.eastmoney.com/api/qt/stock/get",
            params={"secid": secid, "fields": "f43,f44,f45,f46,f57,f58,f60,f170"},
            timeout=5,
        )
        r.raise_for_status()
        d = (r.json() or {}).get("data") or {}
    except Exception as e:
        return f"查股价挂了：{type(e).__name__}"
    if not d:
        return f"查不到 {code}，检查代码或换个名。"
    name = d.get("f58") or code
    price = (d.get("f43") or 0) / 100
    change_pct = (d.get("f170") or 0) / 100
    high = (d.get("f44") or 0) / 100
    low = (d.get("f45") or 0) / 100
    open_p = (d.get("f46") or 0) / 100
    prev = (d.get("f60") or 0) / 100
    arrow = "↑" if change_pct >= 0 else "↓"
    return (
        f"{name} ({code}) {price:.2f} {arrow}{change_pct:+.2f}%\n"
        f"开 {open_p:.2f} 高 {high:.2f} 低 {low:.2f} 昨 {prev:.2f}"
    )
