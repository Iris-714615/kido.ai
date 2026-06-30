"""FastAPI 路由层：保留原接口签名向下兼容 + 新增知识库维护接口。

兼容原 langchain.py 的全部接口：
- GET  /deep/explore_RAG_chat  （调试，无鉴权）
- POST /deep/rag_chat          （多轮历史）
- POST /deep/rag_chat/stream   （流式）
- GET  /deep/rag_history       （历史查询）
- DELETE /deep/rag_history/{conversation_id} （清除历史）

新增：
- POST /deep/kb/refresh        （手动触发知识库刷新）
- GET  /deep/kb/stats          （知识库统计）
- POST /deep/agent_chat        （带 Function Call 的 Agent 问答）
"""
from __future__ import annotations

import json
import threading
import uuid
from pathlib import Path
from typing import Generator

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import asc, select
from sqlalchemy.orm import Session

from app.core.settings import get_settings
from app.dependencies import get_current_child_profile, get_db_session
from app.models import RAGHistory

# RAG 多轮对话历史最少保留轮数（1 轮 = 用户问题 + 助手回答）
RAG_HISTORY_MIN_TURNS = max(5, get_settings().rag_history_min_turns)

# ========== 路由 ==========
deep_router = APIRouter(prefix="/deep", tags=["langchain-rag"])

# 挂载评估优化板块路由
from app.services.langchain_rag.evaluation.eval_router import eval_router

deep_router.include_router(eval_router)

# ========== 知识库懒加载种子（首次访问注入《十万个为什么》）==========
_seed_lock = threading.Lock()
_seeded = False


def _ensure_science_kb_seeded() -> None:
    """首次访问时把《十万个为什么》注入 Chroma science_kb collection。

    保持与原 langchain.py 的行为兼容（原为 InMemoryVectorStore 加载该文件）。
    """
    global _seeded
    if _seeded:
        return
    with _seed_lock:
        if _seeded:
            return
        from app.services.langchain_rag.core.vector_store import ChromaVectorStore

        store = ChromaVectorStore.get_instance("science_kb")
        if store.count() == 0:
            knowledge_file = Path(__file__).resolve().parents[5] / "十万个为什么.txt"
            if knowledge_file.exists():
                from langchain_community.document_loaders import TextLoader
                from langchain_text_splitters import RecursiveCharacterTextSplitter

                loader = TextLoader(str(knowledge_file), encoding="utf-8")
                documents = loader.load()
                # 切割文档（防止单段超过 embedding 限制）
                splitter = RecursiveCharacterTextSplitter(
                    chunk_size=500,
                    chunk_overlap=50,
                    separators=["\n\n", "\n", "。", "！", "？", "；", " ", ""],
                )
                chunks = splitter.split_documents(documents)
                # 注入 source_id 元数据
                for i, d in enumerate(chunks):
                    d.metadata["source_id"] = f"baike_{i}"
                store.add_documents(chunks)
        _seeded = True


# ========== 请求/响应模型（与原接口保持一致）==========
class RAGChatRequest(BaseModel):
    ask: str
    conversation_id: str | None = None


class RAGChatResponse(BaseModel):
    code: int = 200
    question: str
    answer: str
    sources: list[str] = []
    conversation_id: str | None = None


class RAGHistoryItem(BaseModel):
    role: str
    content: str


class RAGHistoryListResponse(BaseModel):
    code: int = 200
    conversation_id: str
    messages: list[RAGHistoryItem] = []


class KBRefreshRequest(BaseModel):
    """知识库刷新请求。"""
    source_type: str = "crawler"  # crawler / document / db
    keywords: list[str] | None = None
    file_paths: list[str] | None = None


# ========== 历史工具函数 ==========
def _load_history(db: Session, conversation_id: str, child_id: int) -> list[dict]:
    """加载指定会话历史（升序），保留最近 RAG_HISTORY_MIN_TURNS 轮。"""
    if not conversation_id:
        return []
    rows = db.scalars(
        select(RAGHistory)
        .where(
            RAGHistory.conversation_id == conversation_id,
            RAGHistory.child_id == child_id,
        )
        .order_by(asc(RAGHistory.created_at))
    ).all()
    tail = rows[-RAG_HISTORY_MIN_TURNS * 2 :]
    out: list[dict] = []
    for r in tail:
        if r.role == "user" and r.question:
            out.append({"role": "user", "content": r.question})
        elif r.role == "assistant" and r.answer:
            out.append({"role": "assistant", "content": r.answer})
    return out


def _format_history_text(history: list[dict]) -> str:
    if not history:
        return "（暂无历史对话）"
    lines = []
    for m in history:
        role = "孩子" if m["role"] == "user" else "探索小助手"
        lines.append(f"{role}：{m['content']}")
    return "\n".join(lines)


def _save_history(
    db: Session,
    conversation_id: str,
    child_id: int,
    question: str,
    answer: str,
    sources: list[str],
) -> None:
    db.add(RAGHistory(
        conversation_id=conversation_id,
        child_id=child_id,
        role="user",
        question=question,
    ))
    db.add(RAGHistory(
        conversation_id=conversation_id,
        child_id=child_id,
        role="assistant",
        answer=answer,
        sources_json=sources or [],
    ))
    db.commit()


# ========== 接口①：调试 RAG（GET，无鉴权）==========
@deep_router.get("/explore_RAG_chat")
def explore_RAG_chat(ask: str):
    """RAG 问答接口（GET，兼容原始接口签名，仅用于调试）。"""
    if not ask or not ask.strip():
        raise HTTPException(status_code=400, detail="问题不能为空")

    _ensure_science_kb_seeded()
    from app.services.langchain_rag.rag.chain import RAGAgentChain

    chain = RAGAgentChain(use_tools=False)
    result = chain.invoke_simple(ask)

    return {
        "code": 200,
        "question": ask,
        "answer": result["answer"],
        "sources": result["sources"],
    }


# ========== 接口②：RAG 问答（POST，多轮历史）==========
@deep_router.post("/rag_chat", response_model=RAGChatResponse)
def rag_chat(
    payload: RAGChatRequest,
    child=Depends(get_current_child_profile),
    db: Session = Depends(get_db_session),
):
    """RAG 问答接口（POST，需登录鉴权，多轮历史）。"""
    if not payload.ask or not payload.ask.strip():
        raise HTTPException(status_code=400, detail="问题不能为空")

    ask = payload.ask.strip()
    conversation_id = payload.conversation_id or f"rag_{child.id}_{uuid.uuid4().hex[:12]}"

    _ensure_science_kb_seeded()

    history = _load_history(db, conversation_id, child.id)
    history_text = _format_history_text(history)

    from app.services.langchain_rag.rag.chain import RAGAgentChain

    chain = RAGAgentChain(use_tools=True)
    result = chain.invoke(
        question=ask,
        history_text=history_text,
        age=child.age if child else 6,
        turns=RAG_HISTORY_MIN_TURNS,
    )

    answer = result["answer"]
    sources = result["sources"]
    _save_history(db, conversation_id, child.id, ask, answer, sources)

    return RAGChatResponse(
        code=200,
        question=ask,
        answer=answer,
        sources=sources,
        conversation_id=conversation_id,
    )


# ========== 接口③：RAG 流式问答（POST，多轮历史）==========
@deep_router.post("/rag_chat/stream")
def rag_chat_stream(
    payload: RAGChatRequest,
    child=Depends(get_current_child_profile),
    db: Session = Depends(get_db_session),
):
    """RAG 问答流式接口（POST，需登录鉴权，多轮历史）。"""
    if not payload.ask or not payload.ask.strip():
        raise HTTPException(status_code=400, detail="问题不能为空")

    ask = payload.ask.strip()
    conversation_id = payload.conversation_id or f"rag_{child.id}_{uuid.uuid4().hex[:12]}"

    _ensure_science_kb_seeded()

    history = _load_history(db, conversation_id, child.id)
    history_text = _format_history_text(history)

    from app.services.langchain_rag.rag.chain import RAGAgentChain

    chain = RAGAgentChain(use_tools=True)

    def generate() -> Generator[str, None, None]:
        full_text = ""
        try:
            # 先发送会话元信息
            meta = {
                "type": "meta",
                "conversation_id": conversation_id,
                "sources": [],
            }
            yield f"data: {json.dumps(meta, ensure_ascii=False)}\n\n"

            # 流式输出回答
            for chunk in chain.stream(
                question=ask,
                history_text=history_text,
                age=child.age if child else 6,
                turns=RAG_HISTORY_MIN_TURNS,
            ):
                full_text += chunk
                data = {"type": "chunk", "text": chunk}
                yield f"data: {json.dumps(data, ensure_ascii=False)}\n\n"

            # 持久化历史
            try:
                _save_history(db, conversation_id, child.id, ask, full_text, [])
            except Exception as e:
                import logging
                logging.getLogger(__name__).warning("RAG 流式持久化失败: %s", e)

            yield "data: [DONE]\n\n"
        except Exception as e:
            error_data = {"type": "error", "message": str(e)}
            yield f"data: {json.dumps(error_data, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Connection": "keep-alive", "Cache-Control": "no-cache"},
    )


# ========== 接口④：历史查询 ==========
@deep_router.get("/rag_history", response_model=RAGHistoryListResponse)
def get_rag_history(
    conversation_id: str,
    child=Depends(get_current_child_profile),
    db: Session = Depends(get_db_session),
):
    """查询指定会话的历史记录。"""
    history = _load_history(db, conversation_id, child.id)
    return RAGHistoryListResponse(
        code=200,
        conversation_id=conversation_id,
        messages=[RAGHistoryItem(role=m["role"], content=m["content"]) for m in history],
    )


# ========== 接口⑤：清除历史 ==========
@deep_router.delete("/rag_history/{conversation_id}")
def clear_rag_history(
    conversation_id: str,
    child=Depends(get_current_child_profile),
    db: Session = Depends(get_db_session),
):
    """清除指定会话的全部历史记录。"""
    rows = db.scalars(
        select(RAGHistory).where(
            RAGHistory.conversation_id == conversation_id,
            RAGHistory.child_id == child.id,
        )
    ).all()
    for r in rows:
        db.delete(r)
    db.commit()
    return {"code": 200, "message": "历史记录已清除", "cleared": len(rows)}


# ========== 新增接口⑥：手动刷新知识库 ==========
@deep_router.post("/kb/refresh")
async def refresh_kb(
    payload: KBRefreshRequest,
    _child=Depends(get_current_child_profile),
):
    """手动触发知识库刷新（异步）。

    source_type:
    - crawler: 爬取 keywords 指定的百科词条
    - document: 加载 file_paths 指定的文档
    - db: 刷新项目数据库数据
    """
    import asyncio

    from app.db.session import SessionLocal
    from app.services.langchain_rag.maintenance.ingest import IngestPipeline

    pipeline = IngestPipeline(collection_name="science_kb")

    if payload.source_type == "crawler":
        keywords = payload.keywords or ["彩虹", "火山", "恐龙"]
        count = await pipeline.ingest_crawler_keywords(keywords)
    elif payload.source_type == "document":
        if not payload.file_paths:
            raise HTTPException(status_code=400, detail="document 类型需提供 file_paths")
        count = await pipeline.ingest_document_files(payload.file_paths)
    elif payload.source_type == "db":
        db = SessionLocal()
        try:
            count = await pipeline.ingest_db_data(db)
        finally:
            db.close()
    else:
        raise HTTPException(status_code=400, detail=f"未知 source_type: {payload.source_type}")

    return {"code": 200, "source_type": payload.source_type, "ingested_chunks": count}


# ========== 新增接口⑦：知识库统计 ==========
@deep_router.get("/kb/stats")
def kb_stats(_child=Depends(get_current_child_profile)):
    """查询知识库各 collection 的统计信息。"""
    from app.services.langchain_rag.core.vector_store import ChromaVectorStore

    collections = ["science_kb", "explore_distilled"]
    stats = {}
    for name in collections:
        try:
            store = ChromaVectorStore.get_instance(name)
            stats[name] = {"count": store.count()}
        except Exception as e:
            stats[name] = {"count": 0, "error": str(e)}
    return {"code": 200, "collections": stats}


# ========== 新增接口⑧：Agent 问答（显式带 Function Call）==========
@deep_router.post("/agent_chat", response_model=RAGChatResponse)
def agent_chat(
    payload: RAGChatRequest,
    child=Depends(get_current_child_profile),
    db: Session = Depends(get_db_session),
):
    """带 Function Call 的 Agent 问答接口。

    LLM 可自主调用工具查询探索记录/成长数据/天气。
    """
    if not payload.ask or not payload.ask.strip():
        raise HTTPException(status_code=400, detail="问题不能为空")

    ask = payload.ask.strip()
    conversation_id = payload.conversation_id or f"agent_{child.id}_{uuid.uuid4().hex[:12]}"

    _ensure_science_kb_seeded()

    history = _load_history(db, conversation_id, child.id)
    history_text = _format_history_text(history)

    from app.services.langchain_rag.rag.chain import RAGAgentChain

    chain = RAGAgentChain(use_tools=True)
    result = chain.invoke(
        question=ask,
        history_text=history_text,
        age=child.age if child else 6,
        turns=RAG_HISTORY_MIN_TURNS,
    )

    answer = result["answer"]
    sources = result["sources"]
    _save_history(db, conversation_id, child.id, ask, answer, sources)

    return RAGChatResponse(
        code=200,
        question=ask,
        answer=answer,
        sources=sources,
        conversation_id=conversation_id,
    )
