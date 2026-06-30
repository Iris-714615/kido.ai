"""Function Call 工具①：查询孩子探索记录。

当孩子问「我上次拍到了什么」「我最近发现了什么」时，
LLM 自动调用本工具从 MySQL explore_records 表查询。
"""
from __future__ import annotations

import json

from langchain_core.tools import tool
from sqlalchemy import select

from app.db.session import SessionLocal
from app.models import ExploreRecord


@tool
def query_explore_records(child_id: int, keyword: str = "", limit: int = 5) -> str:
    """查询孩子的探索记录（最近发现了什么物体）。

    Args:
        child_id: 孩子 ID
        keyword: 物体名称关键词，可选，用于过滤
        limit: 返回条数，默认5
    Returns:
        探索记录的可读文本
    """
    db = SessionLocal()
    try:
        stmt = (
            select(ExploreRecord)
            .where(ExploreRecord.child_id == child_id)
            .order_by(ExploreRecord.created_at.desc())
            .limit(limit)
        )
        if keyword:
            stmt = stmt.where(ExploreRecord.object_name.contains(keyword))
        rows = db.scalars(stmt).all()
        if not rows:
            return "孩子还没有探索记录哦。"
        items = []
        for r in rows:
            items.append({
                "object_name": r.object_name,
                "scientific_fact": r.scientific_fact[:80],
                "growth_dimension": r.growth_dimension,
                "score_delta": r.score_delta,
                "created_at": r.created_at.strftime("%Y-%m-%d") if r.created_at else "",
            })
        return json.dumps({"count": len(rows), "records": items}, ensure_ascii=False)
    finally:
        db.close()
