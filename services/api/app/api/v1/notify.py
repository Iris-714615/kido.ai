"""通知与验证码路由 API。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, EmailStr
from sqlalchemy.orm import Session

from app.dependencies import get_db_session, get_current_user
from app.models import User
from app.services.otp import generate_otp, verify_otp
from app.services.notification import send_email

router = APIRouter(prefix="/notify", tags=["notifications"])

class SendOTPRequest(BaseModel):
    phone: str = Field(..., pattern=r"^1[3-9]\d{9}$", description="标准的中国大陆手机号")

class VerifyOTPRequest(BaseModel):
    phone: str = Field(..., pattern=r"^1[3-9]\d{9}$")
    code: str = Field(..., min_length=6, max_length=6, description="6位数字验证码")

class SendTestEmailRequest(BaseModel):
    email: EmailStr
    subject: str
    body: str

@router.post("/send-otp", status_code=status.HTTP_200_OK)
def send_phone_otp(payload: SendOTPRequest):
    """发送注册/快捷登录手机验证码（限制5分钟时效）。

    内置防刷限流：每分钟 1 条 / 每小时 5 条。超限返回 429。
    """
    try:
        generate_otp(payload.phone)
        return {"status": "success", "message": "验证码已成功发送"}
    except ValueError as exc:
        # 限流异常 → 429
        raise HTTPException(status_code=429, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"发送验证码失败: {str(exc)}")

@router.post("/verify-otp")
def verify_phone_otp(payload: VerifyOTPRequest):
    """手动验证手机验证码接口"""
    is_valid = verify_otp(payload.phone, payload.code)
    if not is_valid:
        raise HTTPException(status_code=400, detail="验证码无效或已过期")
    return {"status": "success", "message": "验证码核验成功"}

@router.post("/send-test-email")
def send_test_email(payload: SendTestEmailRequest, current_user: User = Depends(get_current_user)):
    """管理员或用户发送测试邮件接口"""
    success = send_email(
        to_email=payload.email,
        subject=payload.subject,
        html_content=f"<h3>测试邮件</h3><p>{payload.body}</p>",
        user_id=current_user.id
    )
    if not success:
        raise HTTPException(status_code=500, detail="邮件发送失败，请检查配置")
    return {"status": "success", "message": "邮件发送成功"}
