"""数据源加载层：4 种 RAG 数据来源。

1. db_loader: 项目数据（MySQL/Redis/ES）——结构完整免处理
2. crawler_loader: 网络爬虫（xpath / bs4 / re）
3. document_loader: 文档（PDF / Word / Excel / txt，含表格/图像）
4. distill_loader: 模型蒸馏（大模型生成长文档的 Q→A 条目）
"""
from app.services.langchain_rag.loaders.crawler_loader import CrawlerLoader
from app.services.langchain_rag.loaders.db_loader import DBLoader
from app.services.langchain_rag.loaders.distill_loader import DistillLoader
from app.services.langchain_rag.loaders.document_loader import DocumentLoader

__all__ = ["DBLoader", "CrawlerLoader", "DocumentLoader", "DistillLoader"]
