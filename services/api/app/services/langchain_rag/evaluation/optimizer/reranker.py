"""检索重排 rerank（优化策略 3）。

对检索返回的文档用 rerank 模型重新打分排序：
1. 主路径：阿里灵积 gte-rerank 模型（HTTP API）
2. 降级路径：用 embedding 余弦相似度近似 rerank
3. 兜底：保持原顺序

rerank 与 embedding 检索的区别：
- embedding 检索是 query-doc 双塔，向量独立编码后比对，速度快但精度一般
- rerank 是 cross-encoder，query 和 doc 拼接后一起编码打分，精度更高
"""
from __future__ import annotations

import logging
import os
from typing import Any

import requests
from langchain_core.documents import Document

logger = logging.getLogger(__name__)


class Reranker:
    """检索重排器。"""

    DASHSCOPE_RERANK_URL = "https://dashscope.aliyuncs.com/api/v1/services/rerank"
    DASHSCOPE_RERANK_MODEL = "gte-rerank"

    def __init__(
        self,
        top_n: int = 5,
        score_threshold: float = 0.3,
        method: str = "auto",
    ) -> None:
        """
        Args:
            top_n: 重排后保留的条数
            score_threshold: 分数阈值，低于此值的丢弃
            method: auto / dashscope / embedding / none
        """
        self.top_n = top_n
        self.score_threshold = score_threshold
        self.method = method

    def rerank(self, query: str, documents: list[Document]) -> list[Document]:
        """对文档列表重排，返回 top_n。"""
        if not documents:
            return []

        method = self._resolve_method()
        if method == "dashscope":
            scored = self._rerank_dashscope(query, documents)
        elif method == "embedding":
            scored = self._rerank_embedding(query, documents)
        else:
            # none：不重排，仅按阈值过滤
            scored = [(d, 1.0) for d in documents]

        # 阈值过滤 + 取 top_n
        filtered = [(d, s) for d, s in scored if s >= self.score_threshold]
        filtered.sort(key=lambda x: x[1], reverse=True)
        result = [d for d, _ in filtered[: self.top_n]]

        logger.info(
            "rerank: query=%s, method=%s, 输入=%d, 过滤后=%d, 输出=%d",
            query, method, len(documents), len(filtered), len(result),
        )
        return result

    def _resolve_method(self) -> str:
        if self.method != "auto":
            return self.method
        # auto：有 API key 用 dashscope，否则降级 embedding
        if os.getenv("DASHSCOPE_API_KEY"):
            return "dashscope"
        return "embedding"

    def _rerank_dashscope(self, query: str, documents: list[Document]) -> list[tuple[Document, float]]:
        """阿里灵积 gte-rerank。"""
        api_key = os.getenv("DASHSCOPE_API_KEY")
        if not api_key:
            logger.warning("无 DASHSCOPE_API_KEY，降级 embedding rerank")
            return self._rerank_embedding(query, documents)

        texts = [d.page_content for d in documents]
        payload = {
            "model": self.DASHSCOPE_RERANK_MODEL,
            "input": {
                "query": query,
                "documents": texts,
            },
            "parameters": {
                "top_n": self.top_n,
                "return_documents": False,
            },
        }
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        try:
            resp = requests.post(self.DASHSCOPE_RERANK_URL, json=payload, headers=headers, timeout=15)
            resp.raise_for_status()
            data = resp.json()
            results = data.get("output", {}).get("results", [])
            scored: list[tuple[Document, float]] = []
            for item in results:
                idx = item.get("index")
                score = item.get("relevance_score", 0.0)
                if idx is not None and 0 <= idx < len(documents):
                    scored.append((documents[idx], float(score)))
            return scored
        except Exception as e:
            logger.warning("dashscope rerank 失败，降级 embedding: %s", e)
            return self._rerank_embedding(query, documents)

    def _rerank_embedding(self, query: str, documents: list[Document]) -> list[tuple[Document, float]]:
        """用 embedding 余弦相似度近似 rerank。"""
        from app.services.langchain_rag.core.embeddings import EmbeddingFactory

        emb = EmbeddingFactory.get_embeddings()
        try:
            q_vec = emb.embed_query(query)
            doc_vecs = emb.embed_documents([d.page_content for d in documents])
        except Exception as e:
            logger.warning("embedding rerank 失败，保持原序: %s", e)
            return [(d, 1.0) for d in documents]

        scored: list[tuple[Document, float]] = []
        for doc, dv in zip(documents, doc_vecs):
            score = self._cosine(q_vec, dv)
            scored.append((doc, score))
        return scored

    @staticmethod
    def _cosine(a: list[float], b: list[float]) -> float:
        dot = sum(x * y for x, y in zip(a, b))
        na = sum(x * x for x in a) ** 0.5
        nb = sum(y * y for y in b) ** 0.5
        if na == 0 or nb == 0:
            return 0.0
        return dot / (na * nb)
