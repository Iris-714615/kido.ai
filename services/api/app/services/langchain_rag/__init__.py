"""LangChain RAG 综合服务模块。

封装 LangChain + Function Call + 多源 RAG 能力，对外暴露：
- deep_router: FastAPI 路由（向下兼容原 /deep/* 接口）
- LLMFactory / EmbeddingFactory / ChromaVectorStore: 核心能力
- 各 loader / processor / tool: 可复用组件
"""
from app.services.langchain_rag.core.embeddings import EmbeddingFactory
from app.services.langchain_rag.core.llm import LLMFactory
from app.services.langchain_rag.core.vector_store import ChromaVectorStore
from app.services.langchain_rag.router import deep_router

__all__ = [
    "deep_router",
    "LLMFactory",
    "EmbeddingFactory",
    "ChromaVectorStore",
]
