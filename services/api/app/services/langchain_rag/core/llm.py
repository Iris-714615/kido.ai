"""LLM 工厂：统一解析 AI Provider 并构造 ChatOpenAI 实例。

支持：
- 优先级解析：千问(DashScope) > DeepSeek > OpenAI
- bind_tools：为 Function Call 绑定工具
- 延迟导入 langchain_openai，避免未配置时整体加载失败
"""
from __future__ import annotations

import os
from typing import Any

from fastapi import HTTPException

from app.core.settings import get_settings


class LLMFactory:
    """LLM 实例工厂（线程安全单例由调用方保证，此处只负责构造）。"""

    @staticmethod
    def resolve_provider() -> tuple[str, str, str]:
        """解析当前使用的 AI Provider。

        Returns:
            (api_key, base_url, model)

        优先级：
        1. settings.dashscope_api_key / DASHSCOPE_API_KEY → 阿里云通义千问
        2. settings.deepseek_api_key → DeepSeek
        3. settings.openai_api_key → OpenAI
        """
        settings = get_settings()

        # 1. 优先千问（DashScope，OpenAI 兼容模式）
        dashscope_key = settings.dashscope_api_key or os.getenv("DASHSCOPE_API_KEY")
        if dashscope_key:
            return (
                dashscope_key,
                settings.dashscope_base_url,
                settings.dashscope_model,
            )

        # 2. 其次 DeepSeek
        if settings.deepseek_api_key:
            return (
                settings.deepseek_api_key,
                settings.deepseek_base_url,
                settings.deepseek_model,
            )

        # 3. 最后 OpenAI
        openai_key = getattr(settings, "openai_api_key", None)
        if openai_key:
            return (
                openai_key,
                "https://api.openai.com/v1",
                getattr(settings, "openai_model", "gpt-4o-mini"),
            )

        raise HTTPException(
            status_code=500,
            detail="未配置 AI API Key，请检查 .env 中的 DASHSCOPE_API_KEY / DEEPSEEK_API_KEY",
        )

    @staticmethod
    def get_temperature() -> float:
        """根据当前 Provider 返回温度参数。"""
        settings = get_settings()
        dashscope_key = settings.dashscope_api_key or os.getenv("DASHSCOPE_API_KEY")
        if dashscope_key:
            return settings.dashscope_temperature
        if settings.deepseek_api_key:
            return settings.deepseek_temperature
        return 0.7

    @staticmethod
    def get_llm(bind_tools: list[Any] | None = None, temperature: float | None = None):
        """构造 ChatOpenAI 实例。

        Args:
            bind_tools: 要绑定的 Function Call 工具列表，None 表示不绑定。
            temperature: 温度，None 则按 Provider 默认值。
        """
        from langchain_openai import ChatOpenAI

        api_key, base_url, model = LLMFactory.resolve_provider()
        temp = temperature if temperature is not None else LLMFactory.get_temperature()

        llm = ChatOpenAI(
            model=model,
            api_key=api_key,
            base_url=base_url,
            temperature=temp,
        )
        if bind_tools:
            # langchain 1.0：ChatOpenAI.bind_tools 接收工具列表
            llm = llm.bind_tools(bind_tools)
        return llm
