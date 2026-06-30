"""Chroma 向量库封装：持久化 + 多 collection 隔离 + 元数据去重。

借鉴 kidoai.md 案例：同一 source 的多个 chunk 通过唯一 source_id 去重，
保留最小距离（最优匹配片段）。
"""
from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

from langchain_chroma import Chroma
from langchain_core.documents import Document

from app.core.settings import get_settings
from app.services.langchain_rag.core.embeddings import EmbeddingFactory

# Chroma 持久化目录（项目根下 data/chroma_db）
_DEFAULT_PERSIST_DIR = Path(__file__).resolve().parents[5] / "data" / "chroma_db"

# 默认科普知识库 collection
DEFAULT_COLLECTION = "science_kb"

# 全局 collection 单例缓存（线程安全）
_store_cache: dict[str, ChromaVectorStore] = {}
_cache_lock = threading.Lock()


class ChromaVectorStore:
    """单个 collection 的 Chroma 封装。

    Args:
        collection_name: collection 名称，不同业务用不同 collection 隔离
        persist_dir: 持久化目录
        embedding_provider: 向量模型 provider
    """

    def __init__(
        self,
        collection_name: str = DEFAULT_COLLECTION,
        persist_dir: str | Path | None = None,
        embedding_provider: str = "lingji",
    ) -> None:
        self.collection_name = collection_name
        self.persist_dir = Path(persist_dir) if persist_dir else _DEFAULT_PERSIST_DIR
        self.persist_dir.mkdir(parents=True, exist_ok=True)
        self._embeddings = EmbeddingFactory.get(embedding_provider)
        self._store = Chroma(
            collection_name=collection_name,
            embedding_function=self._embeddings,
            persist_directory=str(self.persist_dir),
        )

    @classmethod
    def get_instance(
        cls,
        collection_name: str = DEFAULT_COLLECTION,
        embedding_provider: str = "lingji",
    ) -> "ChromaVectorStore":
        """获取（或创建）指定 collection 的单例。"""
        cache_key = f"{collection_name}::{embedding_provider}"
        if cache_key in _store_cache:
            return _store_cache[cache_key]
        with _cache_lock:
            if cache_key not in _store_cache:
                _store_cache[cache_key] = cls(
                    collection_name=collection_name,
                    embedding_provider=embedding_provider,
                )
            return _store_cache[cache_key]

    def add_documents(
        self,
        documents: list[Document],
        ids: list[str] | None = None,
    ) -> list[str]:
        """写入文档块。若提供 ids 则按 id 去重（同 id 覆盖）。"""
        if not documents:
            return []
        return self._store.add_documents(documents, ids=ids)

    def similarity_search(self, query: str, k: int = 3, filter: dict | None = None) -> list[Document]:
        """相似度检索（不带分数）。"""
        return self._store.similarity_search(query, k=k, filter=filter)

    def similarity_search_with_score(
        self, query: str, k: int = 5, filter: dict | None = None
    ) -> list[tuple[Document, float]]:
        """相似度检索（带分数，分数越小越相似 / Chroma 默认 L2 距离）。"""
        return self._store.similarity_search_with_score(query, k=k, filter=filter)

    def dedup_by_source(
        self, query: str, k: int = 10, score_threshold: float | None = None
    ) -> list[tuple[Document, float]]:
        """按 source_id 元数据去重检索（借鉴案例 candidate_map 思路）。

        Args:
            k: 初检数量
            score_threshold: 相似度距离阈值，大于该值则丢弃（越小越相似）
        """
        raw = self.similarity_search_with_score(query, k=k)
        best: dict[str, tuple[Document, float]] = {}
        for doc, score in raw:
            source_id = doc.metadata.get("source_id") or doc.metadata.get("source") or id(doc)
            if score_threshold is not None and score > score_threshold:
                continue
            if source_id not in best or score < best[source_id][1]:
                best[source_id] = (doc, score)
        # 按距离升序
        return sorted(best.values(), key=lambda x: x[1])

    def count(self) -> int:
        """当前 collection 文档数。"""
        try:
            return self._store._collection.count()
        except Exception:
            return 0

    def reset(self) -> None:
        """清空当前 collection（谨慎使用）。"""
        try:
            self._store._collection.delete(where={})
        except Exception:
            pass
