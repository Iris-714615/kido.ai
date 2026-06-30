"""问题改写多路召回（优化策略 2）。

针对用户问题不精准的问题：
- 用 LLM 把原问题改写成 3 个不同视角的子问题
- 用 3 个子问题分别检索
- 合并去重后返回（供后续 rerank）

提示词策略：
1. 同义改写：换一种说法
2. 细化改写：补充背景/细节
3. 反向改写：从对立面或追问角度
"""
from __future__ import annotations

import logging
import re
from typing import Any

from langchain_core.documents import Document

from app.services.langchain_rag.rag.retriever import RAGRetriever

logger = logging.getLogger(__name__)


class QueryRewriter:
    """问题改写多路召回。"""

    REWRITE_PROMPT = (
        "你是儿童科普问题改写助手。把用户问题改写成 3 个不同视角的子问题，"
        "用于多路召回提升检索效果。\n"
        "要求：\n"
        "1. 同义改写：换一种说法，保留原意\n"
        "2. 细化改写：补充可能的相关背景或细节\n"
        "3. 反向改写：从对立面或追问角度\n"
        "严格输出 JSON 数组：[\"子问题1\", \"子问题2\", \"子问题3\"]\n"
        "不要输出 JSON 以外内容。"
    )

    def __init__(self, num_rewrites: int = 3) -> None:
        self.num_rewrites = num_rewrites

    def rewrite(self, question: str) -> list[str]:
        """用 LLM 把问题改写成 N 个子问题。"""
        from langchain_core.prompts import ChatPromptTemplate
        from app.services.langchain_rag.core.llm import LLMFactory

        prompt = ChatPromptTemplate.from_messages([
            ("system", self.REWRITE_PROMPT),
            ("human", "用户问题：{question}"),
        ])
        chain = prompt | LLMFactory.get_llm(temperature=0.3)
        try:
            res = chain.invoke({"question": question})
            text = res.content.strip()
            text = re.sub(r"^```(?:json)?\s*", "", text)
            text = re.sub(r"\s*```$", "", text)
            import json
            sub_questions = json.loads(text)
            if isinstance(sub_questions, list):
                return [str(q) for q in sub_questions[: self.num_rewrites]]
        except Exception as e:
            logger.warning("问题改写失败，回退原问题: %s", e)
        return [question]

    def retrieve_with_rewrites(
        self,
        question: str,
        k_per_query: int = 3,
    ) -> list[Document]:
        """改写后多路召回，合并去重。

        Args:
            question: 原问题
            k_per_query: 每个子问题召回的条数
        Returns:
            合并去重后的文档列表（按出现顺序，原问题结果优先）
        """
        sub_questions = self.rewrite(question)
        # 原问题也参与召回，放在最前
        all_queries = [question] + sub_questions

        retriever = RAGRetriever()
        seen_ids: set[str] = set()
        merged: list[Document] = []

        for q in all_queries:
            try:
                result = retriever.retrieve(q, top_k=k_per_query)
                for doc in result.documents:
                    sid = doc.metadata.get("source_id", doc.page_content[:32])
                    if sid in seen_ids:
                        continue
                    seen_ids.add(sid)
                    merged.append(doc)
            except Exception as e:
                logger.warning("多路召回子问题失败 [%s]: %s", q, e)

        logger.info(
            "问题改写多路召回: 原问题=%s, 子问题=%s, 合并去重后=%d条",
            question, sub_questions, len(merged),
        )
        return merged
