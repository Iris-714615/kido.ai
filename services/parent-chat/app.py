"""KidoAI 家长端 AI 育儿助手 —— Gradio + LlamaIndex + LangSmith。

技术栈：
- LlamaIndex：向量索引 + 多轮对话引擎（CondensePlusContextChatEngine）
- DashScope（通义千问 qwen-plus）：LLM + text-embedding-v2 嵌入
- LangSmith：全链路追踪（检索/LLM调用/Token用量/延迟可视化）
- Gradio ChatInterface：Web 聊天 UI（自带流式打字效果）

启动：
    python app.py
访问：
    http://127.0.0.1:7860

LangSmith 追踪：
    在 .env 中设置 LANGCHAIN_TRACING_V2=true 和 LANGCHAIN_API_KEY 后，
    所有 RAG 调用（embedding/检索/LLM生成）自动上报到 LangSmith 控制台，
    可在 https://smith.langchain.com 查看完整调用链路、Token 用量和延迟。
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Generator

# ── 加载项目根目录 .env ───────────────────────────────────
from dotenv import load_dotenv

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(_PROJECT_ROOT / ".env")

# ── LlamaIndex 全局配置 ───────────────────────────────────
import gradio as gr
from llama_index.core import (
    Settings,
    SimpleDirectoryReader,
    VectorStoreIndex,
)
from llama_index.core.chat_engine import CondensePlusContextChatEngine
from llama_index.core.llms import ChatMessage, MessageRole
from llama_index.embeddings.dashscope import (
    DashScopeEmbedding,
    DashScopeTextEmbeddingModels,
)
from llama_index.llms.dashscope import (
    DashScope,
    DashScopeGenerationModels,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("parent-chat")

# ── 配置 ──────────────────────────────────────────────────
DASHSCOPE_API_KEY = os.getenv("DASHSCOPE_API_KEY", "")
LLM_MODEL = os.getenv("PARENT_CHAT_LLM_MODEL", DashScopeGenerationModels.QWEN_PLUS)
EMBED_MODEL = DashScopeTextEmbeddingModels.TEXT_EMBEDDING_V2
KB_DIR = Path(__file__).parent / "data" / "parenting_kb"
PERSIST_DIR = Path(__file__).parent / "data" / "storage"
HOST = os.getenv("PARENT_CHAT_HOST", "0.0.0.0")
PORT = int(os.getenv("PARENT_CHAT_PORT", "7860"))

# ── LangSmith 追踪配置 ────────────────────────────────────
LANGSMITH_TRACING = os.getenv("LANGCHAIN_TRACING_V2", "false").lower() == "true"
LANGSMITH_API_KEY = os.getenv("LANGCHAIN_API_KEY", "")
LANGSMITH_PROJECT = os.getenv("LANGCHAIN_PROJECT", "kidoai-parent-chat")

# 家长端专属系统提示词
PARENT_SYSTEM_PROMPT = (
    "你是 KidoAI 家长端 AI 育儿助手，专注于为 3-6 岁儿童的家长提供专业、温暖的育儿指导。\n\n"
    "回答原则：\n"
    "1. 严格基于提供的育儿知识库内容作答，不编造未经证实的信息\n"
    "2. 态度温暖、有同理心，理解家长的焦虑和困惑\n"
    "3. 建议具体可操作，避免空泛说教\n"
    "4. 涉及健康医疗问题时，提醒家长咨询专业医生\n"
    "5. 尊重不同家庭的教育理念，不评判对错\n"
    "6. 若问题超出知识库范围，坦诚告知并建议查阅更权威的资料\n\n"
    "以下是从育儿知识库检索到的参考资料：\n"
    "{context_str}\n\n"
    "请基于上述资料回答家长的问题。"
)


def setup_langsmith() -> None:
    """配置 LangSmith 全链路追踪。

    启用后，LlamaIndex 的每一次 embedding 调用、向量检索、LLM 生成
    都会自动上报到 LangSmith 控制台，支持可视化查看：
    - 检索的 query 和召回的 chunks
    - LLM 的完整 prompt 和 response
    - Token 用量和延迟
    - 多轮对话的完整链路

    集成方式：
    1. 环境变量 LANGCHAIN_TRACING_V2=true 启用 LangChain 底层追踪
    2. langsmith SDK 的 @traceable 装饰器追踪顶层对话函数
    3. LlamaIndex CallbackManager 桥接到 LangSmith
    """
    if not LANGSMITH_TRACING:
        logger.info("LangSmith 追踪未启用（LANGCHAIN_TRACING_V2=false）")
        return

    if not LANGSMITH_API_KEY:
        logger.warning(
            "LANGCHAIN_TRACING_V2=true 但未配置 LANGCHAIN_API_KEY，"
            "请在 .env 中设置后重试。追踪功能将不生效。"
        )
        return

    # 确保环境变量已设置（langsmith SDK 依赖这些）
    os.environ.setdefault("LANGCHAIN_TRACING_V2", "true")
    os.environ.setdefault("LANGCHAIN_PROJECT", LANGSMITH_PROJECT)

    # 注册 LlamaIndex → LangSmith 桥接回调
    from llama_index.core.callbacks import CallbackManager, CBEventType, base_handler

    class LangSmithBridgeHandler(base_handler.BaseCallbackHandler):
        """LlamaIndex 回调桥接到 LangSmith 的实现。

        通过 langsmith Client 把 LlamaIndex 的检索和 LLM 事件
        作为嵌套 run 上报到 LangSmith，在控制台可视化查看完整链路。
        """

        def __init__(self, project_name: str, api_key: str) -> None:
            from langsmith import Client
            super().__init__(
                event_starts_to_ignore=[],
                event_ends_to_ignore=[],
            )
            self.client = Client(api_key=api_key)
            self.project_name = project_name
            self._runs: list = []

        def on_event_start(self, event_type, payload, **kwargs):
            try:
                name = event_type.value if hasattr(event_type, "value") else str(event_type)
                run = self.client.create_run(
                    name=name,
                    run_type="llm" if "llm" in name.lower() else "tool",
                    inputs=payload or {},
                    project_name=self.project_name,
                )
                self._runs.append(run)
            except Exception as e:
                logger.debug("LangSmith on_event_start skipped: %s", e)

        def on_event_end(self, event_type, payload, **kwargs):
            try:
                if self._runs:
                    run = self._runs.pop()
                    self.client.update_run(
                        run.id,
                        outputs=payload or {},
                    )
            except Exception as e:
                logger.debug("LangSmith on_event_end skipped: %s", e)

        def start_trace(self, trace_id=None):
            pass

        def end_trace(self, trace_id=None, **kwargs):
            pass

    bridge = LangSmithBridgeHandler(LANGSMITH_PROJECT, LANGSMITH_API_KEY)
    Settings.callback_manager = CallbackManager([bridge])
    logger.info(
        "LangSmith 追踪已启用：project=%s, endpoint=%s",
        LANGSMITH_PROJECT,
        os.getenv("LANGCHAIN_ENDPOINT", "https://api.smith.langchain.com"),
    )


def configure_settings() -> None:
    """配置 LlamaIndex 全局 LLM 和 Embedding 模型。"""
    if not DASHSCOPE_API_KEY:
        raise RuntimeError(
            "未配置 DASHSCOPE_API_KEY 环境变量。\n"
            "请在项目根目录 .env 文件中添加：\n"
            "  DASHSCOPE_API_KEY=sk-xxxxxxxxxxxxxxxx\n\n"
            "获取地址：https://dashscope.console.aliyun.com/apiKey"
        )

    # 先配置 LangSmith 追踪（在 LLM/Embedding 调用前注册回调）
    setup_langsmith()

    Settings.llm = DashScope(
        model_name=LLM_MODEL,
        api_key=DASHSCOPE_API_KEY,
        temperature=0.7,
        max_tokens=2048,
    )
    Settings.embed_model = DashScopeEmbedding(
        model_name=EMBED_MODEL,
        api_key=DASHSCOPE_API_KEY,
    )
    # 控制向量检索参数
    Settings.chunk_size = 512
    Settings.chunk_overlap = 50
    Settings.similarity_top_k = 5
    logger.info("LlamaIndex 配置完成：LLM=%s, Embed=%s", LLM_MODEL, EMBED_MODEL)


def build_or_load_index() -> VectorStoreIndex:
    """构建或加载向量索引（首次构建后持久化到磁盘）。"""
    PERSIST_DIR.mkdir(parents=True, exist_ok=True)

    # 已有持久化索引 → 直接加载（启动快）
    if (PERSIST_DIR / "default__vector_store.json").exists():
        from llama_index.core import StorageContext, load_index_from_storage

        logger.info("检测到已有索引，从磁盘加载：%s", PERSIST_DIR)
        storage_context = StorageContext.from_defaults(persist_dir=str(PERSIST_DIR))
        return load_index_from_storage(storage_context)

    # 首次启动：读取育儿知识库 → 构建向量索引
    if not KB_DIR.exists() or not any(KB_DIR.iterdir()):
        raise RuntimeError(
            f"育儿知识库目录为空：{KB_DIR}，请放入育儿相关文档后再启动。"
        )

    logger.info("首次构建向量索引，加载知识库：%s", KB_DIR)
    documents = SimpleDirectoryReader(str(KB_DIR)).load_data()
    logger.info("加载到 %d 个文档，开始向量化...", len(documents))

    index = VectorStoreIndex.from_documents(documents)
    index.storage_context.persist(persist_dir=str(PERSIST_DIR))
    logger.info("索引构建并持久化完成。")
    return index


def create_chat_engine(index: VectorStoreIndex) -> CondensePlusContextChatEngine:
    """创建多轮对话引擎（CondensePlusContext 模式）。

    工作流程：
    1. 把聊天历史 + 新问题浓缩成一个独立问题
    2. 用该问题检索向量库得到相关上下文
    3. 把上下文 + 系统提示词 + 问题交给 LLM 生成回答
    """
    retriever = index.as_retriever(similarity_top_k=Settings.similarity_top_k)

    chat_engine = CondensePlusContextChatEngine.from_defaults(
        retriever=retriever,
        system_prompt=PARENT_SYSTEM_PROMPT,
        verbose=False,
        streaming=True,   # 启用流式输出
    )
    return chat_engine


# ── 全局 chat_engine（应用启动时初始化一次）──────────────────
_chat_engine: CondensePlusContextChatEngine | None = None


def get_chat_engine() -> CondensePlusContextChatEngine:
    global _chat_engine
    if _chat_engine is None:
        configure_settings()
        index = build_or_load_index()
        _chat_engine = create_chat_engine(index)
        logger.info("多轮对话引擎初始化完成。")
    return _chat_engine


def chat_respond(message: str, history: list) -> Generator[str, None, None]:
    """Gradio ChatInterface 的回调函数（流式输出）。

    Args:
        message: 用户当前提问
        history: Gradio 维护的对话历史 [(user, assistant), ...]

    Yields:
        逐步生成的回答片段（打字机效果）
    """
    if not message.strip():
        yield "请输入您的问题～"
        return

    try:
        engine = get_chat_engine()

        # 将 Gradio 历史格式转为 LlamaIndex ChatMessage 列表
        chat_history: list[ChatMessage] = []
        for user_msg, assistant_msg in history:
            if user_msg:
                chat_history.append(
                    ChatMessage(role=MessageRole.USER, content=user_msg)
                )
            if assistant_msg:
                chat_history.append(
                    ChatMessage(role=MessageRole.ASSISTANT, content=assistant_msg)
                )

        # 流式生成回答
        response = engine.stream_chat(message, chat_history=chat_history)

        accumulated = ""
        for token in response.response_gen:
            accumulated += token
            yield accumulated

    except Exception as e:
        logger.exception("对话生成失败")
        yield f"抱歉，回答生成时出现错误：{e}\n请稍后重试，或检查 DASHSCOPE_API_KEY 配置。"


# ── Gradio Web UI ─────────────────────────────────────────
def build_ui() -> gr.Blocks:
    """构建 Gradio 聊天界面。"""
    with gr.Blocks(
        title="KidoAI 家长端 AI 育儿助手",
        theme=gr.themes.Soft(primary_hue="blue", secondary_hue="cyan"),
        css="""
        .header-banner {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white; padding: 20px; border-radius: 12px;
            text-align: center; margin-bottom: 16px;
        }
        .header-banner h1 { margin: 0; font-size: 24px; }
        .header-banner p { margin: 8px 0 0; opacity: 0.9; font-size: 14px; }
        """,
    ) as app:
        gr.HTML("""
        <div class="header-banner">
            <h1>KidoAI 家长端 AI 育儿助手</h1>
            <p>基于 LlamaIndex + 通义千问 · 为 3-6 岁儿童家长提供专业育儿指导</p>
        </div>
        """)

        chat = gr.ChatInterface(
            fn=chat_respond,
            title="育儿问答",
            description=(
                "你可以问我关于儿童心理发展、早期教育、健康营养、"
                "行为管理、睡眠习惯等任何育儿问题。"
            ),
            examples=[
                "3岁孩子不爱吃饭怎么办？",
                "孩子到了4岁还经常发脾气正常吗？",
                "如何培养孩子的阅读习惯？",
                "5岁孩子每天应该睡多长时间？",
                "孩子害怕上幼儿园怎么引导？",
                "如何控制孩子的屏幕时间？",
            ],
            retry_btn="重试",
            undo_btn="撤销",
            clear_btn="清空对话",
            type="messages",
        )

        gr.HTML("""
        <div style="text-align:center; margin-top:16px; color:#888; font-size:12px;">
            本助手提供的建议仅供参考，不替代专业医疗意见。
            涉及健康问题请咨询儿科医生。
        </div>
        """)

    return app


def main() -> None:
    logger.info("启动 KidoAI 家长端 AI 育儿助手 (Gradio port=%d)", PORT)
    app = build_ui()
    app.launch(server_name=HOST, server_port=PORT, share=False)


if __name__ == "__main__":
    main()
