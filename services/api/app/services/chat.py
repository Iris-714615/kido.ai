from __future__ import annotations

from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.models import ChatMessage, ChatSession, ChildProfile
from app.services.ai import build_chat_reply
from app.services.memory import build_memory_text, record_chat_memory


def get_or_create_session(db: Session, child: ChildProfile, session_id: int | None, title: str | None) -> ChatSession:
    if session_id is not None:
        session = db.get(ChatSession, session_id)
        if session is None or session.child_id != child.id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Chat session not found")
        return session

    session = ChatSession(child_id=child.id, title=title or "新的对话", last_message_at=None)
    db.add(session)
    db.flush()
    return session


def list_sessions(db: Session, child_id: int) -> list[ChatSession]:
    return (
        db.scalars(select(ChatSession).where(ChatSession.child_id == child_id).order_by(desc(ChatSession.id))).all()
    )


def append_message(db: Session, session: ChatSession, role: str, content: str, metadata_json: dict | None = None) -> ChatMessage:
    message = ChatMessage(
        session_id=session.id,
        role=role,
        content=content,
        metadata_json=metadata_json or {},
    )
    db.add(message)
    session.last_message_at = datetime.now(timezone.utc)
    db.flush()
    return message


async def compose_reply(db: Session, child: ChildProfile, session: ChatSession, user_message: str) -> tuple[ChatMessage, ChatMessage, list[dict]]:
    user_msg = append_message(db, session, "user", user_message, {"source": "web"})
    memory_text = build_memory_text(db, child.id, limit=5)
    reply = await build_chat_reply(user_message, memory_text, child.nickname, child.age)
    assistant_msg = append_message(
        db,
        session,
        "assistant",
        reply.message,
        {
            "memory_summary": reply.memory_summary,
            "suggested_follow_up": reply.suggested_follow_up,
        },
    )
    memory_events = record_chat_memory(
        db,
        child=child,
        session=session,
        user_message=user_message,
        assistant_message=reply.message,
    )
    db.commit()
    return user_msg, assistant_msg, [event.payload_json for event in memory_events]
