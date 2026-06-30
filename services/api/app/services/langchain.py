"""LangChain RAG 服务模块（薄壳，向下兼容入口）。

实际实现已重构至 `app.services.langchain_rag` 子包。
此处保证 `main.py` 的 `from app.services.langchain import deep_router` 不变。
"""
from __future__ import annotations

from app.services.langchain_rag import deep_router

__all__ = ["deep_router"]
