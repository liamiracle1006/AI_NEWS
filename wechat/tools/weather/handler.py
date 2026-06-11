# encoding:utf-8
"""天气查询——open-meteo 免 key，先 geocode 找城市坐标再查天气。"""
from __future__ import annotations

import logging
from typing import Optional

import requests

logger = logging.getLogger(__name__)

TOOL_NAME = "weather"
TRIGGER_KEYWORDS = ("天气", "weather")

_GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"
_FORECAST_URL = "https://api.open-meteo.com/v1/forecast"

_WMO_DESC = {
    0: "晴", 1: "晴", 2: "多云", 3: "阴",
    45: "雾", 48: "雾凇",
    51: "毛毛雨", 53: "毛毛雨", 55: "毛毛雨",
    56: "冻毛毛雨", 57: "冻毛毛雨",
    61: "小雨", 63: "中雨", 65: "大雨",
    66: "冻雨", 67: "冻雨",
    71: "小雪", 73: "中雪", 75: "大雪",
    77: "霰",
    80: "阵雨", 81: "强阵雨", 82: "暴阵雨",
    85: "阵雪", 86: "强阵雪",
    95: "雷暴", 96: "雷暴+冰雹", 99: "雷暴+冰雹",
}


def _extract_city(text: str) -> str:
    """从触发文本里抽城市名。"""
    rest = text
    for kw in TRIGGER_KEYWORDS:
        if kw in rest:
            rest = rest.replace(kw, "", 1).strip()
            break
    # 去掉常见前后缀
    for junk in ("的", "今天", "现在", "现在的", "查", "问"):
        rest = rest.replace(junk, "").strip()
    return rest or "上海"  # 默认上海


def _geocode(city: str) -> Optional[tuple[float, float, str]]:
    """城市名 → (lat, lon, display_name)。失败 None。"""
    try:
        r = requests.get(_GEOCODE_URL,
                         params={"name": city, "count": 1, "language": "zh"},
                         timeout=5)
        r.raise_for_status()
        results = (r.json() or {}).get("results") or []
        if not results:
            return None
        loc = results[0]
        display = f"{loc.get('name', city)}"
        if loc.get("country"):
            display += f"·{loc['country']}"
        return loc["latitude"], loc["longitude"], display
    except Exception as e:
        logger.warning(f"[weather] geocode failed for {city!r}: {e}")
        return None


def _format_weather(d: dict, display: str) -> str:
    """组装人话天气描述。"""
    cur = d.get("current") or {}
    temp = cur.get("temperature_2m")
    feels = cur.get("apparent_temperature")
    code = cur.get("weather_code", 0)
    humidity = cur.get("relative_humidity_2m")
    wind = cur.get("wind_speed_10m")
    desc = _WMO_DESC.get(code, "天气未知")
    parts = [f"{display}：{desc}"]
    if temp is not None:
        parts.append(f"{temp:.0f}°C")
    if feels is not None and feels != temp:
        parts.append(f"体感 {feels:.0f}°C")
    if humidity is not None:
        parts.append(f"湿度 {humidity:.0f}%")
    if wind is not None:
        parts.append(f"风速 {wind:.1f}m/s")
    return "，".join(parts) + "。"


def handle(text: str, ctx) -> str:
    city = _extract_city(text)
    geo = _geocode(city)
    if geo is None:
        return f"找不到『{city}』这个地方，换个写法试试？"
    lat, lon, display = geo
    try:
        r = requests.get(
            _FORECAST_URL,
            params={
                "latitude": lat, "longitude": lon,
                "current": "temperature_2m,apparent_temperature,weather_code,"
                           "relative_humidity_2m,wind_speed_10m",
                "timezone": "auto",
            },
            timeout=5,
        )
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        return f"查天气挂了：{type(e).__name__}"
    return _format_weather(data, display)
