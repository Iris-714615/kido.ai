"""支付服务：封装支付宝 & 微信支付 SDK。

设计要点：
1. 统一接口 create_payment / verify_notify / query_order
2. 支付宝使用 python-alipay-sdk（AlipayPagePayment for 电脑网站支付）
3. 微信支付使用 wechatpayv3（Native 扫码支付）
4. 未配置密钥时降级为 mock 模式，方便本地开发联调
"""
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from app.core.settings import get_settings

logger = logging.getLogger(__name__)


def generate_order_no() -> str:
    """生成唯一订单号：KIDO + 时间戳 + 随机后缀。"""
    now = datetime.now(timezone.utc)
    return f"KIDO{now.strftime('%Y%m%d%H%M%S')}{uuid.uuid4().hex[:8].upper()}"


# ========== 支付宝 ==========


def _get_alipay_client():
    """懒加载支付宝客户端。密钥未配置时返回 None。"""
    settings = get_settings()
    if not settings.alipay_app_id or not settings.alipay_private_key:
        return None
    try:
        from alipay import AliPay  # type: ignore[import-untyped]

        client = AliPay(
            appid=settings.alipay_app_id,
            app_notify_url=settings.alipay_notify_url or None,
            app_private_key_string=settings.alipay_private_key,
            alipay_public_key_string=settings.alipay_public_key,
            sign_type="RSA2",
            debug=settings.alipay_sandbox,
        )
        return client
    except Exception as exc:
        logger.warning("Alipay client init failed: %s", exc)
        return None


def alipay_create_payment(order_no: str, amount_cents: int, subject: str) -> dict[str, Any]:
    """创建支付宝电脑网站支付，返回跳转 URL。

    Returns:
        {"pay_url": "https://..."}  或 mock 模式下返回 {"pay_url": "mock://alipay?order_no=xxx"}
    """
    settings = get_settings()
    client = _get_alipay_client()

    if client is None:
        # Mock 模式：本地开发无密钥时使用
        logger.info("Alipay mock mode for order %s", order_no)
        return {
            "pay_url": f"mock://alipay?order_no={order_no}&amount={amount_cents}",
            "mock": True,
        }

    amount_yuan = f"{amount_cents / 100:.2f}"
    return_url = settings.alipay_return_url or f"{settings.payment_base_url}/payment/result"
    notify_url = settings.alipay_notify_url or f"{settings.payment_base_url}/api/v1/payment/alipay/notify"

    order_string = client.api_alipay_trade_page_pay(
        out_trade_no=order_no,
        total_amount=amount_yuan,
        subject=subject,
        return_url=return_url,
        notify_url=notify_url,
    )
    gateway = settings.alipay_gateway
    pay_url = f"{gateway}?{order_string}"
    return {"pay_url": pay_url}


def alipay_verify_notify(data: dict[str, Any]) -> bool:
    """验证支付宝异步通知签名。

    安全策略：
    - 生产环境：密钥未配置时拒绝验签，防止伪造支付通知
    - 非生产环境：Mock 模式下直接信任，便于本地联调
    """
    client = _get_alipay_client()
    if client is None:
        settings = get_settings()
        if settings.app_env == "production":
            # 生产环境密钥未配置，拒绝验签防止支付伪造
            logger.error(
                "[Security] Alipay keys not configured in production, "
                "notify verification rejected for order %s",
                data.get("out_trade_no"),
            )
            return False
        # 非生产环境 Mock 模式：直接信任
        return data.get("mock") is not None or data.get("trade_status") == "TRADE_SUCCESS"

    try:
        return client.verify(data, data.get("sign"))
    except Exception as exc:
        logger.error("Alipay verify failed: %s", exc)
        return False


def alipay_query_order(order_no: str) -> dict[str, Any] | None:
    """主动查询支付宝订单状态。"""
    client = _get_alipay_client()
    if client is None:
        return None
    try:
        result = client.api_alipay_trade_query(out_trade_no=order_no)
        return result
    except Exception as exc:
        logger.error("Alipay query failed: %s", exc)
        return None


# ========== 微信支付 ==========


def _get_wechat_client():
    """懒加载微信支付客户端。密钥未配置时返回 None。"""
    settings = get_settings()
    if not settings.wechat_app_id or not settings.wechat_mch_id:
        return None
    try:
        from wechatpayv3 import WeChatPay, WeChatPayType  # type: ignore[import-untyped]

        wxpay = WeChatPay(
            wechatpay_type=WeChatPayType.NATIVE,
            mchid=settings.wechat_mch_id,
            private_key=settings.wechat_private_key,
            cert_serial_no=settings.wechat_cert_serial_no,
            apiv3_key=settings.wechat_api_v3_key,
            appid=settings.wechat_app_id,
            notify_url=settings.wechat_notify_url or f"{settings.payment_base_url}/api/v1/payment/wechat/notify",
            cert_dir=None,
            logger=logger,
            partner_mode=False,
            proxy=None,
        )
        return wxpay
    except Exception as exc:
        logger.warning("WeChat Pay client init failed: %s", exc)
        return None


def wechat_create_payment(order_no: str, amount_cents: int, description: str) -> dict[str, Any]:
    """创建微信 Native 支付（扫码），返回二维码内容。

    Returns:
        {"qr_code": "weixin://wxpay/bizpayurl?pr=xxx"}  或 mock 模式
    """
    client = _get_wechat_client()

    if client is None:
        logger.info("WeChat Pay mock mode for order %s", order_no)
        return {
            "qr_code": f"mock://wechat?order_no={order_no}&amount={amount_cents}",
            "mock": True,
        }

    code, message = client.pay(
        description=description,
        out_trade_no=order_no,
        amount={"total": amount_cents, "currency": "CNY"},
    )
    if code == 200:
        body = json.loads(message)
        return {"qr_code": body.get("code_url", "")}
    logger.error("WeChat Pay create failed: code=%s msg=%s", code, message)
    return {"qr_code": "", "error": message}


def wechat_verify_notify(headers: dict[str, str], body: bytes) -> dict[str, Any] | None:
    """验证微信支付异步通知并解密。返回解密后的通知体，失败返回 None。

    安全策略：
    - 生产环境：密钥未配置时拒绝验签，防止伪造支付通知
    - 非生产环境：Mock 模式下直接解析，便于本地联调
    """
    client = _get_wechat_client()
    if client is None:
        settings = get_settings()
        if settings.app_env == "production":
            # 生产环境密钥未配置，拒绝验签防止支付伪造
            logger.error("[Security] WeChat keys not configured in production, notify verification rejected")
            return None
        # 非生产环境 Mock 模式
        try:
            return json.loads(body)
        except Exception:
            return None

    try:
        result = client.callback(headers, body)
        return json.loads(result.content) if hasattr(result, "content") else result
    except Exception as exc:
        logger.error("WeChat verify failed: %s", exc)
        return None


# ========== 统一入口 ==========


def create_payment(channel: str, order_no: str, amount_cents: int, subject: str) -> dict[str, Any]:
    """统一创建支付入口。

    Args:
        channel: "ALIPAY" 或 "WECHAT"
        order_no: 商户订单号
        amount_cents: 金额（分）
        subject: 商品描述
    Returns:
        {"pay_url": "..."} for ALIPAY
        {"qr_code": "..."} for WECHAT
    """
    if channel == "ALIPAY":
        return alipay_create_payment(order_no, amount_cents, subject)
    elif channel == "WECHAT":
        return wechat_create_payment(order_no, amount_cents, subject)
    else:
        raise ValueError(f"Unsupported payment channel: {channel}")


def calc_subscription_period(billing_cycle: str) -> tuple[datetime, datetime]:
    """根据计费周期计算订阅起止时间。"""
    now = datetime.now(timezone.utc)
    if billing_cycle == "MONTHLY":
        expire = now + timedelta(days=30)
    elif billing_cycle == "YEARLY":
        expire = now + timedelta(days=365)
    else:
        expire = now + timedelta(days=365 * 100)
    return now, expire
