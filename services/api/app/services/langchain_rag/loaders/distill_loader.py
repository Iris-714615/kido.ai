"""数据源④：模型蒸馏。

用大模型把长文档/知识蒸馏成「问题 → 答案」条目，
作为 RAG 知识库的增强数据，提升问答召回率。
"""
from __future__ import annotations

import json
import re

from langchain_core.documents import Document
from langchain_core.prompts import ChatPromptTemplate


_DISTILL_SYSTEM = (
    "你是一个知识蒸馏助手。请把给定的原始材料蒸馏成若干『问题→答案』对，"
    "用于儿童科普问答知识库。\n"
    "要求：\n"
    "1. 每条问题简短自然，符合儿童提问口吻；\n"
    "2. 答案通俗易懂，控制在100字以内；\n"
    "3. 严格输出 JSON 数组，元素格式 {\"question\": \"...\", \"answer\": \"...\"}；\n"
    "4. 不要输出 JSON 以外的任何解释文字。"
)


class DistillLoader:
    """模型蒸馏加载器。"""

    def __init__(self, max_pairs: int = 8) -> None:
        self.max_pairs = max_pairs

    def distill(self, source_documents: list[Document]) -> list[Document]:
        """对源文档逐个蒸馏，返回 Q→A 形式的 Document。"""
        from app.services.langchain_rag.core.llm import LLMFactory

        if not source_documents:
            return []

        llm = LLMFactory.get_llm(temperature=0.3)
        prompt = ChatPromptTemplate.from_messages([
            ("system", _DISTILL_SYSTEM),
            ("human", "原始材料：\n{content}"),
        ])
        chain = prompt | llm

        out: list[Document] = []
        for src in source_documents:
            # 截断过长材料，避免 token 超限
            content = src.page_content[:3000]
            try:
                res = chain.invoke({"content": content})
                pairs = self._parse_pairs(res.content)
            except Exception:
                continue
            for idx, p in enumerate(pairs[: self.max_pairs]):
                page = f"问：{p['question']}\n答：{p['answer']}"
                meta = dict(src.metadata)
                meta["source"] = "distill"
                meta["source_id"] = f"distill_{src.metadata.get('source_id', 'x')}_{idx}"
                out.append(Document(page_content=page, metadata=meta))
        return out

    def _parse_pairs(self, text: str) -> list[dict]:
        """从 LLM 输出解析 JSON 数组，容错处理。"""
        text = text.strip()
        # 去除可能的 markdown 代码块包裹
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
        try:
            data = json.loads(text)
            if isinstance(data, list):
                return [d for d in data if isinstance(d, dict) and "question" in d and "answer" in d]
        except json.JSONDecodeError:
            pass
        # 兜底：正则提取
        pairs: list[dict] = []
        for m in re.finditer(r'"question"\s*:\s*"([^"]+)"\s*,\s*"answer"\s*:\s*"([^"]+)"', text):
            pairs.append({"question": m.group(1), "answer": m.group(2)})
        return pairs
