"""订阅管理 API：套餐列表、当前订阅状态、取消订阅、订单历史。"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.bootstrap import ensure_free_subscription
from app.dependencies import get_current_parent, get_db_session
from app.models import PaymentOrder, Subscription, SubscriptionPlan, User
from app.schemas import (
    CancelSubscriptionResponse,
    OrderStatusResponse,
    SubscriptionPlanPublic,
    SubscriptionPublic,
)

router = APIRouter(prefix="/subscription", tags=["subscription"])


@router.get("/plans", response_model=list[SubscriptionPlanPublic])
def list_plans(db: Session = Depends(get_db_session)) -> list[SubscriptionPlanPublic]:
    """获取所有可用套餐列表（按 sort_order 排序）。"""
    stmt = (
        select(SubscriptionPlan)
        .where(SubscriptionPlan.is_active == True)  # noqa: E712
        .order_by(SubscriptionPlan.sort_order)
    )
    plans = db.scalars(stmt).all()
    return [SubscriptionPlanPublic.model_validate(p) for p in plans]


@router.get("/current", response_model=SubscriptionPublic)
def get_current_subscription(
    current_parent: User = Depends(get_current_parent),
    db: Session = Depends(get_db_session),
) -> SubscriptionPublic:
    """获取当前用户的订阅状态。如果没有订阅记录，自动创建免费版。"""
    sub = ensure_free_subscription(db, current_parent.id)
    # 加载关联的 plan
    plan = db.get(SubscriptionPlan, sub.plan_id)
    result = SubscriptionPublic.model_validate(sub)
    result.plan = SubscriptionPlanPublic.model_validate(plan) if plan else None
    return result


@router.post("/cancel", response_model=CancelSubscriptionResponse)
def cancel_subscription(
    current_parent: User = Depends(get_current_parent),
    db: Session = Depends(get_db_session),
) -> CancelSubscriptionResponse:
    """取消订阅（关闭自动续费，到期后降级为免费版）。"""
    sub = db.scalar(select(Subscription).where(Subscription.user_id == current_parent.id))
    if sub is None:
        raise HTTPException(status_code=404, detail="Subscription not found")

    sub.auto_renew = False
    sub.status = "CANCELLED"
    db.commit()

    return CancelSubscriptionResponse(
        success=True,
        message="订阅已取消，到期后将降级为免费版",
        expire_at=sub.expire_at,
    )


@router.get("/orders", response_model=list[OrderStatusResponse])
def list_orders(
    current_parent: User = Depends(get_current_parent),
    db: Session = Depends(get_db_session),
) -> list[OrderStatusResponse]:
    """获取当前用户的订单历史。"""
    stmt = (
        select(PaymentOrder)
        .where(PaymentOrder.user_id == current_parent.id)
        .order_by(PaymentOrder.created_at.desc())
    )
    orders = db.scalars(stmt).all()
    results = []
    for o in orders:
        plan = db.get(SubscriptionPlan, o.plan_id)
        results.append(
            OrderStatusResponse(
                order_no=o.order_no,
                status=o.status,
                channel=o.channel,
                amount_cents=o.amount_cents,
                paid_at=o.paid_at,
                plan_name=plan.name if plan else None,
            )
        )
    return results
