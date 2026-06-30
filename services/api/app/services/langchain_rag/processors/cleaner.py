"""数据清洗器：表格扁平化 / 图像 OCR 占位 / 通用清洗。

针对文档加载（PDF/Word/Excel）后的原始文本做归一化，
使其更适合后续切割与向量化。
"""
from __future__ import annotations

import re
from typing import Any

from langchain_core.documents import Document


class DataCleaner:
    """数据清洗工具集。"""

    @staticmethod
    def clean_text(text: str) -> str:
        """通用文本清洗：去除多余空白、不可见字符、合并连续空行。"""
        if not text:
            return ""
        # 去除零宽字符、BOM
        text = re.sub(r"[\u200b-\u200f\ufeff\u00ad]", "", text)
        # 制表符转空格
        text = text.replace("\t", " ")
        # 合并连续空格（保留换行）
        text = re.sub(r"[^\S\n]+", " ", text)
        # 合并连续空行
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()

    @staticmethod
    def flatten_table(rows: list[list[Any]]) -> str:
        """表格扁平化为可读文本（每行用 | 分隔，便于向量化）。"""
        if not rows:
            return ""
        lines = []
        for row in rows:
            cells = [str(c).strip() if c is not None else "" for c in row]
            lines.append(" | ".join(cells))
        return "\n".join(lines)

    @staticmethod
    def image_to_placeholder(image_desc: str = "") -> str:
        """图像 OCR 占位标记（实际项目可接 PaddleOCR 等）。

        此处仅生成占位文本，标记此处有图像，避免向量化丢失上下文。
        """
        desc = f"（图像内容：{image_desc}）" if image_desc else "（此处为图像，待 OCR 识别）"
        return desc

    @staticmethod
    def clean_documents(documents: list[Document]) -> list[Document]:
        """批量清洗 Document。"""
        out: list[Document] = []
        for doc in documents:
            cleaned = DataCleaner.clean_text(doc.page_content)
            if not cleaned:
                continue
            out.append(Document(page_content=cleaned, metadata=doc.metadata.copy()))
        return out
