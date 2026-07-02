from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field


class RoleChoice:
    CHILD = "CHILD"
    PARENT = "PARENT"
    ADMIN = "ADMIN"


class UserPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    role: str


class ChildProfilePublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    parent_user_id: int | None = None
    nickname: str
    age: int
    current_level: int
    token_balance: int


class RegisterRequest(BaseModel):
    username: str = Field(min_length=3, max_length=50)
    password: str = Field(min_length=6, max_length=128)
    role: str = Field(default=RoleChoice.CHILD)
    nickname: str | None = Field(default=None, max_length=50)
    age: int | None = Field(default=None, ge=3, le=12)
    parent_username: str | None = Field(default=None, max_length=50)
    email: str | None = Field(default=None, description="注册邮箱，用于发送欢迎邮件")


class LoginRequest(BaseModel):
    username: str
    password: str


class AuthResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserPublic
    child_profile: ChildProfilePublic | None = None


class DemoResponse(AuthResponse):
    demo_username: str


class ExploreAnalysis(BaseModel):
    object_name: str
    scientific_fact: str
    growth_dimension: str
    score_delta: int


class ChatReply(BaseModel):
    message: str
    memory_summary: str
    suggested_follow_up: str


class ExploreRecordPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    child_id: int
    media_type: str
    file_name: str
    file_path: str
    file_url: str
    object_name: str
    scientific_fact: str
    growth_dimension: str
    score_delta: int
    analysis_json: dict
    created_at: datetime


class ExploreResponse(BaseModel):
    record: ExploreRecordPublic
    memory_events: list[dict]


class ChatSessionCreate(BaseModel):
    title: str | None = None


class ChatSessionPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    child_id: int
    title: str
    last_message_at: datetime | None = None
    created_at: datetime
    updated_at: datetime
    messages: list[ChatMessagePublic] = []


class ChatMessageCreate(BaseModel):
    content: str = Field(min_length=1, max_length=4000)


class ChatMessagePublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    session_id: int
    role: str
    content: str
    metadata_json: dict
    created_at: datetime


class ChatExchangeResponse(BaseModel):
    session: ChatSessionPublic
    user_message: ChatMessagePublic
    assistant_message: ChatMessagePublic
    memory_events: list[dict]


class MemoryEventPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    child_id: int
    source_type: str
    source_id: int | None = None
    event_type: str
    payload_json: dict
    created_at: datetime


class MemoryEntityPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    child_id: int
    entity_type: str
    entity_name: str
    attributes_json: dict
    created_at: datetime


class MemorySummaryResponse(BaseModel):
    events: list[MemoryEventPublic]
    entities: list[MemoryEntityPublic]


class CozeMemoryEventItem(BaseModel):
    id: int
    event_type: str
    source_type: str
    source_id: int | None = None
    payload: dict
    created_at: datetime


class CozeMemoryEntityItem(BaseModel):
    id: int
    entity_type: str
    entity_name: str
    attributes: dict
    created_at: datetime


class CozeMemorySummaryResponse(BaseModel):
    child_id: int
    events: list[CozeMemoryEventItem]
    entities: list[CozeMemoryEntityItem]


class CozeChatMessageItem(BaseModel):
    id: int
    session_id: int
    role: str
    content: str
    metadata: dict
    created_at: datetime


class CozeRecentChatsResponse(BaseModel):
    child_id: int
    messages: list[CozeChatMessageItem]


class CozeExploreRecordItem(BaseModel):
    id: int
    media_type: str
    file_name: str
    file_url: str
    object_name: str
    scientific_fact: str
    growth_dimension: str
    score_delta: int
    analysis: dict
    created_at: datetime


class CozeExploreRecordsResponse(BaseModel):
    child_id: int
    records: list[CozeExploreRecordItem]


class CozeChildProfileResponse(BaseModel):
    id: int
    nickname: str
    age: int
    current_level: int
    token_balance: int
    created_at: datetime
    updated_at: datetime


# ========== 家长端 schemas ==========


class ParentCreateChildRequest(BaseModel):
    """家长创建儿童子账号。"""

    username: str = Field(min_length=3, max_length=50)
    password: str = Field(min_length=6, max_length=128)
    nickname: str = Field(min_length=1, max_length=50)
    age: int = Field(ge=3, le=12)


class ParentChildSummary(BaseModel):
    """家长视角的儿童概要（含统计）。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    nickname: str
    age: int
    current_level: int
    token_balance: int
    explore_count: int = 0
    chat_session_count: int = 0
    memory_entity_count: int = 0
    last_active_at: datetime | None = None
    created_at: datetime


class ParentReportDimension(BaseModel):
    dimension: str
    count: int
    total_score: int


class ParentReportResponse(BaseModel):
    child_id: int
    nickname: str
    total_explore: int
    total_chat_sessions: int
    total_chat_messages: int
    total_memory_events: int
    total_memory_entities: int
    total_tokens_earned: int
    dimensions: list[ParentReportDimension]
    recent_explore: list[ExploreRecordPublic]
    recent_chat_titles: list[ChatSessionPublic]


class GrowthReportResponse(BaseModel):
    """AI 成长报告响应：统计数据 + Memory 画像 + LLM 分析。"""

    model_config = ConfigDict(from_attributes=True)

    child_id: int
    nickname: str
    age: int
    report_date: date
    statistics: dict
    profile: dict
    ai_analysis: str
    ai_suggestions: list[str]
    dimensions: list[ParentReportDimension]
    recent_explore: list[ExploreRecordPublic]
    recent_chat_titles: list[ChatSessionPublic]


# ========== 订阅与支付 schemas ==========


class SubscriptionPlanPublic(BaseModel):
    """套餐信息"""
    model_config = ConfigDict(from_attributes=True)

    id: int
    code: str
    name: str
    tier: str
    billing_cycle: str
    price_cents: int
    max_children: int
    features_json: dict
    is_active: bool
    sort_order: int


class SubscriptionPublic(BaseModel):
    """当前订阅状态"""
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    plan_id: int
    status: str
    start_at: datetime
    expire_at: datetime
    auto_renew: bool
    plan: SubscriptionPlanPublic | None = None


class CreateOrderRequest(BaseModel):
    """创建支付订单"""
    plan_code: str = Field(..., description="套餐编码，如 monthly_standard")
    channel: str = Field(..., description="支付渠道：ALIPAY / WECHAT")


class CreateOrderResponse(BaseModel):
    """创建订单返回"""
    order_no: str
    amount_cents: int
    channel: str
    pay_url: str | None = None      # 支付宝跳转链接
    qr_code: str | None = None      # 微信二维码内容（前端生成图片）
    plan_name: str
    plan_code: str


class OrderStatusResponse(BaseModel):
    """订单状态查询"""
    model_config = ConfigDict(from_attributes=True)

    order_no: str
    status: str
    channel: str
    amount_cents: int
    paid_at: datetime | None = None
    plan_name: str | None = None


class CancelSubscriptionResponse(BaseModel):
    """取消订阅响应"""
    success: bool
    message: str
    expire_at: datetime | None = None

