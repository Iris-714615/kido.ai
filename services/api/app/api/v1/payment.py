"""支付 API：创建订单、支付宝/微信异步回调、订单状态查询。
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import PlainTextResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.bootstrap import ensure_free_subscription
from app.core.settings import get_settings
from app.dependencies import get_current_parent, get_db_session
from app.models import PaymentOrder, Subscription, SubscriptionPlan, User
from app.schemas import CreateOrderRequest, CreateOrderResponse, OrderStatusResponse
from app.services.payment import (
    alipay_verify_notify,
    calc_subscription_period,
    create_payment,
    generate_order_no,
    wechat_verify_notify,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/payment", tags=["payment"])

# 后台任务引用集合：保存 asyncio.create_task 返回的引用，防止 GC 回收
_background_tasks: set[asyncio.Task] = set()


def _spawn_background_task(coro) -> asyncio.Task:
    """创建后台任务并保存引用，完成后自动从集合移除。"""
    task = asyncio.create_task(coro)
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
    return task


@router.post("/create-order", response_model=CreateOrderResponse)
def create_order(
    payload: CreateOrderRequest,
    current_parent: User = Depends(get_current_parent),
    db: Session = Depends(get_db_session),
) -> CreateOrderResponse:
    """创建支付订单。

    流程：
    1. 校验套餐存在且非免费
    2. 获取/创建用户订阅记录
    3. 创建订单（PENDING）
    4. 调用支付渠道获取支付链接/二维码
    5. 返回支付参数给前端
    """
    # 查找套餐
    plan = db.scalar(
        select(SubscriptionPlan).where(
            SubscriptionPlan.code == payload.plan_code,
            SubscriptionPlan.is_active == True,  # noqa: E712
        )
    )
    if plan is None:
        raise HTTPException(status_code=404, detail="套餐不存在或已下架")
    if plan.price_cents == 0:
        raise HTTPException(status_code=400, detail="免费套餐无需支付")

    # 校验支付渠道
    channel = payload.channel.upper()
    if channel not in ("ALIPAY", "WECHAT"):
        raise HTTPException(status_code=400, detail="不支持的支付渠道")

    # 确保用户有订阅记录
    sub = ensure_free_subscription(db, current_parent.id)

    # 创建订单
    order_no = generate_order_no()
    order = PaymentOrder(
        order_no=order_no,
        user_id=current_parent.id,
        subscription_id=sub.id,
        plan_id=plan.id,
        amount_cents=plan.price_cents,
        channel=channel,
        status="PENDING",
    )
    db.add(order)
    db.commit()
    db.refresh(order)

    # 调用支付渠道
    subject = f"KidoAI {plan.name}"
    try:
        pay_result = create_payment(channel, order_no, plan.price_cents, subject)
    except Exception as exc:
        logger.error("Create payment failed: %s", exc)
        raise HTTPException(status_code=500, detail="支付渠道调用失败") from exc

    return CreateOrderResponse(
        order_no=order_no,
        amount_cents=plan.price_cents,
        channel=channel,
        pay_url=pay_result.get("pay_url"),
        qr_code=pay_result.get("qr_code"),
        plan_name=plan.name,
        plan_code=plan.code,
    )


@router.post("/alipay/notify")
async def alipay_notify(request: Request, db: Session = Depends(get_db_session)) -> PlainTextResponse:
    """支付宝异步回调通知。

    支付宝要求返回纯文本 "success"，否则会重试通知。
    """
    form_data = await request.form()
    data = {k: v for k, v in form_data.items()}
    logger.info("Alipay notify received: out_trade_no=%s", data.get("out_trade_no"))

    # 验签
    if not alipay_verify_notify(data):
        logger.warning("Alipay notify verify failed")
        return PlainTextResponse("fail")

    order_no = data.get("out_trade_no", "")
    trade_no = data.get("trade_no", "")
    trade_status = data.get("trade_status", "")

    # 只处理成功的交易
    if trade_status not in ("TRADE_SUCCESS", "TRADE_FINISHED"):
        return PlainTextResponse("success")

    # 更新订单
    order = db.scalar(select(PaymentOrder).where(PaymentOrder.order_no == order_no))
    if order is None:
        logger.warning("Order not found: %s", order_no)
        return PlainTextResponse("success")

    if order.status == "PAID":
        # 已处理过，幂等返回
        return PlainTextResponse("success")

    order.status = "PAID"
    order.trade_no = trade_no
    order.paid_at = datetime.now(timezone.utc)
    order.raw_notify_json = data
    db.flush()

    # 激活订阅
    _activate_subscription(db, order)
    db.commit()

    return PlainTextResponse("success")


@router.post("/wechat/notify")
async def wechat_notify(request: Request, db: Session = Depends(get_db_session)) -> dict:
    """微信支付异步回调通知。

    微信要求返回 {"code": "SUCCESS", "message": "成功"}。
    """
    body = await request.body()
    headers = dict(request.headers)
    logger.info("WeChat notify received")

    # 验签 + 解密
    notify_data = wechat_verify_notify(headers, body)
    if notify_data is None:
        logger.warning("WeChat notify verify failed")
        return {"code": "FAIL", "message": "验签失败"}

    order_no = notify_data.get("out_trade_no", "")
    trade_no = notify_data.get("transaction_id", "")
    trade_state = notify_data.get("trade_state", "")

    if trade_state != "SUCCESS":
        return {"code": "SUCCESS", "message": "成功"}

    order = db.scalar(select(PaymentOrder).where(PaymentOrder.order_no == order_no))
    if order is None:
        logger.warning("Order not found: %s", order_no)
        return {"code": "SUCCESS", "message": "成功"}

    if order.status == "PAID":
        return {"code": "SUCCESS", "message": "成功"}

    order.status = "PAID"
    order.trade_no = trade_no
    order.paid_at = datetime.now(timezone.utc)
    order.raw_notify_json = notify_data
    db.flush()

    _activate_subscription(db, order)
    db.commit()

    return {"code": "SUCCESS", "message": "成功"}


@router.get("/order/{order_no}", response_model=OrderStatusResponse)
def query_order(
    order_no: str,
    current_parent: User = Depends(get_current_parent),
    db: Session = Depends(get_db_session),
) -> OrderStatusResponse:
    """查询订单状态（前端轮询用）。"""
    order = db.scalar(select(PaymentOrder).where(PaymentOrder.order_no == order_no))
    if order is None:
        raise HTTPException(status_code=404, detail="订单不存在")
    if order.user_id != current_parent.id:
        raise HTTPException(status_code=403, detail="无权查看此订单")

    plan = db.get(SubscriptionPlan, order.plan_id)
    return OrderStatusResponse(
        order_no=order.order_no,
        status=order.status,
        channel=order.channel,
        amount_cents=order.amount_cents,
        paid_at=order.paid_at,
        plan_name=plan.name if plan else None,
    )


@router.post("/mock-pay/{order_no}")
def mock_pay(
    order_no: str,
    current_parent: User = Depends(get_current_parent),
    db: Session = Depends(get_db_session),
) -> dict:
    """模拟支付成功（仅开发环境使用，跳过真实支付流程）。

    生产环境(app_env=production)下禁止调用，防止绕过真实支付。
    """
    settings = get_settings()
    if settings.app_env == "production":
        raise HTTPException(status_code=403, detail="生产环境禁止使用 mock-pay 接口")
    order = db.scalar(select(PaymentOrder).where(PaymentOrder.order_no == order_no))
    if order is None:
        raise HTTPException(status_code=404, detail="订单不存在")
    if order.user_id != current_parent.id:
        raise HTTPException(status_code=403, detail="无权操作此订单")
    if order.status == "PAID":
        return {"success": True, "message": "订单已支付"}

    order.status = "PAID"
    order.trade_no = f"MOCK_{order_no}"
    order.paid_at = datetime.now(timezone.utc)
    order.raw_notify_json = {"mock": True}
    db.flush()

    _activate_subscription(db, order)
    db.commit()

    return {"success": True, "message": "模拟支付成功，订阅已激活"}


def _activate_subscription(db: Session, order: PaymentOrder) -> None:
    """支付成功后激活订阅：更新套餐、延长到期时间、发送通知。"""
    plan = db.get(SubscriptionPlan, order.plan_id)
    if plan is None:
        return

    sub = db.get(Subscription, order.subscription_id)
    if sub is None:
        return

    start_at, expire_at = calc_subscription_period(plan.billing_cycle)

    # 如果当前订阅未过期，在原到期时间基础上续期
    # 统一使用 aware UTC，与同文件其它时间字段(paid_at 等)保持一致
    now = datetime.now(timezone.utc)
    sub_expire = sub.expire_at
    if sub_expire and sub_expire.tzinfo is None:
        # SQLite 可能返回 naive datetime，补齐 tzinfo 为 UTC
        sub_expire = sub_expire.replace(tzinfo=timezone.utc)
    if sub_expire and sub_expire > now and sub.status == "ACTIVE":
        base = sub_expire
    else:
        base = now

    if plan.billing_cycle == "MONTHLY":
        from datetime import timedelta

        new_expire = base + timedelta(days=30)
    elif plan.billing_cycle == "YEARLY":
        from datetime import timedelta

        new_expire = base + timedelta(days=365)
    else:
        from datetime import timedelta

        new_expire = base + timedelta(days=365 * 100)

    sub.plan_id = plan.id
    sub.status = "ACTIVE"
    sub.start_at = now
    sub.expire_at = new_expire
    sub.auto_renew = False
    db.flush()
    logger.info(
        "Subscription activated: user=%s plan=%s expire=%s",
        order.user_id,
        plan.code,
        new_expire,
    )

    # ========== 发送支付成功通知 (多通道路由 · 异步化) ==========
    # 通知逻辑改为异步执行，避免阻塞支付回调响应（规范第 14 节 P1 优化）
    user = db.get(User, order.user_id)
    if user and user.username:
        # 捕获本次通知所需的快照数据（避免异步上下文中 db session 已关闭）
        notif_snapshot = {
            "user_id": user.id,
            "username": user.username,
            "order_no": order.order_no,
            "amount_cents": order.amount_cents,
            "channel": order.channel,
            "plan_name": plan.name,
            "plan_code": plan.code,
        }
        try:
            _spawn_background_task(_send_payment_notification_async(notif_snapshot))
        except RuntimeError:
            # 没有 event loop（同步调用上下文）→ 退化为同步发送
            _send_payment_notification_sync(notif_snapshot)


async def _send_payment_notification_async(snapshot: dict) -> None:
    """异步发送支付成功通知。

    将阻塞 I/O（Resend/SMTP/SMS SDK）从支付回调线程中剥离，
    避免回调响应超过 5s 触发支付渠道重试。
    """
    try:
        await asyncio.to_thread(_send_payment_notification_sync, snapshot)
    except Exception as exc:  # noqa: BLE001
        logger.error("Failed to send payment success notification (async): %s", exc, exc_info=True)


def _send_payment_notification_sync(snapshot: dict) -> None:
    """同步执行支付成功通知（多通道路由）。

    被 async 包装调用或在无 event loop 时直接调用。
    """
    try:
        username = snapshot.get("username")
        user_id = snapshot.get("user_id")
        if not username:
            return

        from jinja2 import Environment, FileSystemLoader
        template_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "templates")
        env = Environment(loader=FileSystemLoader(template_dir))
        template = env.get_template("payment_success.html")
        html_content = template.render(
            order_no=snapshot.get("order_no"),
            plan_name=snapshot.get("plan_name"),
            plan_code=snapshot.get("plan_code"),
            amount_cents=snapshot.get("amount_cents"),
            channel=snapshot.get("channel"),
        )

        # 如果用户名是邮箱，发邮件；如果是大陆手机号，发短信
        if "@" in username:
            from app.services.notification import send_email
            send_email(
                to_email=username,
                subject=f"【KidoAI】您的订阅 {snapshot.get('plan_name')} 已成功激活！",
                html_content=html_content,
                user_id=user_id,
            )
        elif len(username) == 11 and username.isdigit():
            from app.core.settings import get_settings
            from app.services.notification import send_aliyun_sms
            settings = get_settings()
            send_aliyun_sms(
                phone=username,
                template_code=settings.aliyun_sms_template_code_recharge or "SMS_DEFAULT_RECHARGE",
                template_param={"plan_name": snapshot.get("plan_name"), "order_no": snapshot.get("order_no")},
                user_id=user_id,
            )
    except Exception as exc:  # noqa: BLE001
        logger.error("Failed to send payment success notification: %s", exc, exc_info=True)
