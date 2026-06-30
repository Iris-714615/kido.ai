from __future__ import annotations

import enum
from datetime import date, datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, JSON, String, Text, func, Date
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class UserRole(str, enum.Enum):
    CHILD = "CHILD"
    PARENT = "PARENT"
    ADMIN = "ADMIN"


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class User(Base, TimestampMixin):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(50), unique=True, index=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[UserRole] = mapped_column(Enum(UserRole), nullable=False, default=UserRole.CHILD)

    child_profile = relationship(
        "ChildProfile",
        foreign_keys="ChildProfile.user_id",
        back_populates="user",
        uselist=False,
    )
    children = relationship(
        "ChildProfile",
        foreign_keys="ChildProfile.parent_user_id",
        back_populates="parent",
    )


class ChildProfile(Base, TimestampMixin):
    __tablename__ = "child_profiles"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), unique=True, index=True, nullable=False)
    parent_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), index=True, nullable=True)
    nickname: Mapped[str] = mapped_column(String(50), nullable=False)
    age: Mapped[int] = mapped_column(Integer, nullable=False)
    current_level: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    token_balance: Mapped[int] = mapped_column(Integer, default=1000, nullable=False)

    user = relationship("User", foreign_keys=[user_id], back_populates="child_profile")
    parent = relationship("User", foreign_keys=[parent_user_id], back_populates="children")
    explore_records = relationship("ExploreRecord", back_populates="child", cascade="all, delete-orphan")
    chat_sessions = relationship("ChatSession", back_populates="child", cascade="all, delete-orphan")
    memory_events = relationship("MemoryEvent", back_populates="child", cascade="all, delete-orphan")
    memory_entities = relationship("MemoryEntity", back_populates="child", cascade="all, delete-orphan")


class ExploreRecord(Base, TimestampMixin):
    __tablename__ = "explore_records"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    child_id: Mapped[int] = mapped_column(ForeignKey("child_profiles.id"), index=True, nullable=False)
    media_type: Mapped[str] = mapped_column(String(20), nullable=False)
    file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    file_path: Mapped[str] = mapped_column(String(512), nullable=False)
    file_url: Mapped[str] = mapped_column(String(512), nullable=False)
    object_name: Mapped[str] = mapped_column(String(100), nullable=False)
    scientific_fact: Mapped[str] = mapped_column(Text, nullable=False)
    growth_dimension: Mapped[str] = mapped_column(String(32), nullable=False)
    score_delta: Mapped[int] = mapped_column(Integer, nullable=False)
    analysis_json: Mapped[dict] = mapped_column(JSON, nullable=False)

    child = relationship("ChildProfile", back_populates="explore_records")


class ChatSession(Base, TimestampMixin):
    __tablename__ = "chat_sessions"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    child_id: Mapped[int] = mapped_column(ForeignKey("child_profiles.id"), index=True, nullable=False)
    title: Mapped[str] = mapped_column(String(120), nullable=False, default="新的对话")
    last_message_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    child = relationship("ChildProfile", back_populates="chat_sessions")
    messages = relationship("ChatMessage", back_populates="session", cascade="all, delete-orphan")


class ChatMessage(Base, TimestampMixin):
    __tablename__ = "chat_messages"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("chat_sessions.id"), index=True, nullable=False)
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    metadata_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)

    session = relationship("ChatSession", back_populates="messages")


class MemoryEvent(Base, TimestampMixin):
    __tablename__ = "memory_events"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    child_id: Mapped[int] = mapped_column(ForeignKey("child_profiles.id"), index=True, nullable=False)
    source_type: Mapped[str] = mapped_column(String(40), nullable=False)
    source_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    event_type: Mapped[str] = mapped_column(String(60), nullable=False)
    payload_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)

    child = relationship("ChildProfile", back_populates="memory_events")


class MemoryEntity(Base, TimestampMixin):
    __tablename__ = "memory_entities"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    child_id: Mapped[int] = mapped_column(ForeignKey("child_profiles.id"), index=True, nullable=False)
    entity_type: Mapped[str] = mapped_column(String(40), index=True, nullable=False)
    entity_name: Mapped[str] = mapped_column(String(120), index=True, nullable=False)
    attributes_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)

    child = relationship("ChildProfile", back_populates="memory_entities")

class GrowthReport(Base, TimestampMixin):
    """成长报告缓存表，按 child_id + 日期唯一。"""
    __tablename__ = "growth_reports"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    child_id: Mapped[int] = mapped_column(ForeignKey("child_profiles.id"), index=True, nullable=False)
    report_date: Mapped[date] = mapped_column(Date, nullable=False)  # 报告日期（按天）
    statistics_json: Mapped[dict] = mapped_column(JSON, nullable=False)  # 统计数据
    profile_json: Mapped[dict] = mapped_column(JSON, nullable=False)     # 孩子画像
    ai_analysis: Mapped[str] = mapped_column(Text, nullable=False)       # LLM 生成的分析文本
    ai_suggestions: Mapped[list] = mapped_column(JSON, nullable=False, default=list)  # 建议列表

    child = relationship("ChildProfile")


# ========== 订阅与支付模型 ==========


class SubscriptionPlan(Base, TimestampMixin):
    """订阅套餐定义表"""
    __tablename__ = "subscription_plans"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(32), unique=True, index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    tier: Mapped[str] = mapped_column(String(20), nullable=False)  # FREE / STANDARD / FAMILY
    billing_cycle: Mapped[str] = mapped_column(String(20), nullable=False)  # MONTHLY / YEARLY / NONE
    price_cents: Mapped[int] = mapped_column(Integer, nullable=False)  # 以分为单位
    max_children: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    features_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    is_active: Mapped[bool] = mapped_column(default=True, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    subscriptions = relationship("Subscription", back_populates="plan")
    orders = relationship("PaymentOrder", back_populates="plan")


class Subscription(Base, TimestampMixin):
    """用户当前订阅状态表"""
    __tablename__ = "subscriptions"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), unique=True, index=True, nullable=False)
    plan_id: Mapped[int] = mapped_column(ForeignKey("subscription_plans.id"), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="ACTIVE")  # ACTIVE / EXPIRED / CANCELLED
    start_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expire_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    auto_renew: Mapped[bool] = mapped_column(default=False, nullable=False)

    plan = relationship("SubscriptionPlan", back_populates="subscriptions")
    orders = relationship("PaymentOrder", back_populates="subscription")


class PaymentOrder(Base, TimestampMixin):
    """支付订单表"""
    __tablename__ = "payment_orders"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    order_no: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)
    subscription_id: Mapped[int] = mapped_column(ForeignKey("subscriptions.id"), nullable=False)
    plan_id: Mapped[int] = mapped_column(ForeignKey("subscription_plans.id"), nullable=False)
    amount_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    channel: Mapped[str] = mapped_column(String(20), nullable=False)  # ALIPAY / WECHAT
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="PENDING")  # PENDING / PAID / FAILED / REFUNDED
    trade_no: Mapped[str | None] = mapped_column(String(128), nullable=True)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    raw_notify_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)

    subscription = relationship("Subscription", back_populates="orders")
    plan = relationship("SubscriptionPlan", back_populates="orders")


class RAGHistory(Base, TimestampMixin):
    """RAG 问答历史记录，用于保留多轮对话上下文。

    每条记录表示一轮"问答"（一个 question + 它的 answer），
    同一会话的记录通过 conversation_id 关联。
    """

    __tablename__ = "rag_histories"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    conversation_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    child_id: Mapped[int] = mapped_column(
        ForeignKey("child_profiles.id"), index=True, nullable=False
    )
    role: Mapped[str] = mapped_column(String(20), nullable=False)  # user / assistant
    question: Mapped[str | None] = mapped_column(Text, nullable=True)
    answer: Mapped[str | None] = mapped_column(Text, nullable=True)
    sources_json: Mapped[list] = mapped_column(JSON, nullable=False, default=list)