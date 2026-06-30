from __future__ import annotations

from fastapi import UploadFile
from sqlalchemy.orm import Session

from app.core.settings import Settings
from app.models import ChildProfile, ExploreRecord
from app.schemas import ExploreAnalysis
from app.services.ai import build_explore_analysis
from app.services.memory import record_explore_memory
from app.services.storage import StoredFile, store_upload


async def process_explore_upload(
    db: Session,
    settings: Settings,
    child: ChildProfile,
    upload: UploadFile,
) -> tuple[ExploreRecord, list[dict]]:
    if not upload.content_type or not upload.content_type.startswith("image/"):
        raise ValueError("Only image uploads are supported in v1")

    stored: StoredFile = await store_upload(upload, settings.storage_dir, child.id)
    analysis: ExploreAnalysis = await build_explore_analysis(
        file_name=upload.filename or stored.file_name,
        content_type=upload.content_type or "image/jpeg",
        file_size=stored.size,
        file_url=stored.file_url,
        child_nickname=child.nickname,
        child_age=child.age,
    )

    record = ExploreRecord(
        child_id=child.id,
        media_type="IMAGE",
        file_name=stored.file_name,
        file_path=stored.file_path,
        file_url=stored.file_url,
        object_name=analysis.object_name,
        scientific_fact=analysis.scientific_fact,
        growth_dimension=analysis.growth_dimension,
        score_delta=analysis.score_delta,
        analysis_json=analysis.model_dump(),
    )
    db.add(record)
    child.token_balance += analysis.score_delta
    if analysis.score_delta >= 35 and child.current_level < 5:
        child.current_level += 1
    db.flush()
    memory_events = record_explore_memory(db, child, record)
    db.commit()
    return record, [event.payload_json for event in memory_events]
