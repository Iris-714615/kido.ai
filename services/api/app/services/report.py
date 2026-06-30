"""成长报告生成服务。

链式编排流程（对应 LangChain 的 SequentialChain 思想）：
    数据采集 → Memory 画像构建 → Prompt 组装 → LLM 调用 → 结果缓存

报告按 (child_id, date) 缓存到 growth_reports 表，当天有新数据才重新生成。
"""

from __future__ import annotations

import re
from datetime import date
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import (
    ChatMessage,
    ChatSession,
    ChildProfile,
    ExploreRecord,
    GrowthReport,
    MemoryEntity,
    MemoryEvent,
)
from app.services.ai import build_growth_report
from app.services.profile import build_child_profile
from app.services.prompts import REPORT_SYSTEM_PROMPT, build_report_prompt


async def generate_report(
    db: Session,
    child: ChildProfile,
    target_date: date | None = None,
) -> GrowthReport:
    """生成成长报告（带缓存）。

    流程：
    1. 检查当天缓存，无新数据则直接返回
    2. 采集统计数据（探索/聊天/记忆）
    3. 构建 Memory 画像（兴趣聚类、行为分析）
    4. 组装 Prompt（系统提示词 + 用户提示词）
    5. 调用 LLM（LangChain + DeepSeek）生成分析
    6. 写入/更新缓存
    """
    target_date = target_date or date.today()

    # 1. 检查缓存
    cached = db.scalar(
        select(GrowthReport)
        .where(
            GrowthReport.child_id == child.id,
            GrowthReport.report_date == target_date,
        )
    )
    if cached:
        # 检查是否有新数据：比较缓存更新时间与最新 explore 时间
        latest_explore_at = db.scalar(
            select(ExploreRecord.created_at)
            .where(ExploreRecord.child_id == child.id)
            .order_by(ExploreRecord.created_at.desc())
            .limit(1)
        )
        if not latest_explore_at or cached.updated_at > latest_explore_at:
            return cached  # 无新数据，返回缓存

    # 2. 采集统计数据
    statistics = _collect_statistics(db, child.id)

    # 3. 构建 Memory 画像
    profile = build_child_profile(db, child.id)

    # 4. 获取近期探索记录
    recent_explore_rows = db.scalars(
        select(ExploreRecord)
        .where(ExploreRecord.child_id == child.id)
        .order_by(ExploreRecord.created_at.desc())
        .limit(5)
    ).all()
    recent_explore = [
        {
            "object_name": r.object_name,
            "growth_dimension": r.growth_dimension,
        }
        for r in recent_explore_rows
    ]

    # 5. 组装 Prompt
    user_prompt = build_report_prompt(
        nickname=child.nickname,
        age=child.age,
        statistics=statistics,
        profile=profile,
        recent_explore=recent_explore,
    )

    # 6. 调用 LLM 生成分析（LangChain + DeepSeek）
    #    若 LLM 调用失败（如 API key 未配置/网络异常），降级到 FallbackProvider 保证可用性
    from app.services.ai import FallbackProvider

    try:
        ai_analysis = await build_growth_report(REPORT_SYSTEM_PROMPT, user_prompt)
    except Exception as e:
        # 记录日志，降级到规则模板生成
        import logging
        logging.getLogger(__name__).warning(
            "LLM 生成成长报告失败，降级到 FallbackProvider: %s", e
        )
        ai_analysis = await FallbackProvider().build_growth_report(
            REPORT_SYSTEM_PROMPT, user_prompt
        )

    # 7. 从分析文本中提取建议
    suggestions = _extract_suggestions(ai_analysis)

    # 8. 写入/更新缓存
    if cached:
        cached.statistics_json = statistics
        cached.profile_json = profile
        cached.ai_analysis = ai_analysis
        cached.ai_suggestions = suggestions
    else:
        cached = GrowthReport(
            child_id=child.id,
            report_date=target_date,
            statistics_json=statistics,
            profile_json=profile,
            ai_analysis=ai_analysis,
            ai_suggestions=suggestions,
        )
        db.add(cached)

    db.commit()
    db.refresh(cached)
    return cached


def _collect_statistics(db: Session, child_id: int) -> dict[str, Any]:
    """采集统计数据：探索/聊天/记忆/积分。"""
    total_explore = db.scalar(
        select(func.count(ExploreRecord.id)).where(ExploreRecord.child_id == child_id)
    ) or 0
    total_chat_sessions = db.scalar(
        select(func.count(ChatSession.id)).where(ChatSession.child_id == child_id)
    ) or 0
    total_chat_messages = db.scalar(
        select(func.count(ChatMessage.id))
        .join(ChatSession, ChatMessage.session_id == ChatSession.id)
        .where(ChatSession.child_id == child_id)
    ) or 0
    total_memory_events = db.scalar(
        select(func.count(MemoryEvent.id)).where(MemoryEvent.child_id == child_id)
    ) or 0
    total_memory_entities = db.scalar(
        select(func.count(MemoryEntity.id)).where(MemoryEntity.child_id == child_id)
    ) or 0
    total_tokens_earned = db.scalar(
        select(func.coalesce(func.sum(ExploreRecord.score_delta), 0))
        .where(ExploreRecord.child_id == child_id)
    ) or 0

    return {
        "total_explore": total_explore,
        "total_chat_sessions": total_chat_sessions,
        "total_chat_messages": total_chat_messages,
        "total_memory_events": total_memory_events,
        "total_memory_entities": total_memory_entities,
        "total_tokens_earned": total_tokens_earned,
    }


def _extract_suggestions(analysis: str) -> list[str]:
    """从 LLM 分析文本的"引导建议"段落提取建议列表。

    支持多种 markdown 列表格式：
    - 数字列表：1. / 1、
    - 符号列表：- / *
    - emoji 列表：✅ / ⭐ / 💡 等
    """
    suggestions: list[str] = []
    in_suggestion_section = False
    for line in analysis.split("\n"):
        stripped = line.strip()
        if stripped.startswith("## ") and "建议" in stripped:
            in_suggestion_section = True
            continue
        if in_suggestion_section:
            # 遇到下一个二级标题则结束
            if stripped.startswith("## "):
                break
            # 匹配多种列表项开头：数字./数字、/-/*/✅/⭐/💡 等 emoji
            match = re.match(
                r"^(?:\d+[.、)\s]|[-*]\s+|[\u2705\u2B50\u2728\u2600-\u27BF\U0001F300-\U0001FAFF]\s*)\**\s*(.+?)\**\s*$",
                stripped,
            )
            if match:
                content = match.group(1).strip()
                # 去掉残留的 markdown 加粗符号
                content = content.replace("**", "")
                if content:
                    suggestions.append(content)
    return suggestions[:3]
