"""向量化工厂：统一构造 Embeddings 实例。

支持三种向量模型（按需求预留）：
- lingji: 阿里灵积 text-embedding-v2（默认，远程 API，已实际接入）
- bge: BGE 本地模型（预留接口，需下载权重）
- m3e: m3e 本地模型（预留接口，需下载权重）
"""
from __future__ import annotations

import os
from typing import Literal

from fastapi import HTTPException

from app.core.settings import get_settings

EmbeddingProvider = Literal["lingji", "bge", "m3e"]


class EmbeddingFactory:
    """Embeddings 实例工厂。"""

    @staticmethod
    def get(provider: EmbeddingProvider = "lingji"):
        """获取指定 Provider 的 Embeddings 实例。

        Args:
            provider: lingji(默认) / bge / m3e
        """
        if provider == "lingji":
            return EmbeddingFactory._get_lingji()
        if provider == "bge":
            return EmbeddingFactory._get_bge()
        if provider == "m3e":
            return EmbeddingFactory._get_m3e()
        raise ValueError(f"不支持的向量模型 Provider: {provider}")

    @staticmethod
    def _get_lingji():
        """阿里灵积 text-embedding-v2（远程 API）。

        复用 DashScope 的 OpenAI 兼容模式，关闭 ctx 长度检查以加速。
        """
        from langchain_openai import OpenAIEmbeddings

        settings = get_settings()
        dashscope_key = settings.dashscope_api_key or os.getenv("DASHSCOPE_API_KEY")
        if not dashscope_key:
            # 兜底：使用 LLM Provider 的 key
            from app.services.langchain_rag.core.llm import LLMFactory

            api_key, base_url, _ = LLMFactory.resolve_provider()
            return OpenAIEmbeddings(
                api_key=api_key,
                base_url=base_url,
                check_embedding_ctx_length=False,
            )
        return OpenAIEmbeddings(
            api_key=dashscope_key,
            base_url=settings.dashscope_base_url,
            model=settings.dashscope_embedding_model,
            check_embedding_ctx_length=False,
        )

    @staticmethod
    def _get_bge():
        """BGE 本地模型（预留接口）。

        实际使用需下载权重，例如 BAAI/bge-small-zh-v1.5。
        通过 HuggingFaceEmbeddings 加载。
        """
        try:
            from langchain_huggingface import HuggingFaceEmbeddings
        except ImportError as e:
            raise HTTPException(
                status_code=500,
                detail="BGE 向量模型需要安装 langchain-huggingface 与 sentence-transformers",
            ) from e
        return HuggingFaceEmbeddings(
            model_name="BAAI/bge-small-zh-v1.5",
            encode_kwargs={"normalize_embeddings": True},
        )

    @staticmethod
    def _get_m3e():
        """m3e 本地模型（预留接口）。"""
        try:
            from langchain_huggingface import HuggingFaceEmbeddings
        except ImportError as e:
            raise HTTPException(
                status_code=500,
                detail="m3e 向量模型需要安装 langchain-huggingface 与 sentence-transformers",
            ) from e
        return HuggingFaceEmbeddings(
            model_name="moka-ai/m3e-small",
            encode_kwargs={"normalize_embeddings": True},
        )
