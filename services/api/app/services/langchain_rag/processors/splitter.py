"""文本切割器：三种切割策略可选。

1. char_split: 递归字符切割（字符串，默认）
2. title_split: 按段落标题切分（一、 / ## / 第X章）
3. semantic_split: 按相邻块语义相似度断句（灵积 embedding 余弦相似度）
"""
from __future__ import annotations

import re
from typing import Literal

from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

SplitStrategy = Literal["char", "title", "semantic"]

# 标题正则：匹配「一、」「第X章」「## 标题」「1. 标题」等
_TITLE_PATTERN = re.compile(
    r"^(?:"
    r"[一二三四五六七八九十百千]+、"  # 一、
    r"|第[一二三四五六七八九十百千]+[章节篇]"  # 第一章
    r"|#\s+"  # ## 标题
    r"|[\d]+\.\s"  # 1. 标题
    r")"
)


class TextSplitter:
    """文本切割器，支持三种策略。"""

    def __init__(
        self,
        strategy: SplitStrategy = "char",
        chunk_size: int = 500,
        chunk_overlap: int = 50,
    ) -> None:
        self.strategy = strategy
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap

    def split(self, documents: list[Document]) -> list[Document]:
        """切割文档列表。"""
        if not documents:
            return []
        if self.strategy == "char":
            return self._char_split(documents)
        if self.strategy == "title":
            return self._title_split(documents)
        if self.strategy == "semantic":
            return self._semantic_split(documents)
        raise ValueError(f"未知切割策略: {self.strategy}")

    def _char_split(self, documents: list[Document]) -> list[Document]:
        """递归字符切割（默认）。"""
        splitter = RecursiveCharacterTextSplitter(
            chunk_size=self.chunk_size,
            chunk_overlap=self.chunk_overlap,
            separators=["\n\n", "\n", "。", "！", "？", "；", " ", ""],
        )
        return splitter.split_documents(documents)

    def _title_split(self, documents: list[Document]) -> list[Document]:
        """按段落标题切分，再对超长段做字符二次切割。"""
        out: list[Document] = []
        char_splitter = RecursiveCharacterTextSplitter(
            chunk_size=self.chunk_size,
            chunk_overlap=self.chunk_overlap,
            separators=["\n\n", "\n", "。", "！", "？", "；", " ", ""],
        )
        for doc in documents:
            lines = doc.page_content.split("\n")
            sections: list[tuple[str | None, str]] = []
            current_title: str | None = None
            buffer: list[str] = []
            for line in lines:
                if _TITLE_PATTERN.match(line.strip()):
                    if buffer:
                        sections.append((current_title, "\n".join(buffer)))
                        buffer = []
                    current_title = line.strip()
                    buffer.append(line)
                else:
                    buffer.append(line)
            if buffer:
                sections.append((current_title, "\n".join(buffer)))

            for title, text in sections:
                if not text.strip():
                    continue
                # 二次字符切割，防止超长段
                sub_docs = char_splitter.split_documents([Document(page_content=text, metadata=doc.metadata.copy())])
                for sd in sub_docs:
                    meta = dict(sd.metadata)
                    if title:
                        meta["section_title"] = title
                    out.append(Document(page_content=sd.page_content, metadata=meta))
        return out

    def _semantic_split(self, documents: list[Document]) -> list[Document]:
        """按相邻句子语义相似度断句。

        将文档按句号切句，计算相邻句向量余弦相似度，
        相似度低于阈值处断开成新块，块大小不超过 chunk_size。
        """
        from app.services.langchain_rag.core.embeddings import EmbeddingFactory
        import numpy as np

        embeddings = EmbeddingFactory.get("lingji")
        out: list[Document] = []
        for doc in documents:
            sentences = [s.strip() for s in re.split(r"(?<=[。！？])", doc.page_content) if s.strip()]
            if len(sentences) <= 1:
                out.append(doc)
                continue
            try:
                vecs = embeddings.embed_documents(sentences)
            except Exception:
                # 降级为字符切割
                out.extend(self._char_split([doc]))
                continue
            vecs_arr = np.array(vecs)
            # 归一化
            norms = np.linalg.norm(vecs_arr, axis=1, keepdims=True)
            norms[norms == 0] = 1
            vecs_arr = vecs_arr / norms

            threshold = 0.65  # 相似度低于此值则断句
            chunks: list[list[str]] = [[]]
            current_len = 0
            for i, sent in enumerate(sentences):
                if chunks[-1] and i > 0:
                    sim = float(np.dot(vecs_arr[i - 1], vecs_arr[i]))
                    if sim < threshold or current_len + len(sent) > self.chunk_size:
                        chunks.append([])
                        current_len = 0
                chunks[-1].append(sent)
                current_len += len(sent)

            for chunk_sents in chunks:
                if not chunk_sents:
                    continue
                out.append(Document(
                    page_content="".join(chunk_sents),
                    metadata=doc.metadata.copy(),
                ))
        return out
