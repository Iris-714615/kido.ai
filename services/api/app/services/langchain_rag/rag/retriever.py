"""RAG 检索器：实现任务四的检索闭环。

流程：
    用户输入
      → 敏感词预检（命中直接拒绝）
      → 问题向量化（由 Chroma 内部完成）
      → similarity_search_with_score 检索
      → 结果过滤（相似度阈值 + 敏感词后检）
      → 返回 Top-K context
"""
from __future__ import annotations

from dataclasses import dataclass

from langchain_core.documents import Document

from app.services.langchain_rag.core.vector_store import ChromaVectorStore, DEFAULT_COLLECTION
from app.services.langchain_rag.processors.sensitive_filter import SensitiveFilter


@dataclass
class RetrievalResult:
    """检索结果。"""
    documents: list[Document]
    context: str
    sources: list[str]
    blocked: bool  # 是否因敏感词被拦截
    block_reason: str = ""


class RAGRetriever:
    """RAG 检索器。"""

    def __init__(
        self,
        collection_name: str = DEFAULT_COLLECTION,
        k: int = 5,
        score_threshold: float = 2.0,  # Chroma L2 距离，越小越相似
        store: ChromaVectorStore | None = None,
    ) -> None:
        self.k = k
        self.score_threshold = score_threshold
        self.store = store or ChromaVectorStore.get_instance(collection_name)

    def retrieve(self, query: str) -> RetrievalResult:
        """执行检索闭环。"""
        # 1. 敏感词预检
        hits = SensitiveFilter.scan(query)
        if hits:
            return RetrievalResult(
                documents=[],
                context="",
                sources=[],
                blocked=True,
                block_reason=f"问题包含敏感词：{hits}",
            )

        # 2. 检索（带分数）
        results = self.store.dedup_by_source(
            query, k=self.k, score_threshold=self.score_threshold
        )

        # 3. 敏感词后检：过滤含敏感词的检索块
        clean: list[tuple[Document, float]] = []
        for doc, score in results:
            if not SensitiveFilter.contains(doc.page_content):
                clean.append((doc, score))

        # 4. 组装 context
        documents = [doc for doc, _ in clean]
        context = "\n\n".join(doc.page_content for doc in documents)
        sources = [doc.page_content[:80] + "..." for doc in documents]

        return RetrievalResult(
            documents=documents,
            context=context,
            sources=sources,
            blocked=False,
        )
