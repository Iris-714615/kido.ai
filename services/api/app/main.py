from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api.v1 import auth, chat, explore, memory, coze, parent, subscription, payment, notify
from app.core.bootstrap import seed_demo_account
from app.core.settings import get_settings
from app.db.base import Base
from app.db.session import SessionLocal, engine
from app.models import *  # noqa: F403

from app.services.langchain import deep_router
from app.multi_agent import story_router

@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        seed_demo_account(db, get_settings())
    finally:
        db.close()
    # 启动知识库定时维护任务以及定时成长报告更新通知
    from app.services.langchain_rag.maintenance import KBScheduler
    kb_scheduler = KBScheduler.get_instance()
    kb_scheduler.start()

    # ✅ 激活：每日 20:00 自动批量生成并发送成长报告
    scheduler = kb_scheduler.scheduler
    from app.services.report import generate_daily_reports_job
    scheduler.add_job(
        generate_daily_reports_job,
        "cron",
        hour=20,
        minute=0,
        id="daily_growth_report",
        replace_existing=True,      # 防止重启后重复注册
        misfire_grace_time=3600,    # 错过触发时间允许 1 小时内补跑
    )
    
    try:
        yield
    finally:
        kb_scheduler.shutdown()


settings = get_settings()
app = FastAPI(title=settings.app_name, version="0.1.0", lifespan=lifespan)

# 当允许所有来源（"*"）时，浏览器禁止同时使用 credentials；
# 此时退化为不携带凭证的宽松 CORS，避免配置冲突导致跨域请求失败。
_origins = settings.cors_allow_origins
_allow_all = "*" in _origins
app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins,
    allow_credentials=not _allow_all,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router, prefix=settings.api_prefix)
app.include_router(explore.router, prefix=settings.api_prefix)
app.include_router(chat.router, prefix=settings.api_prefix)
app.include_router(memory.router, prefix=settings.api_prefix)
app.include_router(coze.router, prefix=settings.api_prefix)
app.include_router(parent.router, prefix=settings.api_prefix)
app.include_router(subscription.router, prefix=settings.api_prefix)
app.include_router(payment.router, prefix=settings.api_prefix)
app.include_router(notify.router, prefix=settings.api_prefix)
app.include_router(deep_router, prefix=settings.api_prefix)
app.include_router(story_router, prefix=settings.api_prefix)

app.mount("/media", StaticFiles(directory=str(settings.storage_dir)), name="media")


@app.get("/")
def root() -> dict[str, str]:
    return {"name": settings.app_name, "status": "ok"}


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "healthy"}
