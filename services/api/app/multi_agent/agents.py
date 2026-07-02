"""子 Agent 构建（story_writer / image_prompt_gen / safety_check）。

用纯 LangChain 实现，等价 deepagents 的 AsyncSubAgent + response_format：
  - story_writer: 文本输出
  - image_prompt_gen: with_structured_output(ImagePromptSet)
  - safety_check: with_structured_output(SafetyReport), 低温度保证一致性
"""
from __future__ import annotations

import json
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from app.services.langchain_rag.core.llm import LLMFactory
from app.multi_agent.prompts import (
    IMAGE_PROMPT_SYSTEM_PROMPT,
    SAFETY_CHECK_SYSTEM_PROMPT,
    STORY_WRITER_SYSTEM_PROMPT,
)
from app.multi_agent.schemas import ImagePromptSet, SafetyReport, StoryBlueprint


# ── story_writer ──────────────────────────────────────────
async def run_story_writer(blueprint: StoryBlueprint) -> str:
    """按幕撰写故事正文，返回完整故事文本。"""
    llm = LLMFactory.get_llm(temperature=0.7)
    bp_json = blueprint.model_dump_json(indent=2)
    messages = [
        SystemMessage(content=STORY_WRITER_SYSTEM_PROMPT),
        HumanMessage(content=(
            f"请根据以下故事骨架撰写完整故事正文（按三幕顺序输出，"
            f"目标年龄 {blueprint.target_age} 岁）：\n\n{bp_json}"
        )),
    ]
    resp = await llm.ainvoke(messages)
    return resp.content


# ── image_prompt_gen ──────────────────────────────────────
async def run_image_prompt_gen(blueprint: StoryBlueprint) -> ImagePromptSet:
    """为每幕生成配图 Prompt，返回结构化结果。"""
    llm = LLMFactory.get_llm(temperature=0.7).with_structured_output(ImagePromptSet)
    bp_json = blueprint.model_dump_json(indent=2)
    messages = [
        SystemMessage(content=IMAGE_PROMPT_SYSTEM_PROMPT),
        HumanMessage(content=(
            f"为以下故事的每一幕生成英文配图 Prompt：\n\n{bp_json}\n\n"
            f"story_id 必须使用：{blueprint.story_id}"
        )),
    ]
    result = await llm.ainvoke(messages)
    # 确保 story_id 一致
    result.story_id = blueprint.story_id
    return result


# ── safety_check ──────────────────────────────────────────
async def run_safety_check(story_text: str, target_age: str) -> SafetyReport:
    """对完整故事执行四维安全审核，返回结构化报告。"""
    llm = LLMFactory.get_llm(temperature=0.1).with_structured_output(SafetyReport)
    messages = [
        SystemMessage(content=SAFETY_CHECK_SYSTEM_PROMPT),
        HumanMessage(content=(
            f"请对以下儿童故事（目标年龄 {target_age} 岁）进行四维安全审核，"
            f"严格返回 JSON：\n\n{story_text}"
        )),
    ]
    report: SafetyReport = await llm.ainvoke(messages)
    # 修正：若任何维度命中强制 BLOCK，按规则对齐
    d = report.dimension_scores
    forced_block = (
        d.content_safety <= 40
        or any(f.severity == "critical" and f.type in {"暴力", "色情", "歧视"} for f in report.flags)
    )
    if forced_block:
        report.overall_score = min(report.overall_score, 40)
        report.risk_level = "BLOCK"
        report.auto_decision = "BLOCK"
    return report


# ── orchestrator 规划（产出 StoryBlueprint）─────────────────
async def plan_story_blueprint(
    story_prompt: str,
    target_age: str,
    preferred_theme: str | None,
    story_id: str,
) -> StoryBlueprint:
    """主协调 Agent 规划阶段：解析创意 → 输出 StoryBlueprint。"""
    llm = LLMFactory.get_llm(temperature=0.7).with_structured_output(StoryBlueprint)
    from app.multi_agent.prompts import ORCHESTRATOR_SYSTEM_PROMPT
    messages = [
        SystemMessage(content=ORCHESTRATOR_SYSTEM_PROMPT),
        HumanMessage(content=(
            f"孩子提出的故事开头：{story_prompt}\n"
            f"目标年龄：{target_age} 岁\n"
            f"主题偏好：{preferred_theme or 'adventure'}\n\n"
            f"请规划三幕故事骨架，story_id 必须使用：{story_id}"
        )),
    ]
    blueprint: StoryBlueprint = await llm.ainvoke(messages)
    blueprint.story_id = story_id
    return blueprint
