"""孩子画像构建服务。

从 memory_events / memory_entities / explore_records 聚类分析，
生成结构化的孩子兴趣画像，供成长报告 LLM 分析使用。
"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import ChatMessage, ChatSession, ExploreRecord, MemoryEntity, MemoryEvent


def build_child_profile(db: Session, child_id: int) -> dict:
    """构建孩子结构化画像。

    返回结构：
    {
        "interests": [{"name": "猫", "type": "object", "count": 5}, ...],
        "knowledge_domains": [{"domain": "SCIENCE", "count": 8}, ...],
        "chat_topics": [{"topic": "为什么", "count": 3}, ...],
        "behavior": {
            "total_explore": 12,
            "total_chat_messages": 8,
            "question_ratio": 0.4,
        },
    }
    """
    # 1. 兴趣实体聚类（按 entity_name 分组计数，取 Top10）
    entity_rows = db.execute(
        select(
            MemoryEntity.entity_name,
            MemoryEntity.entity_type,
            func.count(MemoryEntity.id),
        )
        .where(MemoryEntity.child_id == child_id)
        .group_by(MemoryEntity.entity_name, MemoryEntity.entity_type)
        .order_by(func.count(MemoryEntity.id).desc())
        .limit(10)
    ).all()
    interests = [
        {"name": row[0], "type": row[1], "count": row[2]}
        for row in entity_rows
    ]

    # 2. 知识领域分布（从 explore_records 的 growth_dimension）
    dim_rows = db.execute(
        select(
            ExploreRecord.growth_dimension,
            func.count(ExploreRecord.id),
        )
        .where(ExploreRecord.child_id == child_id)
        .group_by(ExploreRecord.growth_dimension)
    ).all()
    knowledge_domains = [{"domain": r[0], "count": r[1]} for r in dim_rows]

    # 3. 聊天话题（从 memory_entities where type=topic）
    topic_rows = db.execute(
        select(MemoryEntity.entity_name, func.count(MemoryEntity.id))
        .where(
            MemoryEntity.child_id == child_id,
            MemoryEntity.entity_type == "topic",
        )
        .group_by(MemoryEntity.entity_name)
        .order_by(func.count(MemoryEntity.id).desc())
        .limit(5)
    ).all()
    chat_topics = [{"topic": r[0], "count": r[1]} for r in topic_rows]

    # 4. 行为统计
    total_explore = db.scalar(
        select(func.count(ExploreRecord.id)).where(ExploreRecord.child_id == child_id)
    ) or 0
    total_chat_messages = db.scalar(
        select(func.count(ChatMessage.id))
        .join(ChatSession, ChatMessage.session_id == ChatSession.id)
        .where(ChatSession.child_id == child_id)
    ) or 0

    # 提问占比：从 chat user_message 中含疑问词的比例
    question_hints = ("为什么", "怎么", "怎样", "什么", "哪里", "谁", "多少", "?", "？")
    question_count = 0
    if total_chat_messages > 0:
        user_messages = db.scalars(
            select(ChatMessage.content)
            .join(ChatSession, ChatMessage.session_id == ChatSession.id)
            .where(
                ChatSession.child_id == child_id,
                ChatMessage.role == "user",
            )
        ).all()
        user_total = len(user_messages)
        if user_total > 0:
            question_count = sum(
                1 for m in user_messages if any(h in m for h in question_hints)
            )
            question_ratio = round(question_count / user_total, 2)
        else:
            question_ratio = 0.0
    else:
        question_ratio = 0.0

    return {
        "interests": interests,
        "knowledge_domains": knowledge_domains,
        "chat_topics": chat_topics,
        "behavior": {
            "total_explore": total_explore,
            "total_chat_messages": total_chat_messages,
            "question_count": question_count,
            "question_ratio": question_ratio,
        },
    }
