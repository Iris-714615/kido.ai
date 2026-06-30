"""Function Call 工具集（任务二）。

至少两种工具：
1. query_explore_records: 查询孩子探索记录（MySQL）
2. query_growth_stats: 查询孩子成长统计（MySQL 聚合）
3. query_weather: 查询天气（外部 API，扩展）
"""
from app.services.langchain_rag.tools.explore_tool import query_explore_records
from app.services.langchain_rag.tools.growth_tool import query_growth_stats
from app.services.langchain_rag.tools.weather_tool import query_weather

ALL_TOOLS = [query_explore_records, query_growth_stats, query_weather]

__all__ = ["query_explore_records", "query_growth_stats", "query_weather", "ALL_TOOLS"]
