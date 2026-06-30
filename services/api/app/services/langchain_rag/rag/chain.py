"""RAG + Function Call 链编排（任务四核心）。

实现：
- RAG 检索 context 注入 Prompt
- LLM 绑定 Function Call 工具
- 工具执行循环：LLM 决策 → 调用工具 → 回灌结果 → 再决策
- 敏感词后检
- 支持非流式 / 流式输出
"""
from __future__ import annotations

import json
from typing import Generator

from langchain_core.messages import AIMessage, ToolMessage

from app.services.langchain_rag.core.llm import LLMFactory
from app.services.langchain_rag.core.prompts import (
    build_science_agent_prompt,
    build_science_rag_prompt,
    build_simple_rag_prompt,
)
from app.services.langchain_rag.processors.sensitive_filter import SensitiveFilter
from app.services.langchain_rag.rag.retriever import RAGRetriever
from app.services.langchain_rag.tools import ALL_TOOLS

# 工具名 → 可调用对象 映射
_TOOL_MAP = {t.name: t for t in ALL_TOOLS}

# 单轮最多工具调用迭代次数，防止死循环
MAX_TOOL_ITERATIONS = 3


class RAGAgentChain:
    """RAG + Function Call 编排链。"""

    def __init__(
        self,
        use_tools: bool = True,
        retriever: RAGRetriever | None = None,
    ) -> None:
        self.use_tools = use_tools
        self.retriever = retriever or RAGRetriever()
        self.tools = ALL_TOOLS if use_tools else []

    def _build_llm(self):
        if self.use_tools:
            return LLMFactory.get_llm(bind_tools=self.tools)
        return LLMFactory.get_llm()

    def _build_messages(self, question: str, context: str, history_text: str, age: int, turns: int):
        """用 Prompt 模板一次性填充占位符，返回初始消息列表。"""
        prompt = build_science_agent_prompt() if self.use_tools else build_science_rag_prompt()
        return prompt.format_messages(
            context=context,
            history=history_text,
            age=age,
            turns=turns,
            question=question,
        )

    # ---------- 非流式 ----------
    def invoke(
        self,
        question: str,
        history_text: str = "（暂无历史对话）",
        age: int = 6,
        turns: int = 5,
    ) -> dict:
        """非流式调用。

        Returns:
            {"answer": str, "sources": list[str], "tool_used": list[str], "blocked": bool}
        """
        # 1. RAG 检索
        retrieval = self.retriever.retrieve(question)
        if retrieval.blocked:
            return {
                "answer": f"抱歉，{retrieval.block_reason}，请换一种问法哦。",
                "sources": [],
                "tool_used": [],
                "blocked": True,
            }

        # 2. 构造初始消息（Prompt 模板一次填充）
        messages = self._build_messages(question, retrieval.context, history_text, age, turns)
        llm = self._build_llm()
        tool_used: list[str] = []

        # 3. 工具调用循环
        for _ in range(MAX_TOOL_ITERATIONS):
            ai_msg: AIMessage = llm.invoke(messages)
            tool_calls = getattr(ai_msg, "tool_calls", None) or []
            if not tool_calls:
                answer = self._post_check(ai_msg.content)
                return {
                    "answer": answer,
                    "sources": retrieval.sources,
                    "tool_used": tool_used,
                    "blocked": False,
                }
            # 有工具调用：执行并回灌
            messages.append(ai_msg)
            for tc in tool_calls:
                tool_name = tc.get("name", "")
                tool_args = tc.get("args", {})
                tool_used.append(tool_name)
                observation = self._execute_tool(tool_name, tool_args)
                messages.append(ToolMessage(
                    content=observation,
                    tool_call_id=tc.get("id", ""),
                ))

        # 达到最大迭代仍未收敛，强制取最后一条 AIMessage
        final = llm.invoke(messages)
        answer = self._post_check(final.content)
        return {
            "answer": answer,
            "sources": retrieval.sources,
            "tool_used": tool_used,
            "blocked": False,
        }

    # ---------- 流式 ----------
    def stream(
        self,
        question: str,
        history_text: str = "（暂无历史对话）",
        age: int = 6,
        turns: int = 5,
    ) -> Generator[str, None, None]:
        """流式输出最终回答文本块。

        工具调用阶段不向外输出，仅最终回答阶段流式输出。
        """
        # 1. RAG 检索
        retrieval = self.retriever.retrieve(question)
        if retrieval.blocked:
            yield f"抱歉，{retrieval.block_reason}，请换一种问法哦。"
            return

        # 2. 构造初始消息
        messages = self._build_messages(question, retrieval.context, history_text, age, turns)
        llm = self._build_llm()

        # 3. 工具调用循环（非流式收尾，决定最终回答）
        final_answer: str | None = None
        for _ in range(MAX_TOOL_ITERATIONS):
            ai_msg: AIMessage = llm.invoke(messages)
            tool_calls = getattr(ai_msg, "tool_calls", None) or []
            if not tool_calls:
                final_answer = ai_msg.content
                break
            messages.append(ai_msg)
            for tc in tool_calls:
                tool_name = tc.get("name", "")
                tool_args = tc.get("args", {})
                observation = self._execute_tool(tool_name, tool_args)
                messages.append(ToolMessage(
                    content=observation,
                    tool_call_id=tc.get("id", ""),
                ))
        if final_answer is None:
            final_answer = llm.invoke(messages).content

        # 4. 敏感词后检后，按字符块流式输出（中文按 2-3 字一块）
        final_answer = self._post_check(final_answer)
        step = 2
        for i in range(0, len(final_answer), step):
            yield final_answer[i : i + step]

    # ---------- 简易调试（无历史、无工具） ----------
    def invoke_simple(self, question: str) -> dict:
        """简易调试调用（兼容 GET 接口，无历史无工具）。"""
        retrieval = self.retriever.retrieve(question)
        if retrieval.blocked:
            return {
                "answer": f"抱歉，{retrieval.block_reason}。",
                "sources": [],
                "blocked": True,
            }
        prompt = build_simple_rag_prompt()
        chain = prompt | LLMFactory.get_llm()
        res = chain.invoke({"context": retrieval.context, "question": question})
        return {
            "answer": self._post_check(res.content),
            "sources": retrieval.sources,
            "blocked": False,
        }

    # ---------- 辅助 ----------
    def _execute_tool(self, name: str, args: dict) -> str:
        """执行单个工具，返回字符串观测结果。"""
        tool_fn = _TOOL_MAP.get(name)
        if tool_fn is None:
            return json.dumps({"error": f"未知工具: {name}"}, ensure_ascii=False)
        try:
            return tool_fn.invoke(args)
        except Exception as e:
            return json.dumps({"error": f"工具 {name} 执行失败: {e}"}, ensure_ascii=False)

    def _post_check(self, text: str) -> str:
        """敏感词后检：打码处理。"""
        return SensitiveFilter.mask(text)
