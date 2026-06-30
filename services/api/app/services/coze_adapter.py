from __future__ import annotations

import json
from dataclasses import dataclass
from typing import AsyncGenerator, Optional

import httpx
from cozepy import (
    AsyncCoze,
    ChatEventType,
    Message,
    TokenAuth,
)

from app.core.settings import get_settings
from app.schemas import ChatReply, ExploreAnalysis


@dataclass(slots=True)
class CozeConfig:
    api_key: str
    base_url: str = "https://api.coze.cn"
    timeout: int = 30
    bot_id: Optional[str] = None
    user_id_prefix: str = "kidoai-child-"
    chat_workflow_id: str = "kidoai-chat-reply"
    explore_workflow_id: str = "kidoai-explore-analysis"
    summary_workflow_id: str = "kidoai-memory-summary"


class CozeAdapter:
    def __init__(self, config: CozeConfig):
        self.config = config
        self.client = AsyncCoze(
            auth=TokenAuth(token=config.api_key),
            base_url=config.base_url,
        )

    async def _call_workflow(self, workflow_id: str, inputs: dict) -> dict:
        async with httpx.AsyncClient(
            base_url=self.config.base_url,
            headers={
                "Authorization": f"Bearer {self.config.api_key}",
                "Content-Type": "application/json",
            },
            timeout=self.config.timeout,
        ) as client:
            response = await client.post(f"/v1/workflows/{workflow_id}/execute", json={"inputs": inputs})
            response.raise_for_status()
            result = response.json()
            if result.get("code") == 0:
                return result.get("data", {})
            raise RuntimeError(f"Coze workflow failed: {result.get('msg', 'Unknown error')}")

    async def build_chat_reply(
        self,
        message: str,
        memory_summary: str,
        child_nickname: str,
        child_age: int,
    ) -> ChatReply:
        inputs = {
            "user_message": message,
            "memory_summary": memory_summary,
            "child_nickname": child_nickname,
            "child_age": child_age,
        }
        outputs = await self._call_workflow(self.config.chat_workflow_id, inputs)
        # outputs 可能是 JSON 字符串或 dict
        if isinstance(outputs, str):
            outputs = json.loads(outputs)
        return ChatReply(
            message=outputs.get("reply_message", ""),
            memory_summary=outputs.get("memory_summary", memory_summary),
            suggested_follow_up=outputs.get("suggested_follow_up", ""),
        )

    async def stream_chat_reply(
        self,
        message: str,
        child_nickname: str,
        child_age: int,
        child_id: Optional[int] = None,
    ) -> AsyncGenerator[str, None]:
        if not self.config.bot_id:
            raise RuntimeError("Coze bot_id not configured")

        user_id = f"{self.config.user_id_prefix}{child_id or 'guest'}"

        async for event in self.client.chat.stream(
            bot_id=self.config.bot_id,
            user_id=user_id,
            additional_messages=[
                Message.build_user_question_text(message),
            ],
        ):
            if event.event == ChatEventType.CONVERSATION_MESSAGE_DELTA:
                content = event.message.content
                if content:
                    yield content
            elif event.event == ChatEventType.CONVERSATION_CHAT_COMPLETED:
                break

    async def build_explore_analysis(
        self,
        file_name: str,
        content_type: str,
        file_size: int,
        file_url: str,
        child_nickname: str,
        child_age: int,
    ) -> ExploreAnalysis:
        inputs = {
            "file_name": file_name,
            "content_type": content_type,
            "file_size": file_size,
            "file_url": file_url,
            "child_nickname": child_nickname,
            "child_age": child_age,
        }
        outputs = await self._call_workflow(self.config.explore_workflow_id, inputs)
        if isinstance(outputs, str):
            outputs = json.loads(outputs)
        return ExploreAnalysis(
            object_name=outputs.get("object_name", "未知物体"),
            scientific_fact=outputs.get("scientific_fact", ""),
            growth_dimension=outputs.get("growth_dimension", "SCIENCE"),
            score_delta=outputs.get("score_delta", 10),
        )

    async def build_memory_summary(
        self,
        child_id: int,
        memory_events: list[dict],
        recent_chats: list[dict],
        explore_records: list[dict],
    ) -> str:
        inputs = {
            "child_id": child_id,
            "memory_events": memory_events,
            "recent_chats": recent_chats,
            "explore_records": explore_records,
        }
        outputs = await self._call_workflow(self.config.summary_workflow_id, inputs)
        if isinstance(outputs, str):
            outputs = json.loads(outputs)
        return outputs.get("summary", "")

    async def close(self):
        # 关闭 AsyncCoze 内部 httpx 连接池，避免连接泄漏
        close_fn = getattr(self.client, "close", None)
        if close_fn is not None:
            result = close_fn()
            if hasattr(result, "__await__"):
                await result
