"""OTP 验证码逻辑：生成、基于 Redis 的 5 分钟 TTL 缓存、校验、防刷限流。
"""
from __future__ import annotations

import logging
import random
from datetime import datetime
from typing import Optional
import redis

from app.core.settings import get_settings
from app.services.notification import send_aliyun_sms

logger = logging.getLogger(__name__)

# 限流阈值
HOURLY_LIMIT = 5      # 每手机号每小时最多 5 条
MINUTE_LIMIT = 1      # 每手机号每分钟最多 1 条


def _get_redis_client() -> Optional[redis.Redis]:
    settings = get_settings()
    try:
        return redis.Redis.from_url(settings.redis_url, decode_responses=True)
    except Exception as exc:
        logger.error("Redis connection failed for OTP: %s", exc)
        return None


def _check_sms_rate_limit(phone: str, r: redis.Redis) -> tuple[bool, str]:
    """短信发送频率限制校验。

    规则：
      - 每手机号每分钟最多 1 条
      - 每手机号每小时最多 5 条

    Returns:
        (allowed, reason) - allowed=False 表示被限流
    """
    now = datetime.now()
    minute_key = f"sms_limit_minute:{phone}:{now.strftime('%Y%m%d%H%M')}"
    hour_key = f"sms_limit_hour:{phone}:{now.strftime('%Y%m%d%H')}"

    pipe = r.pipeline()
    pipe.incr(minute_key)
    pipe.expire(minute_key, 70)
    pipe.incr(hour_key)
    pipe.expire(hour_key, 3600)
    minute_count, _, hour_count, _ = pipe.execute()

    if minute_count > MINUTE_LIMIT:
        return False, f"发送过于频繁，每分钟仅允许 {MINUTE_LIMIT} 条"
    if hour_count > HOURLY_LIMIT:
        return False, f"发送已达上限，每小时仅允许 {HOURLY_LIMIT} 条"
    return True, ""


def generate_otp(phone: str, user_id: int | None = None) -> str:
    """生成 6 位纯数字验证码并存入 Redis 缓存，默认 5 分钟 TTL。

    集成了短信防刷限流：每分钟 1 条 / 每小时 5 条。
    被限流时抛出 ValueError，调用方需捕获。
    """
    settings = get_settings()
    code = f"{random.randint(100000, 999999)}"

    r = _get_redis_client()
    if r:
        try:
            # 防刷限流校验
            allowed, reason = _check_sms_rate_limit(phone, r)
            if not allowed:
                raise ValueError(reason)
            # 存入 redis，key: otp:{phone}
            r.setex(f"otp:{phone}", 300, code)
        except ValueError:
            raise
        except Exception as exc:
            logger.error("Failed to save OTP to Redis: %s", exc)
    else:
        logger.warning("[Redis Mock] Mocking Redis OTP storage for %s", phone)

    # 调用短信通道发送
    send_aliyun_sms(
        phone=phone,
        template_code=settings.aliyun_sms_template_code_otp or "SMS_DEFAULT_OTP",
        template_param={"code": code},
        user_id=user_id
    )
    return code

def verify_otp(phone: str, code: str) -> bool:
    """验证手机验证码是否正确。

    安全策略：
    - 生产环境(app_env=production)：禁止任何固定测试码，必须走 Redis 校验；
      Redis 不可用时直接拒绝验证，防止认证绕过。
    - 非生产环境：Fallback 模式或 Redis 不可用时接受固定测试码 123456，
      便于本地开发与联调测试。
    """
    settings = get_settings()
    is_production = settings.app_env == "production"

    # 非生产环境 + Fallback 开发测试模式：接受固定测试码 123456
    if not is_production and settings.sms_provider == "fallback" and code == "123456":
        logger.info("[SMS Mock] Verify OTP with test code 123456 for %s", phone)
        return True

    r = _get_redis_client()
    if r:
        try:
            cached_code = r.get(f"otp:{phone}")
            if cached_code and cached_code == code:
                r.delete(f"otp:{phone}")  # 验证成功立即销毁，防止复用
                return True
        except Exception as exc:
            logger.error("Failed to read OTP from Redis: %s", exc)
            # 生产环境 Redis 异常时拒绝验证，防止降级到测试码
            if is_production:
                return False
    else:
        # Redis 不可用
        if is_production:
            # 生产环境禁止 Mock 模式，防止认证绕过
            logger.error("[Security] Redis unavailable in production, OTP verify rejected for %s", phone)
            return False
        # 非生产环境进入 Mock 模式
        logger.warning("[Redis Mock] Verify OTP in Mock Mode for %s", phone)
        return code == "123456"
    return False
