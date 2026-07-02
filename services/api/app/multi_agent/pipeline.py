"""LangGraph 状态机流水线（对应设计规范第五章）。

用纯 LangGraph 还原 deepagents 的编排能力：
  - 并发创作：asyncio.gather 同时跑 story_writer + image_prompt_gen
  - HITL：interrupt_before=["human_review"]
  - 自动修订回流：revision_count 循环，超限强制拒绝
  - checkpointer：MemorySaver 跨节点状态持久化
"""
from __future__ import annotations

import asyncio
import logging
from typing import Annotated, Optional, TypedDict

import operator
from langchain_core.messages import BaseMessage, HumanMessage
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, StateGraph

from app.multi_agent import agents, persistence
from app.multi_agent.schemas import StoryMetadata

logger = logging.getLogger(__name__)

MAX_REVISION_ROUNDS = 3
SAFETY_PASS_THRESHOLD = 90
SAFETY_REVIEW_THRESHOLD = 70


class StoryPipelineState(TypedDict, total=False):
    messages: Annotated[list[BaseMessage], operator.add]
    story_id: str
    request: dict
    blueprint: Optional[dict]
    story_content: Optional[str]
    image_prompts: Optional[dict]
    safety_report: Optional[dict]
    pipeline_stage: str
    revision_count: int
    reviewer_decision: Optional[str]
    reviewer_comment: Optional[str]
    error: Optional[str]


# ── 节点 ──────────────────────────────────────────────────
async def plan_story_node(state: StoryPipelineState):
    """规划阶段：解析创意 → 产出 StoryBlueprint。"""
    req = state["request"]
    story_id = state["story_id"]
    blueprint = await agents.plan_story_blueprint(
        story_prompt=req["story_prompt"],
        target_age=req.get("target_age", "6-10"),
        preferred_theme=req.get("preferred_theme"),
        story_id=story_id,
    )
    persistence.save_metadata(StoryMetadata(
        story_id=story_id,
        title=blueprint.title,
        target_age=blueprint.target_age,
        status="creating",
        revision_count=0,
    ))
    return {
        "blueprint": blueprint.model_dump(),
        "pipeline_stage": "planning_done",
        "messages": [HumanMessage(content=f"故事骨架已规划：《{blueprint.title}》")],
    }


async def launch_creation_node(state: StoryPipelineState):
    """并发创作阶段：同时跑 story_writer + image_prompt_gen。"""
    from app.multi_agent.schemas import StoryBlueprint
    blueprint = StoryBlueprint(**state["blueprint"])

    # asyncio.gather 等价 deepagents AsyncSubAgent 并发委派
    story_text, image_set = await asyncio.gather(
        agents.run_story_writer(blueprint),
        agents.run_image_prompt_gen(blueprint),
    )
    persistence.save_story_text(state["story_id"], story_text)
    persistence.save_image_prompts(state["story_id"], image_set.model_dump())

    return {
        "story_content": story_text,
        "image_prompts": image_set.model_dump(),
        "pipeline_stage": "creation_done",
        "messages": [HumanMessage(content="故事正文与配图 Prompt 已生成。")],
    }


async def run_safety_check_node(state: StoryPipelineState):
    """安全审核阶段：四维审核，输出 SafetyReport。"""
    report = await agents.run_safety_check(
        story_text=state["story_content"],
        target_age=state["request"].get("target_age", "6-10"),
    )
    report_dict = report.model_dump()
    persistence.save_safety_report(state["story_id"], report_dict)

    meta = persistence.load_metadata(state["story_id"])
    if meta:
        meta.safety_score = report.overall_score
        meta.risk_level = report.risk_level
        persistence.save_metadata(meta)

    return {
        "safety_report": report_dict,
        "pipeline_stage": "safety_checking",
        "messages": [HumanMessage(content=(
            f"安全审核完成：得分 {report.overall_score}，等级 {report.risk_level}。"
        ))],
    }


async def human_review_node(state: StoryPipelineState):
    """HITL 节点：interrupt_before 会在此前暂停，恢复时决策已注入。"""
    decision = state.get("reviewer_decision", "reject")
    comment = state.get("reviewer_comment", "")
    return {
        "pipeline_stage": "reviewed",
        "messages": [HumanMessage(content=f"人工审核决策：{decision}（{comment}）")],
    }


async def revise_story_node(state: StoryPipelineState):
    """修订阶段：将审核意见回流，重新生成故事。"""
    report = state.get("safety_report") or {}
    suggestion = report.get("suggestion", "请优化内容安全与儿童友好度。")
    from app.multi_agent.schemas import StoryBlueprint
    blueprint = StoryBlueprint(**state["blueprint"])

    # 将修订建议注入 writer 重写
    from langchain_core.messages import HumanMessage, SystemMessage
    from app.multi_agent.prompts import STORY_WRITER_SYSTEM_PROMPT
    from app.services.langchain_rag.core.llm import LLMFactory
    llm = LLMFactory.get_llm(temperature=0.7)
    messages = [
        SystemMessage(content=STORY_WRITER_SYSTEM_PROMPT),
        HumanMessage(content=(
            f"原故事骨架：\n{blueprint.model_dump_json(indent=2)}\n\n"
            f"审核修改建议：\n{suggestion}\n\n"
            f"请据此重新撰写完整故事正文。"
        )),
    ]
    resp = await llm.ainvoke(messages)
    new_text = resp.content
    persistence.save_story_text(state["story_id"], new_text)

    return {
        "story_content": new_text,
        "revision_count": state.get("revision_count", 0) + 1,
        "pipeline_stage": "revising",
        "messages": [HumanMessage(content=f"已按建议修订（第 {state.get('revision_count', 0) + 1} 轮）。")],
    }


async def publish_story_node(state: StoryPipelineState):
    """发布阶段：更新元数据状态为 published。"""
    meta = persistence.load_metadata(state["story_id"])
    if meta:
        meta.status = "published"
        persistence.save_metadata(meta)
    return {
        "pipeline_stage": "published",
        "messages": [HumanMessage(content="绘本已发布。")],
    }


async def reject_story_node(state: StoryPipelineState):
    """拒绝阶段：记录原因，通知家长。"""
    meta = persistence.load_metadata(state["story_id"])
    if meta:
        meta.status = "rejected"
        persistence.save_metadata(meta)
    return {
        "pipeline_stage": "rejected",
        "messages": [HumanMessage(content="绘本已被拒绝。")],
    }


# ── 路由 ──────────────────────────────────────────────────
def safety_routing(state: StoryPipelineState) -> str:
    report = state.get("safety_report") or {}
    return report.get("risk_level", "BLOCK")


def human_review_routing(state: StoryPipelineState) -> str:
    return state.get("reviewer_decision", "reject")


def check_revision_limit(state: StoryPipelineState) -> str:
    if state.get("revision_count", 0) >= MAX_REVISION_ROUNDS:
        return "force_reject"
    return "continue"


# ── 图构建 ────────────────────────────────────────────────
_compiled_cache: dict = {}


def build_story_pipeline():
    """构建并编译流水线图（单例缓存）。"""
    if "graph" in _compiled_cache:
        return _compiled_cache["graph"]

    graph = StateGraph(StoryPipelineState)

    graph.add_node("plan_story", plan_story_node)
    graph.add_node("launch_creation", launch_creation_node)
    graph.add_node("run_safety_check", run_safety_check_node)
    graph.add_node("human_review", human_review_node)
    graph.add_node("revise_story", revise_story_node)
    graph.add_node("publish_story", publish_story_node)
    graph.add_node("reject_story", reject_story_node)

    graph.set_entry_point("plan_story")
    graph.add_edge("plan_story", "launch_creation")
    graph.add_edge("launch_creation", "run_safety_check")

    graph.add_conditional_edges(
        "run_safety_check", safety_routing,
        {"PASS": "publish_story", "REVIEW": "human_review", "BLOCK": "reject_story"},
    )
    graph.add_conditional_edges(
        "human_review", human_review_routing,
        {"approve": "publish_story", "revise": "revise_story", "reject": "reject_story"},
    )
    graph.add_conditional_edges(
        "revise_story", check_revision_limit,
        {"continue": "run_safety_check", "force_reject": "reject_story"},
    )

    graph.add_edge("publish_story", END)
    graph.add_edge("reject_story", END)

    compiled = graph.compile(
        checkpointer=MemorySaver(),
        interrupt_before=["human_review"],   # HITL 暂停点
    )
    _compiled_cache["graph"] = compiled
    return compiled


def get_pipeline():
    """获取流水线实例。"""
    return build_story_pipeline()
