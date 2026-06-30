"""异步入库管线：统一编排 加载 → 清洗 → 切割 → 敏感词过滤 → 入库。

支持 4 种数据源异步入库，用 asyncio.to_thread 包装同步 IO，
不阻塞 FastAPI 事件循环。
"""
from __future__ import annotations

import asyncio
import logging
from typing import Literal

from langchain_core.documents import Document

from app.services.langchain_rag.core.vector_store import ChromaVectorStore, DEFAULT_COLLECTION
from app.services.langchain_rag.processors.cleaner import DataCleaner
from app.services.langchain_rag.processors.sensitive_filter import SensitiveFilter
from app.services.langchain_rag.processors.splitter import TextSplitter, SplitStrategy

logger = logging.getLogger(__name__)

SourceType = Literal["document", "crawler", "db", "distill"]


class IngestPipeline:
    """知识库入库管线。"""

    def __init__(
        self,
        collection_name: str = DEFAULT_COLLECTION,
        split_strategy: SplitStrategy = "char",
        chunk_size: int = 500,
        chunk_overlap: int = 50,
    ) -> None:
        self.store = ChromaVectorStore.get_instance(collection_name)
        self.splitter = TextSplitter(strategy=split_strategy, chunk_size=chunk_size, chunk_overlap=chunk_overlap)

    async def ingest_documents(self, documents: list[Document]) -> int:
        """对已加载的 Document 列表执行入库管线，返回入库块数。"""
        if not documents:
            return 0
        # 1. 清洗
        cleaned = DataCleaner.clean_documents(documents)
        # 2. 切割
        chunks = self.splitter.split(cleaned)
        # 3. 敏感词过滤（丢弃含敏感词的块）
        chunks = SensitiveFilter.filter_documents(chunks, drop=True)
        if not chunks:
            return 0
        # 4. 入库（同步 IO，放线程池）
        ids = [f"{c.metadata.get('source_id', i)}_{i}" for i, c in enumerate(chunks)]
        await asyncio.to_thread(self.store.add_documents, chunks, ids)
        logger.info("入库完成: collection=%s, chunks=%d", self.store.collection_name, len(chunks))
        return len(chunks)

    # ---------- 各数据源便捷入口 ----------
    async def ingest_document_files(self, file_paths: list[str]) -> int:
        """文档文件入库（PDF/Word/Excel/txt）。"""
        from app.services.langchain_rag.loaders.document_loader import DocumentLoader

        loader = DocumentLoader()
        total = 0
        for fp in file_paths:
            try:
                docs = await asyncio.to_thread(loader.load, fp)
                total += await self.ingest_documents(docs)
            except Exception as e:
                logger.warning("文档入库失败 %s: %s", fp, e)
        return total

    async def ingest_crawler_keywords(self, keywords: list[str], parser: str = "bs4") -> int:
        """爬虫关键词入库。"""
        from app.services.langchain_rag.loaders.crawler_loader import CrawlerLoader

        loader = CrawlerLoader(parser=parser)
        total = 0
        for kw in keywords:
            try:
                doc = await asyncio.to_thread(loader.crawl_baidu_baike, kw)
                if doc:
                    total += await self.ingest_documents([doc])
            except Exception as e:
                logger.warning("爬虫入库失败 %s: %s", kw, e)
        return total

    async def ingest_db_data(self, db) -> int:
        """项目数据库数据入库。"""
        from app.services.langchain_rag.loaders.db_loader import DBLoader

        loader = DBLoader(db)
        docs = await asyncio.to_thread(loader.load_all)
        return await self.ingest_documents(docs)

    async def ingest_distill(self, source_documents: list[Document]) -> int:
        """模型蒸馏入库。"""
        from app.services.langchain_rag.loaders.distill_loader import DistillLoader

        distiller = DistillLoader()
        pairs = await asyncio.to_thread(distiller.distill, source_documents)
        return await self.ingest_documents(pairs)
