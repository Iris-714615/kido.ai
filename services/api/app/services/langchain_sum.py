"""LangChain RAG 服务模块（薄壳，向下兼容入口）。

实际实现已重构至 `app.services.langchain_rag` 子包，按职责拆分：
- core/        : LLM / 向量化 / Chroma 向量库 / Prompt
- loaders/     : 4 种数据源（DB / 爬虫 / 文档 / 模型蒸馏）
- processors/  : 切割（字符/语义/标题）/ 敏感词过滤 / 清洗
- tools/       : Function Call 工具（探索记录 / 成长统计 / 天气）
- rag/         : 检索器 + RAG+Tool 链编排
- maintenance/ : 异步入库管线 + 定时任务
- evaluation/  : 评估优化板块（指标/测试/诊断 + 优化策略）
- router.py    : FastAPI 路由（兼容原 /deep/* 接口）

此处保证 `main.py` 的 `from app.services.langchain import deep_router` 不变。
"""
from __future__ import annotations

# 向下兼容：转发 deep_router
from app.services.langchain_rag import deep_router

__all__ = ["deep_router"]
