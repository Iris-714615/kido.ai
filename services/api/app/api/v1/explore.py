from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.core.settings import get_settings
from app.dependencies import get_current_child_profile, get_db_session
from app.models import ChildProfile, ExploreRecord
from app.schemas import ExploreRecordPublic, ExploreResponse
from app.services.explore import process_explore_upload

router = APIRouter(prefix="/explore", tags=["explore"])


@router.post("/image", response_model=ExploreResponse)
async def analyze_image(
    file: UploadFile = File(...),
    db: Session = Depends(get_db_session),
    child: ChildProfile = Depends(get_current_child_profile),
) -> ExploreResponse:
    settings = get_settings()
    try:
        record, memory_events = await process_explore_upload(db, settings, child, file)
    except ValueError as exc:
        # 文件类型/大小等业务校验失败 → 400
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    # 探索成功后，异步触发成长档案更新（不阻塞响应）
    _child_id = child.id
    async def _update_growth_report():
        """后台任务：探索后更新成长档案"""
        from app.services.report import generate_report
        from app.db.session import get_db
        try:
            inner_db = next(get_db())
            try:
                inner_child = inner_db.get(ChildProfile, _child_id)
                if inner_child:
                    await generate_report(inner_db, inner_child)
            finally:
                inner_db.close()
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning("探索后成长档案生成失败: %s", e)

    asyncio.create_task(_update_growth_report())

    return ExploreResponse(record=ExploreRecordPublic.model_validate(record), memory_events=memory_events)


@router.get("/records", response_model=list[ExploreRecordPublic])
def list_records(
    db: Session = Depends(get_db_session),
    child=Depends(get_current_child_profile),
    limit: int = Query(default=20, ge=1, le=100),
) -> list[ExploreRecordPublic]:
    records = (
        db.scalars(
            select(ExploreRecord)
            .where(ExploreRecord.child_id == child.id)
            .order_by(desc(ExploreRecord.id))
            .limit(limit)
        ).all()
    )
    return [ExploreRecordPublic.model_validate(record) for record in records]


@router.get("/records/{record_id}", response_model=ExploreRecordPublic)
def get_record(
    record_id: int,
    db: Session = Depends(get_db_session),
    child=Depends(get_current_child_profile),
) -> ExploreRecordPublic:
    record = db.get(ExploreRecord, record_id)
    if record is None or record.child_id != child.id:
        raise HTTPException(status_code=404, detail="Explore record not found")
    return ExploreRecordPublic.model_validate(record)
