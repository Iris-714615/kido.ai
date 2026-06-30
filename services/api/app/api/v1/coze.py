from __future__ import annotations

import hmac
from datetime import datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.core.settings import get_settings
from app.dependencies import get_db_session
from app.models import ChatMessage, ChatSession, ChildProfile, ExploreRecord, MemoryEvent, MemoryEntity
from app.schemas import (
    CozeChatMessageItem,
    CozeChildProfileResponse,
    CozeExploreRecordItem,
    CozeExploreRecordsResponse,
    CozeMemoryEntityItem,
    CozeMemoryEventItem,
    CozeMemorySummaryResponse,
    CozeRecentChatsResponse,
)

router = APIRouter(prefix="/coze", tags=["coze"])


def authenticate_coze_api_key(api_key: str) -> None:
    settings = get_settings()
    expected = settings.coze_api_key
    if not expected:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Coze API key not configured")
    # 常量时间比较，降低时序攻击风险
    if not hmac.compare_digest(api_key, expected):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API key")


def _require_coze_api_key(x_coze_api_key: Annotated[str, Header(alias="X-Coze-Api-Key")]) -> None:
    authenticate_coze_api_key(x_coze_api_key)


def _get_child_or_404(db: Session, child_id: int) -> ChildProfile:
    """校验 child_id 存在性，统一 404 行为，避免 IDOR 信息泄露。"""
    child = db.get(ChildProfile, child_id)
    if child is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Child not found")
    return child


@router.get("/child/{child_id}/memory-summary", response_model=CozeMemorySummaryResponse)
def get_child_memory_summary(
    child_id: int,
    db: Session = Depends(get_db_session),
    _: None = Depends(_require_coze_api_key),
    limit: int = Query(default=10, ge=1, le=50),
) -> CozeMemorySummaryResponse:
    _get_child_or_404(db, child_id)

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

    return CozeMemorySummaryResponse(
        child_id=child_id,
        events=[
            CozeMemoryEventItem(
                id=event.id,
                event_type=event.event_type,
                source_type=event.source_type,
                source_id=event.source_id,
                payload=event.payload_json,
                created_at=event.created_at,
            )
            for event in events
        ],
        entities=[
            CozeMemoryEntityItem(
                id=entity.id,
                entity_type=entity.entity_type,
                entity_name=entity.entity_name,
                attributes=entity.attributes_json,
                created_at=entity.created_at,
            )
            for entity in entities
        ],
    )


@router.get("/child/{child_id}/recent-chats", response_model=CozeRecentChatsResponse)
def get_child_recent_chats(
    child_id: int,
    db: Session = Depends(get_db_session),
    _: None = Depends(_require_coze_api_key),
    session_id: int | None = None,
    limit: int = Query(default=20, ge=1, le=100),
) -> CozeRecentChatsResponse:
    _get_child_or_404(db, child_id)

    if session_id is not None:
        # 校验 session 归属该 child，防止跨儿童读取聊天记录
        session = db.get(ChatSession, session_id)
        if session is None or session.child_id != child_id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Chat session not found")
        messages = (
            db.scalars(
                select(ChatMessage)
                .where(ChatMessage.session_id == session_id)
                .order_by(desc(ChatMessage.id))
                .limit(limit)
            )
            .all()
        )
    else:
        subq = (
            select(ChatSession.id)
            .where(ChatSession.child_id == child_id)
            .order_by(desc(ChatSession.id))
            .limit(5)
            .subquery()
        )
        messages = (
            db.scalars(
                select(ChatMessage)
                .where(ChatMessage.session_id.in_(subq))
                .order_by(desc(ChatMessage.id))
                .limit(limit)
            )
            .all()
        )

    return CozeRecentChatsResponse(
        child_id=child_id,
        messages=[
            CozeChatMessageItem(
                id=msg.id,
                session_id=msg.session_id,
                role=msg.role,
                content=msg.content,
                metadata=msg.metadata_json,
                created_at=msg.created_at,
            )
            for msg in reversed(messages)
        ],
    )


@router.get("/child/{child_id}/explore-records", response_model=CozeExploreRecordsResponse)
def get_child_explore_records(
    child_id: int,
    db: Session = Depends(get_db_session),
    _: None = Depends(_require_coze_api_key),
    days: int = Query(default=7, ge=1, le=30),
    limit: int = Query(default=20, ge=1, le=100),
) -> CozeExploreRecordsResponse:
    _get_child_or_404(db, child_id)

    # 统一使用 naive UTC，避免与 SQLite 存储的 naive datetime 比较时区不一致
    cutoff_date = datetime.utcnow() - timedelta(days=days)

    records = (
        db.scalars(
            select(ExploreRecord)
            .where(ExploreRecord.child_id == child_id)
            .where(ExploreRecord.created_at >= cutoff_date)
            .order_by(desc(ExploreRecord.id))
            .limit(limit)
        )
        .all()
    )

    return CozeExploreRecordsResponse(
        child_id=child_id,
        records=[
            CozeExploreRecordItem(
                id=record.id,
                media_type=record.media_type,
                file_name=record.file_name,
                file_url=record.file_url,
                object_name=record.object_name,
                scientific_fact=record.scientific_fact,
                growth_dimension=record.growth_dimension,
                score_delta=record.score_delta,
                analysis=record.analysis_json,
                created_at=record.created_at,
            )
            for record in records
        ],
    )


@router.get("/child/{child_id}/profile", response_model=CozeChildProfileResponse)
def get_child_profile(
    child_id: int,
    db: Session = Depends(get_db_session),
    _: None = Depends(_require_coze_api_key),
) -> CozeChildProfileResponse:
    child = _get_child_or_404(db, child_id)

    return CozeChildProfileResponse(
        id=child.id,
        nickname=child.nickname,
        age=child.age,
        current_level=child.current_level,
        token_balance=child.token_balance,
        created_at=child.created_at,
        updated_at=child.updated_at,
    )
