from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.dependencies import get_current_child_profile, get_db_session
from app.models import MemoryEntity, MemoryEvent
from app.schemas import MemoryEntityPublic, MemoryEventPublic, MemorySummaryResponse
from app.services.memory import build_memory_summary

router = APIRouter(prefix="/memory", tags=["memory"])


@router.get("/summary", response_model=MemorySummaryResponse)
def summary(
    db: Session = Depends(get_db_session),
    child=Depends(get_current_child_profile),
    limit: int = Query(default=10, ge=1, le=50),
) -> MemorySummaryResponse:
    data = build_memory_summary(db, child.id, limit=limit)
    return MemorySummaryResponse(
        events=[MemoryEventPublic.model_validate(item) for item in data["events"]],
        entities=[MemoryEntityPublic.model_validate(item) for item in data["entities"]],
    )


@router.get("/events", response_model=list[MemoryEventPublic])
def events(
    db: Session = Depends(get_db_session),
    child=Depends(get_current_child_profile),
    limit: int = Query(default=20, ge=1, le=100),
) -> list[MemoryEventPublic]:
    items = (
        db.scalars(
            select(MemoryEvent).where(MemoryEvent.child_id == child.id).order_by(desc(MemoryEvent.id)).limit(limit)
        ).all()
    )
    return [MemoryEventPublic.model_validate(item) for item in items]


@router.get("/entities", response_model=list[MemoryEntityPublic])
def entities(
    db: Session = Depends(get_db_session),
    child=Depends(get_current_child_profile),
    limit: int = Query(default=20, ge=1, le=100),
) -> list[MemoryEntityPublic]:
    items = (
        db.scalars(
            select(MemoryEntity).where(MemoryEntity.child_id == child.id).order_by(desc(MemoryEntity.id)).limit(limit)
        ).all()
    )
    return [MemoryEntityPublic.model_validate(item) for item in items]

