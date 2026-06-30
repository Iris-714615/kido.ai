"""Function Call 工具②：查询孩子成长统计。

当孩子问「我探索了多少次」「我的成长数据」时，
LLM 自动调用本工具从 MySQL 聚合查询统计数据。
"""
from __future__ import annotations

import json

from langchain_core.tools import tool
from sqlalchemy import func, select

from app.db.session import SessionLocal
from app.models import ChatMessage, ChatSession, ExploreRecord, MemoryEntity, MemoryEvent


@tool
def query_growth_stats(child_id: int) -> str:
    """查询孩子的成长统计数据（探索次数/积分/聊天/记忆）。

    Args:
        child_id: 孩子 ID
    Returns:
        成长统计的可读文本
    """
    db = SessionLocal()
    try:
        total_explore = db.scalar(
            select(func.count(ExploreRecord.id)).where(ExploreRecord.child_id == child_id)
        ) or 0
        total_tokens = db.scalar(
            select(func.coalesce(func.sum(ExploreRecord.score_delta), 0))
            .where(ExploreRecord.child_id == child_id)
        ) or 0
        total_chat = db.scalar(
            select(func.count(ChatSession.id)).where(ChatSession.child_id == child_id)
        ) or 0
        total_memory_events = db.scalar(
            select(func.count(MemoryEvent.id)).where(MemoryEvent.child_id == child_id)
        ) or 0
        total_memory_entities = db.scalar(
            select(func.count(MemoryEntity.id)).where(MemoryEntity.child_id == child_id)
        ) or 0

        # 维度分布
        dim_rows = db.execute(
            select(ExploreRecord.growth_dimension, func.count(ExploreRecord.id))
            .where(ExploreRecord.child_id == child_id)
            .group_by(ExploreRecord.growth_dimension)
        ).all()
        dimensions = {dim: cnt for dim, cnt in dim_rows}

        stats = {
            "total_explore": int(total_explore),
            "total_tokens": int(total_tokens),
            "total_chat_sessions": int(total_chat),
            "total_memory_events": int(total_memory_events),
            "total_memory_entities": int(total_memory_entities),
            "dimension_distribution": dimensions,
        }
        return json.dumps(stats, ensure_ascii=False)
    finally:
        db.close()
