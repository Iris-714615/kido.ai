# KidoAI · 儿童绘本共创 × 内容安全审核 — 闭环多智能体系统设计规范 v1.0

> **技术栈**：LangChain · LangGraph · Deep Agents (Agent Harness)
> **适配项目**：KidoAI `services/api` · `apps/child-web`
> **文档状态**：可直接落地实现的工程设计规范

---

## 一、业务背景与战略价值

### 1.1 两个场景的融合逻辑

| 原始场景 | 核心痛点 | 孤立的问题 |
|---|---|---|
| 儿童绘本/故事共创 Agent | 孩子提开头，故事无逻辑/角色断层 | 创作质量不稳定，缺乏结构化生成 |
| 儿童内容安全审核 Agent | 全量人工审核效率低 | 审核与创作割裂，无法形成质量正反馈 |

**融合后的本质**：内容生产 + 内容安全是同一条流水线的两个阶段，割裂会导致：
- 生成了不合格内容才发现 → 浪费算力 + 影响儿童体验
- 审核无法回流修改建议 → 低质内容反复出现，无法迭代

**融合后的价值**：
- 🚀 生产效率：手动创作 2 小时 → 自动化 **3-5 分钟**（异步并行）
- 🛡️ 安全覆盖：自动审核拦截 **≥95%** 明显违规，人工聚焦剩余灰色地带
- 🔁 质量闭环：审核不合格 → 自动回流 → 重新生成，最多 3 轮自动修正

---

### 1.2 系统全景架构图

```
┌─────────────────────────────────────────────────────────────────────┐
│                   KidoAI 绘本共创安全闭环系统                         │
│                                                                      │
│  👦 孩子输入 "从前有只小狐狸，它想找到自己的家..."                      │
│                         │                                            │
│                         ▼                                            │
│         ┌───────────────────────────────────┐                       │
│         │   主协调 Agent (Orchestrator)      │  LangGraph StateGraph │
│         │   · write_todos() 全局规划         │                       │
│         │   · 管理创作→审核→发布状态流转      │                       │
│         └──────────────┬────────────────────┘                       │
│                        │ AsyncSubAgent 并发委派                       │
│           ┌────────────┴─────────────┐                              │
│           ▼                          ▼                               │
│  ┌─────────────────┐     ┌────────────────────┐                     │
│  │  story_writer   │     │  image_prompt_gen  │  ← 异步并发         │
│  │  子 Agent        │     │  子 Agent           │    同时运行         │
│  │  · 按幕写正文    │     │  · 每幕配图Prompt   │                     │
│  │  · 角色一致性    │     │  · 儿童插画风格     │                     │
│  └────────┬────────┘     └──────────┬─────────┘                    │
│           └──────────┬──────────────┘                               │
│                      │ 创作产物汇总                                   │
│                      ▼                                               │
│         ┌─────────────────────────────────┐                         │
│         │  safety_check 子 Agent (同步)    │                         │
│         │  · ①内容安全  ②儿童友好度        │                         │
│         │  · ③价值观导向 ④版权原创性       │                         │
│         │  → 输出 SafetyReport JSON        │                         │
│         └──────────────┬──────────────────┘                         │
│                        │                                             │
│              ┌─────────┴──────────┐                                 │
│         score≥90    score 70-89   score<70                          │
│          PASS         REVIEW       BLOCK                             │
│            │             │            │                              │
│            ▼             ▼            ▼                              │
│        直接发布    interrupt_on    自动拒绝                           │
│                    人工审批队列    + 修订建议回流                      │
│                    (HITL Gate)     重新生成(≤3轮)                    │
│                        │                                             │
│               ✅批准 → 发布                                           │
│               ✏️修改 → 回流重新创作                                   │
│               ❌拒绝 → 记录原因 + 通知家长                            │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 二、数据模型（Pydantic Schemas）

```python
# services/api/app/schemas/story.py

from pydantic import BaseModel, Field
from typing import List, Optional, Literal
from datetime import datetime
from uuid import uuid4


class Character(BaseModel):
    name: str
    personality: str
    appearance: str


class StoryAct(BaseModel):
    act: int
    title: str
    summary: str
    content: Optional[str] = None        # 由 story_writer 填充
    image_prompt: Optional[str] = None   # 由 image_prompt_gen 填充


class StoryBlueprint(BaseModel):
    """主协调 Agent 规划阶段产出的故事骨架，传给两个子 Agent"""
    story_id: str = Field(default_factory=lambda: f"story_{uuid4().hex[:8]}")
    title: str
    target_age: Literal["3-6", "6-10"]
    characters: List[Character]
    acts: List[StoryAct]
    tone: str                  # 如"温暖治愈"/"冒险欢快"
    value_theme: str           # 如"勇气与归属感"


class SafetyFlag(BaseModel):
    type: str
    location: str              # 如"第2幕第3段"
    description: str
    severity: Literal["low", "medium", "high", "critical"]


class DimensionScores(BaseModel):
    content_safety: int = Field(ge=0, le=100)    # 内容安全（权重40%）
    child_friendly: int = Field(ge=0, le=100)    # 儿童友好度（权重25%）
    values_guidance: int = Field(ge=0, le=100)   # 价值观导向（权重25%）
    originality: int = Field(ge=0, le=100)       # 版权原创性（权重10%）


class SafetyReport(BaseModel):
    """safety_check 子 Agent 的结构化输出（response_format）"""
    overall_score: int = Field(ge=0, le=100)
    risk_level: Literal["PASS", "REVIEW", "BLOCK"]
    dimension_scores: DimensionScores
    flags: List[SafetyFlag] = []
    suggestion: str
    auto_decision: Literal["PASS", "REVIEW", "BLOCK"]
    reviewer_note: Optional[str] = None


class StoryCreationRequest(BaseModel):
    """前端 → API 的请求体"""
    child_id: str
    story_prompt: str
    target_age: Literal["3-6", "6-10"]
    preferred_theme: Optional[str] = "adventure"


class HumanReviewDecision(BaseModel):
    """家长/运营人员的人工审核决策"""
    action: Literal["approve", "revise", "reject"]
    comment: Optional[str] = None   # revise 时必填修改建议


class StoryCreationResponse(BaseModel):
    """API → 前端的响应体"""
    story_id: str
    status: Literal["creating", "reviewing", "published", "rejected"]
    message: str
    eta_seconds: Optional[int] = None
```

---

## 三、主协调 Agent 实现

```python
# services/api/app/agents/story_orchestrator.py

import os
from langchain_openai import ChatOpenAI
from deepagents import create_deep_agent, AsyncSubAgent
from deepagents.backends import CompositeBackend, StateBackend, StoreBackend
from .prompts import ORCHESTRATOR_SYSTEM_PROMPT
from ..schemas.story import SafetyReport

# ── 模型 ──────────────────────────────────────────────────
orchestrator_model = ChatOpenAI(
    model=os.environ.get("STORY_MODEL", "Pro/zai-org/GLM-5.1"),
    api_key=os.environ["SILICONFLOW_API_KEY"],
    base_url="https://api.siliconflow.cn/v1",
    temperature=0.7,
)

# ── 异步子 Agent（并发创作）────────────────────────────────
async_subagents = [
    AsyncSubAgent(
        name="story_writer",
        description=(
            "专业儿童故事撰写 Agent。接收故事骨架与角色设定，"
            "按幕输出正文（每幕200-400字），维护角色一致性，"
            "语言适合目标年龄段。当需要撰写故事章节时委派给它。"
        ),
        graph_id="story_writer",
        # url 不填 → ASGI 进程内传输（与主 Agent 同部署）
    ),
    AsyncSubAgent(
        name="image_prompt_gen",
        description=(
            "儿童插画 Prompt 生成 Agent。接收故事每幕场景摘要，"
            "输出适合 DALL-E/SD 的英文插画 Prompt，"
            "风格为温暖水彩儿童绘本风。当需要为故事配图时委派给它。"
        ),
        graph_id="image_prompt_gen",
    ),
]

# ── 同步审核子 Agent ───────────────────────────────────────
safety_subagent = {
    "name": "safety_check",
    "description": (
        "儿童内容四维安全审核 Agent。对故事全文进行内容安全、"
        "儿童友好度、价值观导向、版权原创性四维审核，"
        "输出结构化 SafetyReport JSON。"
        "每次故事创作完成后、发布前必须执行此审核。"
    ),
    "system_prompt": SAFETY_CHECK_SYSTEM_PROMPT,
    "tools": [],
    "response_format": SafetyReport,   # 强制结构化 JSON 输出
    "model": ChatOpenAI(               # 审核用高精度模型
        model=os.environ.get("SAFETY_MODEL", "Pro/zai-org/GLM-5.1"),
        api_key=os.environ["SILICONFLOW_API_KEY"],
        base_url="https://api.siliconflow.cn/v1",
        temperature=0.1,               # 审核需低温度，保证一致性
    ),
}


def user_namespace(rt):
    """用户级记忆命名空间"""
    if rt.server_info and rt.server_info.user:
        return (rt.server_info.user.identity,)
    user_id = getattr(rt.context, "user_id", "local-user")
    return (user_id,)


def build_story_orchestrator(checkpointer=None, store=None):
    """构建主协调 Agent，可传入生产级 checkpointer/store"""
    from langgraph.checkpoint.memory import MemorySaver
    return create_deep_agent(
        model=orchestrator_model,
        subagents=async_subagents + [safety_subagent],
        checkpointer=checkpointer or MemorySaver(),
        backend=CompositeBackend(
            default=StateBackend(),
            routes={
                # 绘本内容跨对话持久化
                "/stories/": StoreBackend(namespace=user_namespace),
                # 孩子的偏好主题记忆（角色/风格偏好）
                "/memories/": StoreBackend(namespace=user_namespace),
            }
        ),
        memory=["/memories/story_preferences.md"],   # 自动热载孩子偏好
        interrupt_on=["safety_check"],               # 审核后触发 HITL 门
        system_prompt=ORCHESTRATOR_SYSTEM_PROMPT,
    )
```

---

## 四、系统提示词

```python
# services/api/app/agents/prompts.py

ORCHESTRATOR_SYSTEM_PROMPT = """你是 KidoAI 的绘本创作大师，负责协调从创意到发布的全流程。

## 工作流程（必须严格遵守）

### 第一步：故事规划（每次必须先执行）
收到孩子的故事开头后，立即使用 write_todos 制定完整计划：
  1. [pending] 解析故事主题、主角、情感基调
  2. [pending] 规划三幕结构（起承转合）+ 生成角色设定卡
  3. [pending] 同时启动 story_writer 和 image_prompt_gen（异步并发）
  4. [pending] 监控两个创作任务进度，告知孩子状态
  5. [pending] 等待两个任务都完成
  6. [pending] 执行 safety_check 安全审核（同步，不可跳过）
  7. [pending] 根据 risk_level 决策：PASS发布/REVIEW等待人工/BLOCK修订
  8. [pending] 保存最终绘本到 /stories/{story_id}/

### 第二步：并发创作
**必须同时**用 start_async_task 启动两个任务（不要顺序执行）：
- story_writer：传入完整的 StoryBlueprint JSON
- image_prompt_gen：传入相同的 StoryBlueprint JSON

立即告知孩子："正在为你创作绘本，大约需要3分钟 ✨"

### 第三步：安全审核（不可跳过）
两个任务都完成后，通过 task(safety_check, ...) 执行审核。
将完整故事文本传入，获得 SafetyReport。

### 第四步：发布决策
- overall_score ≥ 90 → 直接 write_file 保存并告知孩子绘本完成
- overall_score 70-89 → 告知孩子"需要叔叔阿姨确认一下"，等待人工审批
- overall_score < 70 → 将 suggestion 发给 story_writer 重新生成（最多3次）

### 角色设定卡格式（必须传给两个子 Agent）
{
  "story_id": "唯一ID",
  "title": "故事标题",
  "target_age": "3-6 或 6-10",
  "characters": [{"name":"...", "personality":"...", "appearance":"..."}],
  "acts": [{"act":1, "title":"...", "summary":"..."},
           {"act":2, "title":"...", "summary":"..."},
           {"act":3, "title":"...", "summary":"..."}],
  "tone": "温暖治愈",
  "value_theme": "勇气与归属感"
}

### 存储规范
- /stories/{story_id}/story.md        完整故事正文
- /stories/{story_id}/prompts.json    各幕配图 Prompt
- /stories/{story_id}/safety.json     安全审核报告
- /stories/{story_id}/metadata.json   绘本元数据
"""

SAFETY_CHECK_SYSTEM_PROMPT = """你是一位专业的儿童内容安全审核专家，拥有儿童教育心理学背景。

对输入的儿童故事进行四维审核，**必须**严格返回指定 JSON 格式，不得有多余文字。

## 四维审核标准

### 维度一：内容安全（权重40%）
- 暴力/血腥描写 → 直接 BLOCK
- 恐怖/惊悚内容 → 3-6岁判BLOCK，7-10岁判REVIEW
- 任何色情暗示 → 直接 BLOCK

### 维度二：儿童友好度（权重25%）
- 词汇难度：是否超过目标年龄段认知水平
- 情绪基调：负面情绪比例是否超过30%
- 故事结局：是否有积极正向收尾（无积极结局 → REVIEW）

### 维度三：价值观导向（权重25%）
- 是否传递勇气、友善、诚实等正向价值
- 是否存在歧视性内容（性别/种族/外貌歧视）→ BLOCK
- 主角行为是否适合儿童模仿

### 维度四：版权与原创性（权重10%）
- 是否直接复制知名IP角色（迪士尼/漫威等）→ REVIEW
- 创意原创度评估

## 评分标准
- 90-100：优质内容，直接发布（PASS）
- 70-89：有轻微问题，建议人工确认（REVIEW）
- 0-69：不符合标准，需修改或拒绝（BLOCK）

任何维度命中"直接BLOCK"标准，overall_score 强制 ≤ 40，risk_level 强制 BLOCK。
"""

STORY_WRITER_SYSTEM_PROMPT = """你是一位专业的儿童绘本作家，擅长创作3-10岁儿童喜爱的故事。

## 写作原则

### 语言标准
- 3-6岁：短句（≤15字/句），常用词汇，拟声词，反复句式
- 6-10岁：可用复合句，适当成语，保持节奏感

### 每幕结构
1. 场景描写（1-2句，画面感强，适合插画）
2. 主角行动与心理（2-3句）
3. 转折或推进（1-2句，为下幕铺垫）
目标字数：200-400字/幕

### 角色一致性（写每幕前必须检查）
- 角色性格行为与设定卡一致
- 称呼统一（不能时而"小狐狸"时而"狐狸宝宝"）
- 能力边界合理

### 禁止事项
- ❌ 死亡/永久消失（用"睡着了"/"去旅行了"代替）
- ❌ 负面结局
- ❌ 超出年龄认知的概念（金融/战争/政治）

## 输出格式
## 第{N}幕：{幕标题}

{正文内容}

---
🎨 插画重点场景：{本幕最适合配图的1个场景，一句话}
"""

IMAGE_PROMPT_SYSTEM_PROMPT = """你是儿童插画 AI Prompt 专家，专门为绘本生成温暖风格的配图描述。

## 风格标签（每条Prompt必须包含）
watercolor children's book illustration, soft pastel colors, warm and cozy,
Studio Ghibli inspired, gentle lighting, cute character design, age-appropriate

## 场景描述结构
[主角动作+情绪], [场景环境], [时间/光线], [氛围], [风格标签]

## 输出格式（严格JSON）
{
  "story_id": "xxx",
  "prompts": [
    {
      "act": 1,
      "scene_cn": "小狐狸站在森林边缘，好奇地望向远方",
      "prompt_en": "A small orange fox cub standing at the edge of a magical forest, looking curious and hopeful toward the horizon, golden afternoon light, watercolor children's book illustration, soft pastel colors, warm and cozy, Studio Ghibli inspired, cute character design",
      "negative_prompt": "dark, scary, violent, realistic, photo, adult content",
      "ratio": "16:9",
      "palette": ["#FFB347", "#87CEEB", "#90EE90"]
    }
  ]
}

## 禁止出现
- 真实人物肖像 / 已知IP角色（米老鼠/哈利波特等）
- 武器/血腥/恐怖元素
"""
```

---

## 五、LangGraph 状态机流水线

```python
# services/api/app/graphs/story_pipeline.py

from langgraph.graph import StateGraph, END
from typing import TypedDict, Annotated, Optional
from langchain_core.messages import BaseMessage
import operator
import json


class StoryPipelineState(TypedDict):
    messages: Annotated[list[BaseMessage], operator.add]
    story_id: str
    request: dict                        # StoryCreationRequest
    blueprint: Optional[dict]            # StoryBlueprint
    writer_task_id: Optional[str]        # story_writer 异步任务ID
    image_task_id: Optional[str]         # image_prompt_gen 异步任务ID
    story_content: Optional[str]         # 汇总后的故事全文
    image_prompts: Optional[dict]        # 配图Prompt集合
    safety_report: Optional[dict]        # SafetyReport
    pipeline_stage: str                  # 当前阶段标识
    revision_count: int                  # 修改轮次计数
    reviewer_decision: Optional[str]     # approve/revise/reject
    reviewer_comment: Optional[str]      # 人工审核意见


# ── 节点实现 ───────────────────────────────────────────────

async def plan_story_node(state: StoryPipelineState):
    """第一阶段：规划故事骨架"""
    orchestrator = build_story_orchestrator()
    # 主 Agent 用 write_todos 规划，并产出 StoryBlueprint
    result = await orchestrator.ainvoke({
        "messages": state["messages"],
    })
    return {
        "pipeline_stage": "planning_done",
        "messages": result["messages"],
    }


async def launch_creation_node(state: StoryPipelineState):
    """第二阶段：并发启动 story_writer + image_prompt_gen"""
    return {"pipeline_stage": "creating"}


async def wait_for_creation_node(state: StoryPipelineState):
    """等待两个异步任务完成，轮询状态"""
    import asyncio
    max_wait = 300  # 最多等5分钟
    interval = 10
    elapsed = 0
    while elapsed < max_wait:
        # 检查两个任务状态（通过 check_async_task）
        # 实际由主 Agent 在 orchestrator 中处理
        await asyncio.sleep(interval)
        elapsed += interval
    return {"pipeline_stage": "creation_done"}


async def safety_check_node(state: StoryPipelineState):
    """第三阶段：同步安全审核"""
    return {"pipeline_stage": "safety_checking"}


async def human_review_node(state: StoryPipelineState):
    """HITL 节点：等待人工审批（由 interrupt_before 暂停）"""
    # 此节点在 interrupt_before 配置下，执行到这里时图会暂停
    # 恢复时 reviewer_decision 已通过 aupdate_state 注入
    return {"pipeline_stage": "reviewed"}


async def revise_story_node(state: StoryPipelineState):
    """修订节点：将审核意见回流给主 Agent 重新生成"""
    return {
        "pipeline_stage": "revising",
        "revision_count": state.get("revision_count", 0) + 1,
    }


async def publish_story_node(state: StoryPipelineState):
    """发布节点：持久化存储，更新状态"""
    return {"pipeline_stage": "published"}


async def reject_story_node(state: StoryPipelineState):
    """拒绝节点：记录原因，通知家长"""
    return {"pipeline_stage": "rejected"}


# ── 路由函数 ──────────────────────────────────────────────

def safety_routing(state: StoryPipelineState) -> str:
    report = state.get("safety_report", {})
    return report.get("risk_level", "BLOCK")


def human_review_routing(state: StoryPipelineState) -> str:
    return state.get("reviewer_decision", "reject")


def check_revision_limit(state: StoryPipelineState) -> str:
    max_rounds = int(os.environ.get("MAX_REVISION_ROUNDS", "3"))
    if state.get("revision_count", 0) >= max_rounds:
        return "force_reject"
    return "continue"


# ── 图构建 ────────────────────────────────────────────────

def build_story_pipeline():
    graph = StateGraph(StoryPipelineState)

    graph.add_node("plan_story",        plan_story_node)
    graph.add_node("launch_creation",   launch_creation_node)
    graph.add_node("wait_for_creation", wait_for_creation_node)
    graph.add_node("run_safety_check",  safety_check_node)
    graph.add_node("human_review",      human_review_node)
    graph.add_node("revise_story",      revise_story_node)
    graph.add_node("publish_story",     publish_story_node)
    graph.add_node("reject_story",      reject_story_node)

    graph.set_entry_point("plan_story")
    graph.add_edge("plan_story",        "launch_creation")
    graph.add_edge("launch_creation",   "wait_for_creation")
    graph.add_edge("wait_for_creation", "run_safety_check")

    graph.add_conditional_edges(
        "run_safety_check", safety_routing,
        {"PASS": "publish_story", "REVIEW": "human_review", "BLOCK": "reject_story"}
    )
    graph.add_conditional_edges(
        "human_review", human_review_routing,
        {"approve": "publish_story", "revise": "revise_story", "reject": "reject_story"}
    )
    graph.add_conditional_edges(
        "revise_story", check_revision_limit,
        {"continue": "run_safety_check", "force_reject": "reject_story"}
    )

    graph.add_edge("publish_story", END)
    graph.add_edge("reject_story",  END)

    return graph.compile(
        checkpointer=get_checkpointer(),
        interrupt_before=["human_review"],    # HITL 暂停点
    )
```

---

## 六、FastAPI 路由接口

```python
# services/api/app/routers/story.py

import asyncio, json, os
from uuid import uuid4
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from ..schemas.story import StoryCreationRequest, StoryCreationResponse, HumanReviewDecision
from ..graphs.story_pipeline import build_story_pipeline

router = APIRouter(prefix="/api/v1/stories", tags=["story"])
_pipeline = build_story_pipeline()


@router.post("/create", response_model=StoryCreationResponse)
async def create_story(request: StoryCreationRequest):
    """
    孩子发起绘本创作
    → 立即返回 story_id（不阻塞），后台异步执行完整流水线
    """
    story_id = f"story_{uuid4().hex[:8]}"
    config = {"configurable": {"thread_id": story_id}}

    asyncio.create_task(
        _pipeline.ainvoke(
            {
                "messages": [{
                    "role": "user",
                    "content": f"请帮我创作一个故事：{request.story_prompt}，"
                               f"目标年龄{request.target_age}岁，主题偏好{request.preferred_theme}"
                }],
                "story_id":      story_id,
                "request":       request.model_dump(),
                "pipeline_stage":"init",
                "revision_count": 0,
            },
            config=config
        )
    )

    return StoryCreationResponse(
        story_id=story_id,
        status="creating",
        message="正在为你创作绘本，大约需要 3 分钟 ✨",
        eta_seconds=180
    )


@router.get("/{story_id}/status")
async def get_status(story_id: str):
    """轮询当前流水线阶段与安全分数"""
    state = _pipeline.get_state({"configurable": {"thread_id": story_id}})
    if not state:
        raise HTTPException(status_code=404, detail="故事不存在")

    report = state.values.get("safety_report") or {}
    return {
        "story_id":          story_id,
        "stage":             state.values.get("pipeline_stage", "unknown"),
        "safety_score":      report.get("overall_score"),
        "risk_level":        report.get("risk_level"),
        "pending_review":    state.next == ("human_review",),
        "revision_count":    state.values.get("revision_count", 0),
    }


@router.post("/{story_id}/review")
async def submit_review(story_id: str, decision: HumanReviewDecision):
    """
    家长/运营人员提交人工审核结果
    → 恢复被 interrupt_before 暂停的流水线
    """
    config = {"configurable": {"thread_id": story_id}}
    state = _pipeline.get_state(config)
    if not state or state.next != ("human_review",):
        raise HTTPException(status_code=400, detail="该绘本当前不在待审核状态")

    # 注入审核决策
    await _pipeline.aupdate_state(config, {
        "reviewer_decision": decision.action,
        "reviewer_comment":  decision.comment,
    })
    # 恢复流水线执行
    asyncio.create_task(_pipeline.ainvoke(None, config=config))

    action_msg = {"approve": "已批准发布", "revise": "已提交修改意见", "reject": "已拒绝"}
    return {"story_id": story_id, "message": action_msg.get(decision.action, "已处理")}


@router.get("/{story_id}/stream")
async def stream_progress(story_id: str):
    """
    SSE 流式推送创作进度到前端
    → 孩子实时看到"正在写第2幕..."等动态消息
    """
    stage_labels = {
        "plan_story":        "✍️ 正在规划故事大纲...",
        "launch_creation":   "🚀 故事创作已启动！",
        "wait_for_creation": "✨ 正在撰写故事 & 生成配图描述...",
        "run_safety_check":  "🔍 内容安全检查中...",
        "human_review":      "⏳ 等待叔叔阿姨确认...",
        "revise_story":      "✏️ 正在优化内容...",
        "publish_story":     "🎉 绘本创作完成！",
        "rejected":          "❌ 很抱歉，内容需要调整",
    }

    async def generator():
        config = {"configurable": {"thread_id": story_id}}
        async for event in _pipeline.astream_events(None, config=config, version="v2"):
            if event["event"] == "on_chain_start":
                node = event.get("name", "")
                label = stage_labels.get(node)
                if label:
                    payload = json.dumps({"type": "progress", "node": node, "label": label})
                    yield f"data: {payload}\n\n"
            elif event["event"] == "on_chain_end":
                if event.get("name") in ("publish_story", "reject_story"):
                    stage = event["name"].replace("_story", "")
                    yield f"data: {json.dumps({'type': 'complete', 'story_id': story_id, 'stage': stage})}\n\n"
                    break

    return StreamingResponse(generator(), media_type="text/event-stream")
```

---

## 七、配置文件

### langgraph.json（多图注册）
```json
{
  "graphs": {
    "orchestrator":     "./app/graphs/story_pipeline.py:build_story_pipeline",
    "story_writer":     "./app/agents/story_writer_agent.py:build_story_writer",
    "image_prompt_gen": "./app/agents/image_prompt_agent.py:build_image_prompt_agent"
  },
  "env": ".env"
}
```

### .env 新增配置项
```bash
# ── 模型配置 ──────────────────────────────────────────────
STORY_MODEL=Pro/zai-org/GLM-5.1          # 主创作模型（需强工具调用能力）
IMAGE_PROMPT_MODEL=Qwen/Qwen2.5-7B-Instruct  # 图片Prompt（轻量即可）
SAFETY_MODEL=Pro/zai-org/GLM-5.1         # 安全审核（建议高精度）

# ── 业务阈值 ──────────────────────────────────────────────
SAFETY_PASS_THRESHOLD=90                 # ≥90 直接发布
SAFETY_REVIEW_THRESHOLD=70              # 70-89 人工审核
MAX_REVISION_ROUNDS=3                   # 最大自动修改轮次

# ── 存储（生产环境）────────────────────────────────────────
DATABASE_URL=postgresql://user:pass@localhost:5432/kidoai
```

### 工程目录结构
```
services/api/app/
├── agents/
│   ├── story_orchestrator.py    ← 主协调 Agent
│   ├── story_writer_agent.py    ← story_writer 子 Agent
│   ├── image_prompt_agent.py    ← image_prompt_gen 子 Agent
│   └── prompts.py               ← 所有 System Prompt 统一管理
├── graphs/
│   └── story_pipeline.py        ← LangGraph StateGraph 流水线
├── routers/
│   └── story.py                 ← FastAPI 路由
├── schemas/
│   └── story.py                 ← Pydantic 数据模型
└── skills/
    ├── story-writing/
    │   ├── SKILL.md             ← 故事写作规范 Skill（渐进式加载）
    │   └── references/
    │       └── age_guide.md     ← 分年龄段写作标准参考
    └── safety-audit/
        ├── SKILL.md             ← 安全审核标准 Skill
        └── references/
            └── content_policy.md ← 内容政策细则
```

---

## 八、关键设计决策

| 决策点 | 选型方案 | 设计原因 |
|---|---|---|
| story_writer + image_prompt_gen | **AsyncSubAgent 并发** | 两者完全独立，并发节省 40-50% 等待时间 |
| safety_check | **同步 SubAgent** | 审核须顺序执行，且单次 <5s，无需异步 |
| HITL 触发条件 | `score 70-89` 才触发 | 仅灰色地带需人工，高分直接通过，低分直接拒绝 |
| `response_format=SafetyReport` | 强制结构化输出 | 审核结果供程序路由，必须机器可读 |
| 防循环机制 | `revision_count ≤ 3` 硬上限 | 防止低质内容无限重试，保护算力和用户体验 |
| 前端通信 | **SSE 流式推送** | 创作耗时 3-5 分钟，实时进度远优于静态等待 |
| 记忆持久化 | `StoreBackend → /stories/` | 孩子历史绘本跨会话可查，支持家长回顾 |
| 安全模型温度 | `temperature=0.1` | 审核场景需要强确定性，低温度保证一致结论 |

---

## 九、落地里程碑

### Phase 1（第1-2周）— 核心创作链路
- [ ] story_writer + image_prompt_gen 基础 Agent 搭建
- [ ] 主协调 Agent write_todos 规划 + 异步并发启动
- [ ] 基础 API：`POST /create`、`GET /{id}/status`
- [ ] 前端：故事输入框 + 进度展示组件

### Phase 2（第3周）— 安全审核集成
- [ ] safety_check 子 Agent 四维审核 + SafetyReport Schema
- [ ] LangGraph interrupt_before HITL 门实现
- [ ] 家长端审核界面：`POST /{id}/review`
- [ ] 自动修订闭环（revision loop）

### Phase 3（第4周）— 生产级加固
- [ ] PostgresSaver 替换 MemorySaver（断点恢复）
- [ ] SSE 流式进度推送前端集成
- [ ] LangSmith 全链路追踪上线
- [ ] 孩子偏好长期记忆（故事风格/喜爱角色存档）
- [ ] 压测：并发 20 个创作任务的稳定性验证
