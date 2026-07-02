"""兼容薄壳：转发至 langchain_rag.router.deep_router。

历史原因：早期模块名为 ``app.services.langchain``，后重构迁入
``app.services.langchain_rag`` 包。此处保留旧导入路径，避免破坏既有引用。
"""
from app.services.langchain_rag.router import deep_router

__all__ = ["deep_router"]
