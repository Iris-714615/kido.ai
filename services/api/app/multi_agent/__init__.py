"""KidoAI 多智能体模块（动态多智能体 · 儿童绘本共创 × 内容安全审核闭环）。

基于 docs/story_safety_agent_spec.md 设计规范实现。由于 deepagents 库未安装，
采用纯 LangChain 1.0 + LangGraph 原生 API 等价还原：
  - 异步子 Agent 并发 → asyncio.gather
  - interrupt_on HITL → interrupt_before
  - response_format 结构化输出 → with_structured_output
  - CompositeBackend/StoreBackend → 文件存储持久化

本模块与现有 services/langchain_rag 等已跑通模块物理隔离，仅通过 main.py
追加一行 include_router 接入。
"""
from app.multi_agent.router import router as story_router

__all__ = ["story_router"]
