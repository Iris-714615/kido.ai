"""知识库预处理优化（优化策略 1）。

针对入库前数据做预处理优化：
1. 无效版本清除：去重、删除空文档、删除过短片段
2. 特殊符号 / 敏感词过滤
3. 非格式数据转换：HTML 标签剥离、表格扁平化、图像占位
4. 图像去噪（opencv，可选依赖，缺失时降级为跳过）
"""
from __future__ import annotations

import logging
import re
from typing import Any

from langchain_core.documents import Document

from app.services.langchain_rag.processors.cleaner import DataCleaner
from app.services.langchain_rag.processors.sensitive_filter import SensitiveFilter

logger = logging.getLogger(__name__)


class KBPreprocessor:
    """知识库预处理优化器。"""

    def __init__(
        self,
        min_chunk_length: int = 10,
        dedup: bool = True,
        filter_sensitive: bool = True,
        denoise_image: bool = False,
    ) -> None:
        self.min_chunk_length = min_chunk_length
        self.dedup = dedup
        self.filter_sensitive = filter_sensitive
        self.denoise_image = denoise_image

    def process(self, documents: list[Document]) -> list[Document]:
        """对一批文档执行预处理优化管线。"""
        docs = documents
        # 1. 清洗（HTML/特殊符号/表格/图像占位）
        docs = self._clean(docs)
        # 2. 敏感词过滤（剔除整条敏感文档）
        if self.filter_sensitive:
            docs = self._filter_sensitive(docs)
        # 3. 无效版本清除：空/过短 + 去重
        docs = self._remove_invalid(docs)
        if self.dedup:
            docs = self._dedup(docs)
        # 4. 图像去噪（可选，需 opencv）
        if self.denoise_image:
            docs = self._denoise_images(docs)
        return docs

    def _clean(self, docs: list[Document]) -> list[Document]:
        cleaned: list[Document] = []
        for d in docs:
            text = DataCleaner.clean_text(d.page_content)
            cleaned.append(Document(page_content=text, metadata=dict(d.metadata)))
        return cleaned

    def _filter_sensitive(self, docs: list[Document]) -> list[Document]:
        kept: list[Document] = []
        for d in docs:
            if SensitiveFilter.contains(d.page_content):
                logger.info("剔除敏感文档片段: %s", d.metadata.get("source_id"))
                continue
            kept.append(d)
        return kept

    def _remove_invalid(self, docs: list[Document]) -> list[Document]:
        return [d for d in docs if len(d.page_content.strip()) >= self.min_chunk_length]

    def _dedup(self, docs: list[Document]) -> list[Document]:
        seen: set[str] = set()
        unique: list[Document] = []
        for d in docs:
            key = d.page_content.strip()
            if key in seen:
                continue
            seen.add(key)
            unique.append(d)
        return unique

    def _denoise_images(self, docs: list[Document]) -> list[Document]:
        """图像去噪（opencv 可选）。

        仅对 metadata 含 image_path 的文档生效；opencv 缺失时降级跳过。
        """
        try:
            import cv2  # type: ignore
            import numpy as np
        except ImportError:
            logger.warning("opencv 未安装，跳过图像去噪")
            return docs

        for d in docs:
            img_path = d.metadata.get("image_path")
            if not img_path:
                continue
            try:
                img = cv2.imread(str(img_path), cv2.IMREAD_COLOR)
                if img is None:
                    continue
                # 高斯去噪
                denoised = cv2.GaussianBlur(img, (3, 3), 0)
                cv2.imwrite(str(img_path), denoised)
                d.metadata["denoised"] = True
            except Exception as e:
                logger.warning("图像去噪失败 %s: %s", img_path, e)
        return docs
