"""Function Call 工具③：查询天气（外部 API，扩展）。

当孩子问「今天天气怎么样」时，LLM 自动调用本工具。
使用 wttr.in 免费 API（无需 key）。
"""
from __future__ import annotations

import json

import requests
from langchain_core.tools import tool


@tool
def query_weather(city: str) -> str:
    """查询指定城市的天气情况。

    Args:
        city: 城市名称，如「北京」「上海」
    Returns:
        天气情况的可读文本
    """
    try:
        # wttr.in 免费 API，JSON 格式
        url = f"https://wttr.in/{city}"
        resp = requests.get(
            url,
            params={"format": "j1"},
            headers={"User-Agent": "curl/7.0"},
            timeout=8,
        )
        resp.raise_for_status()
        data = resp.json()
        current = data.get("current_condition", [{}])[0]
        weather_desc = current.get("lang_zh", [{}])[0].get("value", current.get("weatherDesc", [{}])[0].get("value", ""))
        result = {
            "city": city,
            "temp_c": current.get("temp_C", "?"),
            "feels_like_c": current.get("FeelsLikeC", "?"),
            "humidity": current.get("humidity", "?"),
            "description": weather_desc,
            "wind_speed_kmph": current.get("windspeedKmph", "?"),
        }
        return json.dumps(result, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"city": city, "error": f"天气查询失败: {e}"}, ensure_ascii=False)
