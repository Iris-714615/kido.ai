"""多智能体数据模型（对应设计规范第二章）。"""
from __future__ import annotations

from datetime import datetime
from typing import List, Literal, Optional
from uuid import uuid4

from pydantic import BaseModel, Field


class Character(BaseModel):
    name: str
    personality: str
    appearance: str


class StoryAct(BaseModel):
    act: int
    title: str
    summary: str
    content: Optional[str] = None
    image_prompt: Optional[str] = None


class StoryBlueprint(BaseModel):
    """主协调 Agent 规划阶段产出的故事骨架。"""
    story_id: str = Field(default_factory=lambda: f"story_{uuid4().hex[:8]}")
    title: str
    target_age: Literal["3-6", "6-10"]
    characters: List[Character]
    acts: List[StoryAct]
    tone: str
    value_theme: str


class SafetyFlag(BaseModel):
    type: str
    location: str
    description: str
    severity: Literal["low", "medium", "high", "critical"]


class DimensionScores(BaseModel):
    content_safety: int = Field(ge=0, le=100)
    child_friendly: int = Field(ge=0, le=100)
    values_guidance: int = Field(ge=0, le=100)
    originality: int = Field(ge=0, le=100)


class SafetyReport(BaseModel):
    """safety_check 子 Agent 的结构化输出。"""
    overall_score: int = Field(ge=0, le=100)
    risk_level: Literal["PASS", "REVIEW", "BLOCK"]
    dimension_scores: DimensionScores
    flags: List[SafetyFlag] = []
    suggestion: str
    auto_decision: Literal["PASS", "REVIEW", "BLOCK"]
    reviewer_note: Optional[str] = None


class ImagePromptItem(BaseModel):
    act: int
    scene_cn: str
    prompt_en: str
    negative_prompt: str = "dark, scary, violent, realistic, photo, adult content"
    ratio: str = "16:9"
    palette: List[str] = []


class ImagePromptSet(BaseModel):
    story_id: str
    prompts: List[ImagePromptItem] = []


class StoryCreationRequest(BaseModel):
    child_id: str
    story_prompt: str
    target_age: Literal["3-6", "6-10"] = "3-6"
    preferred_theme: Optional[str] = "adventure"


class HumanReviewDecision(BaseModel):
    action: Literal["approve", "revise", "reject"]
    comment: Optional[str] = None


class StoryCreationResponse(BaseModel):
    story_id: str
    status: Literal["creating", "reviewing", "published", "rejected"]
    message: str
    eta_seconds: Optional[int] = None


class StoryMetadata(BaseModel):
    story_id: str
    title: str
    target_age: str
    status: str
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)
    safety_score: Optional[int] = None
    risk_level: Optional[str] = None
    revision_count: int = 0
    cover_image_path: Optional[str] = None
    image_count: int = 0


class ImageManifestItem(BaseModel):
    """单张图片生成结果。"""
    act: int
    scene_cn: str
    prompt_en: str
    image_url: Optional[str] = None
    local_path: Optional[str] = None
    status: str  # succeeded | failed
    error: Optional[str] = None


class ImageManifest(BaseModel):
    """绘本图片清单（全部生成完成后保存）。"""
    story_id: str
    total: int = 0
    succeeded: int = 0
    failed: int = 0
    images: List[ImageManifestItem] = []
