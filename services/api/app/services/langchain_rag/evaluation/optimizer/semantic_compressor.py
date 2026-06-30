"""语义压缩 + 关键词提取（优化策略 4）。

两件事：
1. 语义压缩：把检索到的多个长文档压缩成与问题最相关的精炼片段
   - 主路径：LLM 提取相关内容（langchain ContextualCompressionRetriever 思路）
   - 降级路径：基于关键词的句子抽取
2. 关键词提取：从问题/文档中抽取关键词，用于 BM25 加权、问题改写、检索过滤
"""
from __future__ import annotations

import logging
import re
from typing import Any

from langchain_core.documents import Document

logger = logging.getLogger(__name__)


class SemanticCompressor:
    """语义压缩 + 关键词提取。"""

    COMPRESS_PROMPT = (
        "你是儿童科普知识精炼助手。下面是若干检索到的知识片段和用户问题。\n"
        "请只保留与问题直接相关的内容，去除无关背景、重复表述、冗余修饰。\n"
        "保留关键事实和因果关系，不要添加任何新信息，不要回答问题。\n"
        "输出精炼后的知识片段（200字以内）。"
    )

    KEYWORD_PROMPT = (
        "从下面这段文本中提取 3-8 个关键词，用于检索增强。\n"
        "要求：名词/名词短语优先，专有名词保留，去除停用词。\n"
        "严格输出 JSON 数组：[\"关键词1\", \"关键词2\"]\n"
        "不要输出 JSON 以外内容。"
    )

    # 中文停用词（简表）
    STOP_WORDS = {
        "的", "了", "是", "在", "我", "有", "和", "就", "不", "人", "都",
        "一", "一个", "上", "也", "很", "到", "说", "要", "去", "你",
        "会", "着", "没有", "看", "好", "自己", "这", "那", "什么", "怎么",
        "为什么", "吗", "呢", "啊", "吧", "把", "被", "让", "给", "向",
    }

    def compress(self, question: str, documents: list[Document]) -> str:
        """语义压缩：把多文档压缩成与问题相关的精炼片段。"""
        if not documents:
            return ""

        # 文档较短时直接拼接，无需压缩
        total = sum(len(d.page_content) for d in documents)
        if total <= 300:
            return "\n".join(d.page_content for d in documents)

        try:
            return self._llm_compress(question, documents)
        except Exception as e:
            logger.warning("LLM 语义压缩失败，降级关键词抽取: %s", e)
            return self._keyword_compress(question, documents)

    def extract_keywords(self, text: str, top_n: int = 5) -> list[str]:
        """关键词提取。

        主路径：LLM 提取；降级：TF 简易抽取。
        """
        try:
            return self._llm_keywords(text, top_n)
        except Exception as e:
            logger.warning("LLM 关键词提取失败，降级 TF: %s", e)
            return self._tf_keywords(text, top_n)

    # ---------- LLM 路径 ----------
    def _llm_compress(self, question: str, documents: list[Document]) -> str:
        from langchain_core.prompts import ChatPromptTemplate
        from app.services.langchain_rag.core.llm import LLMFactory

        context = "\n---\n".join(d.page_content for d in documents)
        prompt = ChatPromptTemplate.from_messages([
            ("system", self.COMPRESS_PROMPT),
            ("human", "用户问题：{question}\n知识片段：\n{context}"),
        ])
        chain = prompt | LLMFactory.get_llm(temperature=0.0)
        res = chain.invoke({"question": question, "context": context})
        return res.content.strip()

    def _llm_keywords(self, text: str, top_n: int) -> list[str]:
        from langchain_core.prompts import ChatPromptTemplate
        from app.services.langchain_rag.core.llm import LLMFactory
        import json

        prompt = ChatPromptTemplate.from_messages([
            ("system", self.KEYWORD_PROMPT),
            ("human", "{text}"),
        ])
        chain = prompt | LLMFactory.get_llm(temperature=0.0)
        res = chain.invoke({"text": text})
        t = res.content.strip()
        t = re.sub(r"^```(?:json)?\s*", "", t)
        t = re.sub(r"\s*```$", "", t)
        kws = json.loads(t)
        if isinstance(kws, list):
            return [str(k) for k in kws[:top_n]]
        return []

    # ---------- 降级路径 ----------
    def _keyword_compress(self, question: str, documents: list[Document]) -> list[str] | str:
        """基于关键词的句子抽取（无 LLM 时的降级）。"""
        keywords = self._tf_keywords(question, top_n=5)
        if not keywords:
            return "\n".join(d.page_content[:200] for d in documents)

        sents: list[str] = []
        for d in documents:
            for sent in re.split(r"[。！？\n]+", d.page_content):
                sent = sent.strip()
                if any(kw in sent for kw in keywords):
                    sents.append(sent)
        return "\n".join(sents[:5]) if sents else "\n".join(d.page_content[:200] for d in documents)

    def _tf_keywords(self, text: str, top_n: int) -> list[str]:
        """简易词频关键词提取（jieba 缺失时用字符 n-gram）。"""
        try:
            import jieba  # type: ignore
            words = [w for w in jieba.cut(text) if len(w) >= 2 and w not in self.STOP_WORDS]
        except ImportError:
            # 降级：2-4 字汉字 n-gram
            words = re.findall(r"[\u4e00-\u9fa5]{2,4}", text)
            words = [w for w in words if w not in self.STOP_WORDS]

        freq: dict[str, int] = {}
        for w in words:
            freq[w] = freq.get(w, 0) + 1
        ranked = sorted(freq.items(), key=lambda x: x[1], reverse=True)
        return [w for w, _ in ranked[:top_n]]
