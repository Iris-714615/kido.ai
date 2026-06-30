from __future__ import annotations

import asyncio
import re
from typing import AsyncGenerator, Protocol, runtime_checkable

from app.core.settings import get_settings
from app.schemas import ChatReply, ExploreAnalysis


OBJECT_KEYWORDS: list[tuple[str, str, str]] = [
    ("猫", "小猫", "SCIENCE"),
    ("狗", "小狗", "SCIENCE"),
    ("鸟", "小鸟", "SCIENCE"),
    ("车", "汽车", "SCIENCE"),
    ("树", "树木", "SCIENCE"),
    ("花", "花朵", "SCIENCE"),
    ("书", "书本", "LANGUAGE"),
    ("字", "文字", "LANGUAGE"),
    ("房子", "房子", "SCIENCE"),
    ("天空", "天空", "SCIENCE"),
]

QUESTION_HINTS = ["为什么", "怎么", "怎样", "什么", "哪里", "谁", "多少"]


@runtime_checkable
class AIProvider(Protocol):
    async def build_chat_reply(
        self,
        message: str,
        memory_summary: str,
        child_nickname: str,
        child_age: int,
    ) -> ChatReply: ...

    async def stream_chat_reply(
        self,
        message: str,
        child_nickname: str,
        child_age: int,
        child_id: int | None = None,
    ) -> AsyncGenerator[str, None]: ...

    async def build_explore_analysis(
        self,
        file_name: str,
        content_type: str,
        file_size: int,
        file_url: str,
        child_nickname: str,
        child_age: int,
    ) -> ExploreAnalysis: ...

    async def build_growth_report(
        self,
        system_prompt: str,
        user_prompt: str,
    ) -> str: ...

class FallbackProvider:
    def infer_object_name(self, file_name: str, content_type: str) -> tuple[str, str]:
        lowered = file_name.lower()
        for keyword, object_name, dimension in OBJECT_KEYWORDS:
            if keyword in file_name or keyword in lowered:
                return object_name, dimension
        if content_type.startswith("video/"):
            return "视频片段", "SCIENCE"
        if content_type.startswith("image/"):
            return "未知物体", "SCIENCE"
        return "未知内容", "LANGUAGE"

    async def build_explore_analysis(
        self,
        file_name: str,
        content_type: str,
        file_size: int,
        file_url: str,
        child_nickname: str,
        child_age: int,
    ) -> ExploreAnalysis:
        object_name, dimension = self.infer_object_name(file_name, content_type)
        fact_map = {
            "SCIENCE": f"你发现的{object_name}有自己的形状、颜色和用途，仔细观察时就像在读一本自然故事书。",
            "LANGUAGE": f"{object_name}常常和名字、标记、故事联系在一起，观察它能帮助你认识更多词语。",
            "HISTORY": f"{object_name}背后通常藏着时间和人们生活方式的变化。",
            "HABIT": f"观察{object_name}的时候，慢慢看、认真想，是很棒的探索习惯。",
        }
        score = max(10, min(50, 12 + file_size // 60_000))
        if child_age <= 5:
            score = max(10, score - 2)
        if "视频" in object_name:
            score = min(50, score + 4)
        scientific_fact = (
            f"{child_nickname}，"
            + fact_map.get(dimension, fact_map["SCIENCE"])
        )
        return ExploreAnalysis(
            object_name=object_name,
            scientific_fact=scientific_fact,
            growth_dimension=dimension,
            score_delta=score,
        )

    def _pick_memory_sentence(self, memory_summary: str) -> str:
        lines = [line.strip() for line in memory_summary.splitlines() if line.strip()]
        return lines[0] if lines else "我正在认真听你说。"

    async def build_chat_reply(
        self,
        message: str,
        memory_summary: str,
        child_nickname: str,
        child_age: int = 6,
    ) -> ChatReply:
        first_memory_line = self._pick_memory_sentence(memory_summary)
        lower_message = message.lower()
        has_question = any(hint in message for hint in QUESTION_HINTS) or "?" in message or "？" in message

        if "为什么" in message or "why" in lower_message:
            body = "这是一个很棒的问题。我们可以先观察现象，再一步一步找原因，我会陪你一起想。"
        elif "再说" in message or "继续" in message:
            body = "好，我们继续往下看。"
        elif "谢谢" in message or "thank" in lower_message:
            body = "不客气，我最喜欢和你一起探索了。"
        elif has_question:
            body = "我先把你刚才的问题记住，再用你已经发现的线索来回答它。"
        else:
            body = "我听懂啦，我们可以把它变成一个小小的探索任务。"

        reply = f"{child_nickname}，{body}\n\n我记得：{first_memory_line}"
        if "探索" in message or "看" in message:
            follow_up = "你可以再告诉我你看到了什么颜色、形状或者动作。"
        else:
            follow_up = "如果你愿意，我也可以帮你继续追问一个小问题。"
        return ChatReply(message=reply, memory_summary=memory_summary, suggested_follow_up=follow_up)

    async def stream_chat_reply(
        self,
        message: str,
        child_nickname: str,
        child_age: int,
        child_id: int | None = None,
    ) -> AsyncGenerator[str, None]:
        reply = await self.build_chat_reply(message, "", child_nickname, child_age)
        text = reply.message
        # 按字符切分以适配中文（中文无空格），每 2-3 个字符一个 chunk 模拟流式
        for i in range(0, len(text), 2):
            yield text[i : i + 2]
            await asyncio.sleep(0.05)

    async def build_growth_report(
        self,
        system_prompt: str,
        user_prompt: str,
    ) -> str:
        """Fallback 模式：基于规则生成简单分析。"""
        # 从 user_prompt 中提取关键字段，生成模板化分析
        return (
            "## 兴趣分析\n"
            "孩子近期表现出对自然事物的探索兴趣，建议持续鼓励观察行为。\n\n"
            "## 认知发展\n"
            "探索维度分布显示认知面正在拓展，保持当前节奏即可。\n\n"
            "## 引导建议\n"
            "1. 每周安排 2-3 次户外探索，结合拍照记录\n"
            "2. 鼓励孩子用“为什么”提问，并一起寻找答案\n"
            "3. 尝试不同类别的探索，拓展兴趣广度\n"
        )


class LangChainProvider:
    """基于 LangChain + DeepSeek 的 AI Provider。

    使用 langchain_openai.ChatOpenAI 对接 DeepSeek API，
    通过 ChatPromptTemplate + 管道（prompt | llm）编排调用。
    """

    def __init__(self, api_key: str, base_url: str, model: str, temperature: float = 0.7):
        self._api_key = api_key
        self._base_url = base_url
        self._model = model
        self._temperature = temperature

    def _build_llm(self):
        # 延迟导入，避免未安装 langchain 时整体加载失败
        from langchain_openai import ChatOpenAI

        return ChatOpenAI(
            model=self._model,
            api_key=self._api_key,
            base_url=self._base_url,
            temperature=self._temperature,
        )

    def _build_chat_chain(self, system_prompt: str):
        from langchain_core.prompts import ChatPromptTemplate

        prompt = ChatPromptTemplate.from_messages([
            ("system", system_prompt),
            ("human", "{input}"),
        ])
        return prompt | self._build_llm()

    async def build_growth_report(
        self,
        system_prompt: str,
        user_prompt: str,
    ) -> str:
        """使用 LangChain 链式调用 DeepSeek 生成成长报告。"""
        import asyncio

        chain = self._build_chat_chain(system_prompt)
        # ChatOpenAI.invoke 是同步方法，放到线程池执行避免阻塞事件循环
        response = await asyncio.to_thread(
            chain.invoke, {"input": user_prompt}
        )
        # LangChain 的 AIMessage 对象，content 为文本
        return getattr(response, "content", str(response))

    async def build_chat_reply(
        self,
        message: str,
        memory_summary: str,
        child_nickname: str = "小朋友",
        child_age: int = 6,
    ) -> ChatReply:
        """使用 LangChain + LLM 生成儿童聊天回复"""
        import asyncio
        from langchain_core.prompts import ChatPromptTemplate

        system_prompt = (
            f"你是一个面向儿童的 AI 探索伙伴，名字叫「探索小助手」。"
            f"你正在和 {child_age} 岁的孩子「{child_nickname}」聊天。"
            f"\n回答要求：\n"
            f"- 语言简单生动，适合{child_age}岁儿童理解\n"
            f"- 用比喻、拟人等修辞让回答有趣\n"
            f"- 回答控制在150字以内\n"
            f"- 保持温暖鼓励的语气\n"
            f"- 如果孩子问科学问题，尽量用知识回答\n"
            f"{f'\n关于孩子的记忆：\n{memory_summary}' if memory_summary.strip() else ''}"
        )

        prompt = ChatPromptTemplate.from_messages([
            ("system", system_prompt),
            ("human", "{input}"),
        ])
        chain = prompt | self._build_llm()
        response = await asyncio.to_thread(chain.invoke, {"input": message})
        text = getattr(response, "content", str(response))

        return ChatReply(
            message=text,
            memory_summary=memory_summary or "",
            suggested_follow_up="你还想聊什么呢？",
        )

    async def stream_chat_reply(
        self,
        message: str,
        child_nickname: str,
        child_age: int,
        child_id: int | None = None,
    ) -> AsyncGenerator[str, None]:
        """使用 LangChain + LLM 流式生成儿童聊天回复"""
        from langchain_core.prompts import ChatPromptTemplate

        system_prompt = (
            f"你是一个面向儿童的 AI 探索伙伴，名字叫「探索小助手」。"
            f"你正在和 {child_age} 岁的孩子「{child_nickname}」聊天。"
            f"\n回答要求：\n"
            f"- 语言简单生动，适合{child_age}岁儿童理解\n"
            f"- 用比喻、拟人等修辞让回答有趣\n"
            f"- 回答控制在150字以内\n"
            f"- 保持温暖鼓励的语气\n"
            f"- 如果孩子问科学问题，尽量用知识回答"
        )

        prompt = ChatPromptTemplate.from_messages([
            ("system", system_prompt),
            ("human", "{input}"),
        ])
        chain = prompt | self._build_llm()

        # 同步调用 stream，在线程池中执行避免阻塞事件循环
        import queue, threading

        result_queue: queue.Queue = queue.Queue()

        def _worker():
            try:
                for chunk in chain.stream({"input": message}):
                    if hasattr(chunk, "content") and chunk.content:
                        result_queue.put(chunk.content)
                result_queue.put(None)  # 结束标记
            except Exception as e:
                result_queue.put(e)

        thread = threading.Thread(target=_worker, daemon=True)
        thread.start()

        while True:
            try:
                item = result_queue.get(timeout=0.1)
                if item is None:
                    break
                if isinstance(item, Exception):
                    raise item
                yield item
                await asyncio.sleep(0.02)
            except queue.Empty:
                await asyncio.sleep(0.01)

    async def build_explore_analysis(
        self,
        file_name: str,
        content_type: str,
        file_size: int,
        file_url: str,
        child_nickname: str,
        child_age: int,
    ) -> ExploreAnalysis:
        return await FallbackProvider().build_explore_analysis(
            file_name, content_type, file_size, file_url, child_nickname, child_age
        )


_coze_adapter = None


def get_coze_adapter():
    global _coze_adapter
    if _coze_adapter is None:
        from app.services.coze_adapter import CozeAdapter, CozeConfig
        
        settings = get_settings()
        if not settings.coze_api_key:
            raise RuntimeError("Coze API key not configured")
        config = CozeConfig(
            api_key=settings.coze_api_key,
            base_url=settings.coze_api_base,
            timeout=settings.coze_timeout,
            bot_id=settings.coze_bot_id,
            user_id_prefix=settings.coze_user_id_prefix,
            chat_workflow_id=settings.coze_chat_workflow_id,
            explore_workflow_id=settings.coze_explore_workflow_id,
            summary_workflow_id=settings.coze_summary_workflow_id,
        )
        _coze_adapter = CozeAdapter(config)
    return _coze_adapter


def get_ai_provider() -> AIProvider:
    settings = get_settings()
    import os
    # 优先使用 LangChain + 千问（DashScope，OpenAI 兼容模式）
    dashscope_key = settings.dashscope_api_key or os.getenv("DASHSCOPE_API_KEY")
    if settings.ai_provider == "langchain" and dashscope_key:
        return LangChainProvider(
            api_key=dashscope_key,
            base_url=settings.dashscope_base_url,
            model=settings.dashscope_model,
            temperature=settings.dashscope_temperature,
        )
    # 其次 LangChain + DeepSeek
    if settings.ai_provider == "langchain" and settings.deepseek_api_key:
        return LangChainProvider(
            api_key=settings.deepseek_api_key,
            base_url=settings.deepseek_base_url,
            model=settings.deepseek_model,
            temperature=settings.deepseek_temperature,
        )
    if settings.ai_provider == "coze" and settings.coze_api_key:
        return get_coze_adapter()
    return FallbackProvider()


async def build_chat_reply(
    message: str,
    memory_summary: str,
    child_nickname: str,
    child_age: int = 6,
) -> ChatReply:
    provider = get_ai_provider()
    return await provider.build_chat_reply(message, memory_summary, child_nickname, child_age)


async def stream_chat_reply(
    message: str,
    child_nickname: str,
    child_age: int,
    child_id: int | None = None,
) -> AsyncGenerator[str, None]:
    provider = get_ai_provider()
    async for chunk in provider.stream_chat_reply(message, child_nickname, child_age, child_id):
        yield chunk


async def build_explore_analysis(
    file_name: str,
    content_type: str,
    file_size: int,
    file_url: str,
    child_nickname: str,
    child_age: int,
) -> ExploreAnalysis:
    provider = get_ai_provider()
    return await provider.build_explore_analysis(
        file_name, content_type, file_size, file_url, child_nickname, child_age
    )


async def build_growth_report(system_prompt: str, user_prompt: str) -> str:
    provider = get_ai_provider()
    return await provider.build_growth_report(system_prompt, user_prompt)













