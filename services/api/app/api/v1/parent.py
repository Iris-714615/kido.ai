from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.security import hash_password
from app.core.settings import get_settings
from app.dependencies import get_current_parent, get_db_session, get_parent_child_or_404
from app.models import (
    ChatMessage,
    ChatSession,
    ChildProfile,
    ExploreRecord,
    MemoryEntity,
    MemoryEvent,
    User,
    UserRole,
)
from app.schemas import (
    ChatMessagePublic,
    ChatSessionPublic,
    ChildProfilePublic,
    ExploreRecordPublic,
    GrowthReportResponse,
    MemoryEntityPublic,
    MemoryEventPublic,
    MemorySummaryResponse,
    ParentChildSummary,
    ParentCreateChildRequest,
    ParentReportDimension,
    ParentReportResponse,
)

router = APIRouter(prefix="/parent", tags=["parent"])


@router.post("/children", response_model=ChildProfilePublic, status_code=status.HTTP_201_CREATED)
def create_child(
    payload: ParentCreateChildRequest,
    current_parent: User = Depends(get_current_parent),
    db: Session = Depends(get_db_session),
) -> ChildProfilePublic:
    """家长创建儿童子账号，自动绑定 parent_user_id。"""
    settings = get_settings()
    existing = db.scalar(select(User).where(User.username == payload.username))
    if existing is not None:
        raise HTTPException(status_code=409, detail="Username already exists")

    child_user = User(
        username=payload.username,
        password_hash=hash_password(payload.password, settings.secret_key),
        role=UserRole.CHILD,
    )
    db.add(child_user)
    db.flush()

    child_profile = ChildProfile(
        user_id=child_user.id,
        parent_user_id=current_parent.id,
        nickname=payload.nickname,
        age=payload.age,
        current_level=1,
        token_balance=1000,
    )
    db.add(child_profile)
    db.commit()
    db.refresh(child_profile)
    return ChildProfilePublic.model_validate(child_profile)


@router.get("/children", response_model=list[ParentChildSummary])
def list_children(
    current_parent: User = Depends(get_current_parent),
    db: Session = Depends(get_db_session),
) -> list[ParentChildSummary]:
    """列出当前家长绑定的所有儿童，附带统计。"""
    children = db.scalars(
        select(ChildProfile).where(ChildProfile.parent_user_id == current_parent.id)
    ).all()

    result: list[ParentChildSummary] = []
    for child in children:
        explore_count = db.scalar(
            select(func.count(ExploreRecord.id)).where(ExploreRecord.child_id == child.id)
        ) or 0
        chat_session_count = db.scalar(
            select(func.count(ChatSession.id)).where(ChatSession.child_id == child.id)
        ) or 0
        memory_entity_count = db.scalar(
            select(func.count(MemoryEntity.id)).where(MemoryEntity.child_id == child.id)
        ) or 0
        last_active_at = db.scalar(
            select(func.max(ChatSession.last_message_at)).where(ChatSession.child_id == child.id)
        )
        result.append(
            ParentChildSummary(
                id=child.id,
                nickname=child.nickname,
                age=child.age,
                current_level=child.current_level,
                token_balance=child.token_balance,
                explore_count=explore_count,
                chat_session_count=chat_session_count,
                memory_entity_count=memory_entity_count,
                last_active_at=last_active_at,
                created_at=child.created_at,
            )
        )
    return result


@router.get("/children/{child_id}/explore-records", response_model=list[ExploreRecordPublic])
def list_child_explore(
    child: ChildProfile = Depends(get_parent_child_or_404),
    db: Session = Depends(get_db_session),
    limit: int = 50,
) -> list[ExploreRecordPublic]:
    records = db.scalars(
        select(ExploreRecord)
        .where(ExploreRecord.child_id == child.id)
        .order_by(ExploreRecord.created_at.desc())
        .limit(limit)
    ).all()
    return [ExploreRecordPublic.model_validate(r) for r in records]


@router.get("/children/{child_id}/chat-sessions", response_model=list[ChatSessionPublic])
def list_child_sessions(
    child: ChildProfile = Depends(get_parent_child_or_404),
    db: Session = Depends(get_db_session),
    limit: int = 50,
) -> list[ChatSessionPublic]:
    sessions = db.scalars(
        select(ChatSession)
        .where(ChatSession.child_id == child.id)
        .order_by(ChatSession.created_at.desc())
        .limit(limit)
    ).all()
    return [ChatSessionPublic.model_validate(s) for s in sessions]


@router.get(
    "/children/{child_id}/chat-sessions/{session_id}/messages",
    response_model=list[ChatMessagePublic],
)
def list_child_messages(
    session_id: int,
    child: ChildProfile = Depends(get_parent_child_or_404),
    db: Session = Depends(get_db_session),
) -> list[ChatMessagePublic]:
    session = db.get(ChatSession, session_id)
    if session is None or session.child_id != child.id:
        raise HTTPException(status_code=404, detail="Session not found")
    messages = db.scalars(
        select(ChatMessage)
        .where(ChatMessage.session_id == session_id)
        .order_by(ChatMessage.created_at.asc())
    ).all()
    return [ChatMessagePublic.model_validate(m) for m in messages]


@router.get("/children/{child_id}/memory/summary", response_model=MemorySummaryResponse)
def child_memory_summary(
    child: ChildProfile = Depends(get_parent_child_or_404),
    db: Session = Depends(get_db_session),
    limit: int = 50,
) -> MemorySummaryResponse:
    events = db.scalars(
        select(MemoryEvent)
        .where(MemoryEvent.child_id == child.id)
        .order_by(MemoryEvent.created_at.desc())
        .limit(limit)
    ).all()
    entities = db.scalars(
        select(MemoryEntity)
        .where(MemoryEntity.child_id == child.id)
        .order_by(MemoryEntity.created_at.desc())
        .limit(limit)
    ).all()
    return MemorySummaryResponse(
        events=[MemoryEventPublic.model_validate(e) for e in events],
        entities=[MemoryEntityPublic.model_validate(en) for en in entities],
    )


@router.get("/children/{child_id}/report", response_model=ParentReportResponse)
def child_report(
    child: ChildProfile = Depends(get_parent_child_or_404),
    db: Session = Depends(get_db_session),
) -> ParentReportResponse:
    """成长报告：统计探索/聊天/记忆数据 + 维度分布 + 近期记录。"""
    total_explore = db.scalar(
        select(func.count(ExploreRecord.id)).where(ExploreRecord.child_id == child.id)
    ) or 0
    total_chat_sessions = db.scalar(
        select(func.count(ChatSession.id)).where(ChatSession.child_id == child.id)
    ) or 0
    total_chat_messages = db.scalar(
        select(func.count(ChatMessage.id))
        .join(ChatSession, ChatMessage.session_id == ChatSession.id)
        .where(ChatSession.child_id == child.id)
    ) or 0
    total_memory_events = db.scalar(
        select(func.count(MemoryEvent.id)).where(MemoryEvent.child_id == child.id)
    ) or 0
    total_memory_entities = db.scalar(
        select(func.count(MemoryEntity.id)).where(MemoryEntity.child_id == child.id)
    ) or 0
    total_tokens_earned = db.scalar(
        select(func.coalesce(func.sum(ExploreRecord.score_delta), 0)).where(
            ExploreRecord.child_id == child.id
        )
    ) or 0

    # 维度分布
    dim_rows = db.execute(
        select(
            ExploreRecord.growth_dimension,
            func.count(ExploreRecord.id),
            func.coalesce(func.sum(ExploreRecord.score_delta), 0),
        )
        .where(ExploreRecord.child_id == child.id)
        .group_by(ExploreRecord.growth_dimension)
    ).all()
    dimensions = [
        ParentReportDimension(dimension=row[0], count=row[1], total_score=row[2])
        for row in dim_rows
    ]

    recent_explore_rows = db.scalars(
        select(ExploreRecord)
        .where(ExploreRecord.child_id == child.id)
        .order_by(ExploreRecord.created_at.desc())
        .limit(5)
    ).all()
    recent_chat_rows = db.scalars(
        select(ChatSession)
        .where(ChatSession.child_id == child.id)
        .order_by(ChatSession.created_at.desc())
        .limit(5)
    ).all()

    return ParentReportResponse(
        child_id=child.id,
        nickname=child.nickname,
        total_explore=total_explore,
        total_chat_sessions=total_chat_sessions,
        total_chat_messages=total_chat_messages,
        total_memory_events=total_memory_events,
        total_memory_entities=total_memory_entities,
        total_tokens_earned=total_tokens_earned,
        dimensions=dimensions,
        recent_explore=[ExploreRecordPublic.model_validate(r) for r in recent_explore_rows],
        recent_chat_titles=[ChatSessionPublic.model_validate(s) for s in recent_chat_rows],
    )


@router.get("/children/{child_id}/report/ai", response_model=GrowthReportResponse)
async def child_ai_report(
    child: ChildProfile = Depends(get_parent_child_or_404),
    db: Session = Depends(get_db_session),
) -> GrowthReportResponse:
    """AI 成长报告：统计数据 + Memory 画像 + LLM 分析（LangChain + DeepSeek）。

    流程：数据采集 → Memory 画像 → Prompt 组装 → LLM 生成 → 缓存。
    报告按天缓存，当天有新数据才重新生成。
    """
    from app.services.report import generate_report

    report = await generate_report(db, child)

    # 组装维度分布
    dim_rows = db.execute(
        select(
            ExploreRecord.growth_dimension,
            func.count(ExploreRecord.id),
            func.coalesce(func.sum(ExploreRecord.score_delta), 0),
        )
        .where(ExploreRecord.child_id == child.id)
        .group_by(ExploreRecord.growth_dimension)
    ).all()
    dimensions = [
        ParentReportDimension(dimension=row[0], count=row[1], total_score=row[2])
        for row in dim_rows
    ]

    recent_explore_rows = db.scalars(
        select(ExploreRecord)
        .where(ExploreRecord.child_id == child.id)
        .order_by(ExploreRecord.created_at.desc())
        .limit(5)
    ).all()
    recent_chat_rows = db.scalars(
        select(ChatSession)
        .where(ChatSession.child_id == child.id)
        .order_by(ChatSession.created_at.desc())
        .limit(5)
    ).all()

    return GrowthReportResponse(
        child_id=child.id,
        nickname=child.nickname,
        age=child.age,
        report_date=report.report_date,
        statistics=report.statistics_json,
        profile=report.profile_json,
        ai_analysis=report.ai_analysis,
        ai_suggestions=report.ai_suggestions,
        dimensions=dimensions,
        recent_explore=[ExploreRecordPublic.model_validate(r) for r in recent_explore_rows],
        recent_chat_titles=[ChatSessionPublic.model_validate(s) for s in recent_chat_rows],
    )
