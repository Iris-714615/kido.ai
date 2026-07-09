from __future__ import annotations

import json
from typing import AsyncGenerator

from fastapi import APIRouter, Body, Depends, HTTPException
from fastapi.responses import Response, StreamingResponse
from sqlalchemy.orm import Session

from app.dependencies import check_chat_quota, get_current_child_profile, get_db_session
from app.models import ChatSession, ChatMessage
from app.schemas import (
    ChatExchangeResponse,
    ChatMessageCreate,
    ChatMessagePublic,
    ChatSessionCreate,
    ChatSessionPublic,
)
from app.services.ai import build_chat_reply, stream_chat_reply
from app.services.chat import append_message, build_memory_text, get_or_create_session, list_sessions, record_chat_memory
from app.services.tts import synthesize

router = APIRouter(prefix="/chat", tags=["chat"])


@router.post("/sessions", response_model=ChatSessionPublic)
def create_session(
    payload: ChatSessionCreate,
    db: Session = Depends(get_db_session),
    child=Depends(get_current_child_profile),
) -> ChatSessionPublic:
    session = get_or_create_session(db, child, None, payload.title)
    db.commit()
    return ChatSessionPublic.model_validate(session)


@router.get("/sessions", response_model=list[ChatSessionPublic])
def get_sessions(
    db: Session = Depends(get_db_session),
    child=Depends(get_current_child_profile),
) -> list[ChatSessionPublic]:
    return [ChatSessionPublic.model_validate(session) for session in list_sessions(db, child.id)]


@router.get("/sessions/{session_id}", response_model=ChatSessionPublic)
def get_session(
    session_id: int,
    db: Session = Depends(get_db_session),
    child=Depends(get_current_child_profile),
) -> ChatSessionPublic:
    session = db.get(ChatSession, session_id)
    if session is None or session.child_id != child.id:
        raise HTTPException(status_code=404, detail="Chat session not found")
    return ChatSessionPublic.model_validate(session)


@router.post("/sessions/{session_id}/messages", response_model=ChatExchangeResponse)
async def send_message(
    session_id: int,
    payload: ChatMessageCreate,
    db: Session = Depends(get_db_session),
    child=Depends(get_current_child_profile),
    _quota=Depends(check_chat_quota),
) -> ChatExchangeResponse:
    session = get_or_create_session(db, child, session_id, None)
    user_msg = append_message(db, session, "user", payload.content, {"source": "web"})
    db.flush()

    memory_text = build_memory_text(db, child.id, limit=5)
    reply = await build_chat_reply(payload.content, memory_text, child.nickname, child.age)

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
        user_message=payload.content,
        assistant_message=reply.message,
    )
    db.commit()
    db.refresh(session)
    return ChatExchangeResponse(
        session=ChatSessionPublic.model_validate(session),
        user_message=ChatMessagePublic.model_validate(user_msg),
        assistant_message=ChatMessagePublic.model_validate(assistant_msg),
        memory_events=[event.payload_json for event in memory_events],
    )


@router.post("/sessions/{session_id}/messages/stream")
def send_message_stream(
    session_id: int,
    payload: ChatMessageCreate,
    db: Session = Depends(get_db_session),
    child=Depends(get_current_child_profile),
    _quota=Depends(check_chat_quota),
):
    session = get_or_create_session(db, child, session_id, None)
    user_msg = append_message(db, session, "user", payload.content, {"source": "web"})
    db.flush()

    memory_text = build_memory_text(db, child.id, limit=5)

    async def streamer() -> AsyncGenerator[bytes, None]:
        full_text = ""
        async for chunk in stream_chat_reply(payload.content, child.nickname, child.age, child.id):
            full_text += chunk
            data = {"type": "chunk", "text": chunk}
            yield f"data: {json.dumps(data, ensure_ascii=False)}\n\n".encode("utf-8")

        assistant_msg = append_message(
            db,
            session,
            "assistant",
            full_text.strip(),
            {"source": "coze_stream", "streamed": True},
        )
        # 与非流式接口保持一致：将本次对话写入记忆系统
        record_chat_memory(
            db,
            child=child,
            session=session,
            user_message=payload.content,
            assistant_message=assistant_msg.content,
        )
        db.commit()

        final_data = {
            "type": "done",
            "message_id": assistant_msg.id,
            "session_id": session.id,
        }
        yield f"data: {json.dumps(final_data, ensure_ascii=False)}\n\n".encode("utf-8")

    return StreamingResponse(streamer(), media_type="text/event-stream")


@router.post("/tts")
def text_to_speech(
    payload: dict = Body(...),
    child=Depends(get_current_child_profile),
) -> Response:
    """文本转语音（TTS）。

    请求体：{"text": "要播放的文本", "voice": "longxiaochun"(可选)}
    响应：audio/wav 二进制音频流
    """
    text = (payload.get("text") or "").strip()
    voice = payload.get("voice")
    if not text:
        raise HTTPException(status_code=400, detail="text 不能为空")
    try:
        audio = synthesize(text, voice)
        return Response(content=audio, media_type="audio/wav")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"TTS 合成失败: {exc}")