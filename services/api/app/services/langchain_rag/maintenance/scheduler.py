"""知识库维护定时任务。

使用 APScheduler BackgroundScheduler：
- 每日凌晨 02:00 增量抓取科普百科关键词 → 蒸馏 → 入库
- 每周全量刷新项目数据库数据入知识库

通过 FastAPI lifespan 启动/关闭。
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

if TYPE_CHECKING:
    from apscheduler.schedulers.background import BackgroundScheduler as _BS

logger = logging.getLogger(__name__)

# 默认科普关键词（可扩展或从配置读取）
DEFAULT_CRAWL_KEYWORDS = [
    "彩虹", "火山", "恐龙", "光合作用", "万有引力",
    "指南针", "太阳能", "地震", "北极星", "蜜蜂",
]

# 默认知识库文档目录（项目根下 knowledge/）
_DEFAULT_DOC_DIR = None  # 运行时按需解析


class KBScheduler:
    """知识库定时维护调度器（单例）。"""

    _instance: "KBScheduler | None" = None

    def __init__(self) -> None:
        self.scheduler: BackgroundScheduler = BackgroundScheduler(timezone="Asia/Shanghai")
        self._started = False

    @classmethod
    def get_instance(cls) -> "KBScheduler":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def start(self) -> None:
        """启动定时任务。"""
        if self._started:
            return
        # 每日 02:00 增量爬取科普关键词
        self.scheduler.add_job(
            self._job_crawl_keywords,
            trigger=CronTrigger(hour=2, minute=0),
            id="kb_crawl_daily",
            replace_existing=True,
        )
        # 每周一 03:00 全量刷新项目数据库数据
        self.scheduler.add_job(
            self._job_refresh_db,
            trigger=CronTrigger(day_of_week="mon", hour=3, minute=0),
            id="kb_db_weekly",
            replace_existing=True,
        )
        self.scheduler.start()
        self._started = True
        logger.info("知识库定时任务已启动")

    def shutdown(self) -> None:
        """关闭定时任务。"""
        if self._started:
            self.scheduler.shutdown(wait=False)
            self._started = False
            logger.info("知识库定时任务已停止")

    # ---------- 定时任务实现 ----------
    def _job_crawl_keywords(self) -> None:
        """定时爬取科普关键词并入库（同步入口，内部跑异步）。"""
        import asyncio

        async def _run():
            from app.services.langchain_rag.maintenance.ingest import IngestPipeline

            pipeline = IngestPipeline(collection_name="science_kb")
            count = await pipeline.ingest_crawler_keywords(DEFAULT_CRAWL_KEYWORDS)
            logger.info("定时爬取入库完成: %d 块", count)

        try:
            asyncio.run(_run())
        except Exception as e:
            logger.exception("定时爬取任务失败: %s", e)

    def _job_refresh_db(self) -> None:
        """定时刷新项目数据库数据入知识库。"""
        import asyncio

        async def _run():
            from app.db.session import SessionLocal
            from app.services.langchain_rag.maintenance.ingest import IngestPipeline

            pipeline = IngestPipeline(collection_name="explore_distilled")
            db = SessionLocal()
            try:
                count = await pipeline.ingest_db_data(db)
                logger.info("定时数据库刷新入库完成: %d 块", count)
            finally:
                db.close()

        try:
            asyncio.run(_run())
        except Exception as e:
            logger.exception("定时数据库刷新任务失败: %s", e)
