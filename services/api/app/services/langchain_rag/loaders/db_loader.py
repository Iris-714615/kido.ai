"""数据源①：项目数据（MySQL / Redis / ES）。

数据结构完整，免处理，直接转 Document 入库。
- MySQL：通过 SQLAlchemy 查 explore_records / memory_entities 等
- Redis：读取缓存中的热点科普摘要
- ES：预留接口（可选）
"""
from __future__ import annotations

import json
from typing import Any

from langchain_core.documents import Document
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import ExploreRecord, MemoryEntity


class DBLoader:
    """项目数据库加载器。"""

    def __init__(self, db: Session) -> None:
        self.db = db

    # ---------- MySQL ----------
    def load_explore_records(self, limit: int = 200) -> list[Document]:
        """加载探索记录作为知识库（孩子发现的物体 + 科学事实）。"""
        rows = self.db.scalars(
            select(ExploreRecord).order_by(ExploreRecord.created_at.desc()).limit(limit)
        ).all()
        docs: list[Document] = []
        for r in rows:
            content = (
                f"孩子发现了「{r.object_name}」。\n"
                f"科学事实：{r.scientific_fact}\n"
                f"成长维度：{r.growth_dimension}"
            )
            docs.append(Document(
                page_content=content,
                metadata={
                    "source": "mysql.explore_records",
                    "source_id": f"explore_{r.id}",
                    "object_name": r.object_name,
                    "growth_dimension": r.growth_dimension,
                },
            ))
        return docs

    def load_memory_entities(self, limit: int = 200) -> list[Document]:
        """加载记忆实体作为知识库（孩子兴趣画像）。"""
        rows = self.db.scalars(
            select(MemoryEntity).order_by(MemoryEntity.created_at.desc()).limit(limit)
        ).all()
        docs: list[Document] = []
        for r in rows:
            attrs = r.attributes_json or {}
            content = f"孩子感兴趣的{r.entity_type}：{r.entity_name}。属性：{json.dumps(attrs, ensure_ascii=False)}"
            docs.append(Document(
                page_content=content,
                metadata={
                    "source": "mysql.memory_entities",
                    "source_id": f"entity_{r.id}",
                    "entity_type": r.entity_type,
                },
            ))
        return docs

    def load_all(self, limit: int = 200) -> list[Document]:
        """加载全部项目数据源。"""
        return self.load_explore_records(limit) + self.load_memory_entities(limit)

    # ---------- Redis ----------
    def load_from_redis(self, key_pattern: str = "kidoai:kb:*") -> list[Document]:
        """从 Redis 读取热点科普摘要（结构完整，直接转 Document）。

        需要 redis-py，若未配置则跳过。
        """
        try:
            import redis
            from app.core.settings import get_settings

            settings = get_settings()
            client = redis.from_url(settings.redis_url, decode_responses=True)
            docs: list[Document] = []
            for key in client.scan_iter(key_pattern):
                value = client.get(key)
                if not value:
                    continue
                docs.append(Document(
                    page_content=value,
                    metadata={
                        "source": "redis",
                        "source_id": key,
                    },
                ))
            return docs
        except Exception:
            # Redis 未配置或不可达，返回空
            return []

    # ---------- ES（预留） ----------
    def load_from_es(self, index: str = "kidoai_kb", query: dict | None = None) -> list[Document]:
        """从 Elasticsearch 读取（预留接口，需安装 elasticsearch 客户端）。"""
        return []
