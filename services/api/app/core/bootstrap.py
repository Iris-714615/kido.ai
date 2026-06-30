from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import hash_password
from app.core.settings import Settings
from app.models import ChildProfile, Subscription, SubscriptionPlan, User, UserRole


# ========== 套餐种子数据 ==========

PLANS_SEED = [
    {
        "code": "free",
        "name": "免费版",
        "tier": "FREE",
        "billing_cycle": "NONE",
        "price_cents": 0,
        "max_children": 1,
        "sort_order": 0,
        "features_json": {
            "explore_daily_limit": 3,
            "chat_daily_limit": 10,
            "growth_report": "basic",
            "location_tracking": False,
            "video_call": False,
            "data_retention_days": 7,
            "priority_support": False,
        },
    },
    {
        "code": "monthly_standard",
        "name": "月度标准版",
        "tier": "STANDARD",
        "billing_cycle": "MONTHLY",
        "price_cents": 2900,
        "max_children": 1,
        "sort_order": 1,
        "features_json": {
            "explore_daily_limit": -1,
            "chat_daily_limit": -1,
            "growth_report": "full",
            "location_tracking": False,
            "video_call": False,
            "data_retention_days": 90,
            "priority_support": False,
        },
    },
    {
        "code": "yearly_standard",
        "name": "年度标准版",
        "tier": "STANDARD",
        "billing_cycle": "YEARLY",
        "price_cents": 29900,
        "max_children": 1,
        "sort_order": 2,
        "features_json": {
            "explore_daily_limit": -1,
            "chat_daily_limit": -1,
            "growth_report": "full",
            "location_tracking": False,
            "video_call": False,
            "data_retention_days": 90,
            "priority_support": False,
        },
    },
    {
        "code": "monthly_family",
        "name": "月度家庭版",
        "tier": "FAMILY",
        "billing_cycle": "MONTHLY",
        "price_cents": 4900,
        "max_children": 3,
        "sort_order": 3,
        "features_json": {
            "explore_daily_limit": -1,
            "chat_daily_limit": -1,
            "growth_report": "full",
            "location_tracking": True,
            "video_call": True,
            "data_retention_days": -1,
            "priority_support": False,
        },
    },
    {
        "code": "yearly_family",
        "name": "年度家庭版",
        "tier": "FAMILY",
        "billing_cycle": "YEARLY",
        "price_cents": 49900,
        "max_children": 3,
        "sort_order": 4,
        "features_json": {
            "explore_daily_limit": -1,
            "chat_daily_limit": -1,
            "growth_report": "full",
            "location_tracking": True,
            "video_call": True,
            "data_retention_days": -1,
            "priority_support": True,
        },
    },
]


def seed_subscription_plans(db: Session) -> None:
    """初始化订阅套餐数据（幂等）。"""
    for seed in PLANS_SEED:
        existing = db.scalar(select(SubscriptionPlan).where(SubscriptionPlan.code == seed["code"]))
        if existing is None:
            db.add(SubscriptionPlan(**seed))
    db.commit()


def ensure_free_subscription(db: Session, user_id: int) -> Subscription:
    """为新用户创建免费订阅（如果不存在）。"""
    sub = db.scalar(select(Subscription).where(Subscription.user_id == user_id))
    if sub is not None:
        return sub
    free_plan = db.scalar(select(SubscriptionPlan).where(SubscriptionPlan.code == "free"))
    if free_plan is None:
        seed_subscription_plans(db)
        free_plan = db.scalar(select(SubscriptionPlan).where(SubscriptionPlan.code == "free"))
    now = datetime.now(timezone.utc)
    sub = Subscription(
        user_id=user_id,
        plan_id=free_plan.id,
        status="ACTIVE",
        start_at=now,
        expire_at=now + timedelta(days=365 * 100),  # 免费版长期有效
        auto_renew=False,
    )
    db.add(sub)
    db.commit()
    db.refresh(sub)
    return sub


def seed_demo_account(db: Session, settings: Settings) -> ChildProfile:
    # 先初始化套餐
    seed_subscription_plans(db)

    user = db.scalar(select(User).where(User.username == settings.demo_username))
    if user is None:
        user = User(
            username=settings.demo_username,
            password_hash=hash_password(settings.demo_password, settings.secret_key),
            role=UserRole.CHILD,
        )
        db.add(user)
        db.flush()
    profile = db.scalar(select(ChildProfile).where(ChildProfile.user_id == user.id))
    if profile is None:
        profile = ChildProfile(
            user_id=user.id,
            nickname=settings.demo_nickname,
            age=settings.demo_age,
            current_level=1,
            token_balance=1000,
        )
        db.add(profile)
        db.flush()
    db.commit()

    # 确保 demo 用户有免费订阅
    ensure_free_subscription(db, user.id)

    return profile

