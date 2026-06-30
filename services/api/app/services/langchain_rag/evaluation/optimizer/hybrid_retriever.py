"""多路召回 + 混合检索（优化策略 5）。

混合检索 = 向量检索（余弦相似度）+ 分词检索（BM25）
- 向量检索：语义匹配，捕获同义/近义
- BM25 分词检索：关键词精确匹配，捕获专有名词/数字

归一化处理：两路分数各自 min-max 归一化到 [0,1]，再加权融合。
"""
from __future__ import annotations

import logging
import math
from typing import Any

from langchain_core.documents import Document

from app.services.langchain_rag.rag.retriever import RAGRetriever

logger = logging.getLogger(__name__)


class HybridRetriever:
    """混合检索器（向量 + BM25 分词）。"""

    def __init__(
        self,
        vector_weight: float = 0.6,
        bm25_weight: float = 0.4,
        top_k: int = 5,
        vector_k: int = 10,
        bm25_k: int = 10,
    ) -> None:
        """
        Args:
            vector_weight / bm25_weight: 两路权重（归一化后使用）
            top_k: 最终返回条数
            vector_k / bm25_k: 各路召回条数（融合前）
        """
        total = vector_weight + bm25_weight
        self.vector_weight = vector_weight / total
        self.bm25_weight = bm25_weight / total
        self.top_k = top_k
        self.vector_k = vector_k
        self.bm25_k = bm25_k

    def retrieve(self, query: str) -> list[Document]:
        """混合检索：向量 + BM25 融合排序。"""
        # 1. 向量检索
        vector_docs = self._vector_search(query)
        # 2. BM25 分词检索
        bm25_docs = self._bm25_search(query)

        # 3. 融合：归一化 + 加权
        merged = self._fuse(vector_docs, bm25_docs)
        return merged[: self.top_k]

    def _vector_search(self, query: str) -> list[tuple[Document, float]]:
        """向量检索，返回 (doc, score)。"""
        try:
            result = RAGRetriever().retrieve(query, top_k=self.vector_k)
            # RAGRetriever 返回的 documents 已按相似度排序，但未暴露原始分数
            # 这里用排名衰减近似分数（rank 1 分数最高）
            scored = []
            for i, d in enumerate(result.documents):
                score = 1.0 / (i + 1)  # 排名衰减
                scored.append((d, score))
            return scored
        except Exception as e:
            logger.warning("向量检索失败: %s", e)
            return []

    def _bm25_search(self, query: str) -> list[tuple[Document, float]]:
        """BM25 分词检索，返回 (doc, score)。

        从向量库全量加载文档建 BM25 索引（小数据量场景适用）。
        jieba/rank_bm25 缺失时降级为空。
        """
        try:
            import jieba  # type: ignore
            from rank_bm25 import BM25Okapi  # type: ignore
        except ImportError:
            logger.warning("jieba/rank_bm25 未安装，BM25 检索降级跳过")
            return []

        # 从向量库全量加载
        all_docs = self._load_all_docs()
        if not all_docs:
            return []

        # 分词
        tokenized_corpus = [list(jieba.cut(d.page_content)) for d in all_docs]
        bm25 = BM25Okapi(tokenized_corpus)
        tokenized_query = list(jieba.cut(query))
        scores = bm25.get_scores(tokenized_query)

        # 取 top
        ranked = sorted(zip(all_docs, scores), key=lambda x: x[1], reverse=True)
        return [(d, float(s)) for d, s in ranked[: self.bm25_k]]

    def _load_all_docs(self) -> list[Document]:
        """从 Chroma 全量加载文档（用于建 BM25 索引）。"""
        try:
            from app.services.langchain_rag.core.vector_store import ChromaVectorStore
            store = ChromaVectorStore.get_instance("science_kb")._store
            data = store.get(include=["documents", "metadatas"])
            docs: list[Document] = []
            for text, meta in zip(data.get("documents", []), data.get("metadatas", [])):
                docs.append(Document(page_content=text, metadata=meta or {}))
            return docs
        except Exception as e:
            logger.warning("BM25 全量加载失败: %s", e)
            return []

    def _fuse(
        self,
        vector_docs: list[tuple[Document, float]],
        bm25_docs: list[tuple[Document, float]],
    ) -> list[Document]:
        """归一化 + 加权融合。"""
        # 各路 min-max 归一化
        vec_normalized = self._normalize(vector_docs)
        bm25_normalized = self._normalize(bm25_docs)

        # 按 source_id 聚合分数
        score_map: dict[str, float] = {}
        doc_map: dict[str, Document] = {}

        for d, s in vec_normalized:
            sid = d.metadata.get("source_id", d.page_content[:32])
            score_map[sid] = score_map.get(sid, 0.0) + s * self.vector_weight
            doc_map[sid] = d

        for d, s in bm25_normalized:
            sid = d.metadata.get("source_id", d.page_content[:32])
            score_map[sid] = score_map.get(sid, 0.0) + s * self.bm25_weight
            doc_map[sid] = d

        # 排序输出
        ranked = sorted(score_map.items(), key=lambda x: x[1], reverse=True)
        return [doc_map[sid] for sid, _ in ranked]

    @staticmethod
    def _normalize(scored: list[tuple[Document, float]]) -> list[tuple[Document, float]]:
        """min-max 归一化到 [0,1]。"""
        if not scored:
            return []
        scores = [s for _, s in scored]
        lo, hi = min(scores), max(scores)
        rng = hi - lo if hi > lo else 1.0
        return [(d, (s - lo) / rng) for d, s in scored]
