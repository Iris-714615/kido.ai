from __future__ import annotations

import re
from typing import Iterable

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.models import ChatMessage, ChatSession, ExploreRecord, MemoryEntity, MemoryEvent, ChildProfile


TOKEN_CANDIDATES = [
    "猫",
    "狗",
    "鸟",
    "汽车",
    "车",
    "树",
    "花",
    "天空",
    "星星",
    "月亮",
    "太阳",
    "书",
    "字",
    "颜色",
    "形状",
    "声音",
    "为什么",
    "怎么",
]


def _append_event(
    db: Session,
    *,
    child_id: int,
    source_type: str,
    source_id: int | None,
    event_type: str,
    payload_json: dict,
) -> MemoryEvent:
    event = MemoryEvent(
        child_id=child_id,
        source_type=source_type,
        source_id=source_id,
        event_type=event_type,
        payload_json=payload_json,
    )
    db.add(event)
    return event


def _append_entity(
    db: Session,
    *,
    child_id: int,
    entity_type: str,
    entity_name: str,
    attributes_json: dict,
) -> MemoryEntity:
    entity = MemoryEntity(
        child_id=child_id,
        entity_type=entity_type,
        entity_name=entity_name,
        attributes_json=attributes_json,
    )
    db.add(entity)
    return entity


def record_explore_memory(db: Session, child: ChildProfile, record: ExploreRecord) -> list[MemoryEvent]:
    event = _append_event(
        db,
        child_id=child.id,
        source_type="explore",
        source_id=record.id,
        event_type="explore.recorded",
        payload_json={
            "object_name": record.object_name,
            "scientific_fact": record.scientific_fact,
            "growth_dimension": record.growth_dimension,
            "score_delta": record.score_delta,
            "file_url": record.file_url,
        },
    )
    _append_entity(
        db,
        child_id=child.id,
        entity_type="object",
        entity_name=record.object_name,
        attributes_json={
            "source": "explore",
            "record_id": record.id,
            "dimension": record.growth_dimension,
        },
    )
    _append_entity(
        db,
        child_id=child.id,
        entity_type="knowledge",
        entity_name=record.growth_dimension,
        attributes_json={
            "source": "explore",
            "record_id": record.id,
            "fact": record.scientific_fact,
        },
    )
    return [event]


def _extract_keywords(text: str) -> list[str]:
    found = [candidate for candidate in TOKEN_CANDIDATES if candidate in text]
    if found:
        return list(dict.fromkeys(found))
    matches = [token for token in re.findall(r"[\u4e00-\u9fff]{2,6}", text) if len(token) >= 2]
    return matches[:5]


def record_chat_memory(
    db: Session,
    *,
    child: ChildProfile,
    session: ChatSession,
    user_message: str,
    assistant_message: str,
) -> list[MemoryEvent]:
    entities = _extract_keywords(user_message + " " + assistant_message)
    events = [
        _append_event(
            db,
            child_id=child.id,
            source_type="chat",
            source_id=session.id,
            event_type="chat.user_message",
            payload_json={"content": user_message, "session_id": session.id},
        ),
        _append_event(
            db,
            child_id=child.id,
            source_type="chat",
            source_id=session.id,
            event_type="chat.assistant_message",
            payload_json={"content": assistant_message, "session_id": session.id},
        ),
    ]
    for entity_name in entities:
        _append_entity(
            db,
            child_id=child.id,
            entity_type="topic",
            entity_name=entity_name,
            attributes_json={"source": "chat", "session_id": session.id},
        )
    return events


def build_memory_summary(db: Session, child_id: int, limit: int = 5) -> dict[str, list]:
    events = (
        db.scalars(
            select(MemoryEvent)
            .where(MemoryEvent.child_id == child_id)
            .order_by(desc(MemoryEvent.id))
            .limit(limit)
        )
        .all()
    )
    entities = (
        db.scalars(
            select(MemoryEntity)
            .where(MemoryEntity.child_id == child_id)
            .order_by(desc(MemoryEntity.id))
            .limit(limit)
        )
        .all()
    )
    return {"events": events, "entities": entities}


def build_memory_text(db: Session, child_id: int, limit: int = 5) -> str:
    summary = build_memory_summary(db, child_id=child_id, limit=limit)
    lines: list[str] = []
    for event in reversed(summary["events"]):
        if event.event_type == "explore.recorded":
            payload = event.payload_json
            lines.append(
                f"最近一次探索：看到了{payload.get('object_name')}，"
                f"属于{payload.get('growth_dimension')}，得到了{payload.get('score_delta')}分。"
            )
        elif event.event_type == "chat.user_message":
            lines.append(f"刚才你说：{event.payload_json.get('content')}")
    for entity in reversed(summary["entities"]):
        lines.append(f"记忆实体：{entity.entity_type} / {entity.entity_name}")
    return "\n".join(lines) if lines else "还没有可用的长期记忆。"


def list_chat_messages(db: Session, session_id: int, limit: int = 20) -> list[ChatMessage]:
    return (
        db.scalars(
            select(ChatMessage)
            .where(ChatMessage.session_id == session_id)
            .order_by(desc(ChatMessage.id))
            .limit(limit)
        )
        .all()[::-1]
    )

