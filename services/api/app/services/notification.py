"""通知发送核心服务：支持阿里云短信、Resend API 或 SMTP 邮件。
当未配置相关密钥时，自动降级为 mock/fallback 模式，避免崩溃并打印日志，方便本地开发。
"""
from __future__ import annotations

import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime, timezone
import requests

from app.core.settings import get_settings
from app.models import NotificationLog, NotificationType, NotificationStatus
from app.db.session import SessionLocal

logger = logging.getLogger(__name__)


def log_notification(
    user_id: int | None,
    channel: NotificationType,
    receiver: str,
    template_code: str,
    content: str,
    status: NotificationStatus,
    error_message: str | None = None
) -> None:
    """向数据库写入发送日志"""
    db = SessionLocal()
    try:
        log_entry = NotificationLog(
            user_id=user_id,
            channel=channel,
            receiver=receiver,
            template_code=template_code,
            content=content,
            status=status,
            error_message=error_message,
            retry_count=0
        )
        db.add(log_entry)
        db.commit()
    except Exception as exc:
        logger.error("Failed to write notification log: %s", exc)
    finally:
        db.close()


# ========== 阿里云短信 ==========

def send_aliyun_sms(phone: str, template_code: str, template_param: dict[str, str], user_id: int | None = None) -> bool:
    """发送阿里云短信"""
    settings = get_settings()
    content_summary = f"Template: {template_code}, Params: {template_param}"

    if settings.sms_provider == "fallback" or not settings.aliyun_sms_access_key_id:
        # Fallback/Mock 模式
        logger.info("[SMS Mock] Send SMS to %s. Content: %s", phone, content_summary)
        log_notification(
            user_id=user_id,
            channel=NotificationType.SMS,
            receiver=phone,
            template_code=template_code,
            content=content_summary,
            status=NotificationStatus.SENT
        )
        return True

    try:
        # 懒加载阿里云 SDK，防未安装时报错
        from alibabacloud_dysmsapi20170525.client import Client as Dysmsapi20170525Client
        from alibabacloud_tea_openapi import models as open_api_models
        from alibabacloud_dysmsapi20170525 import models as dysmsapi_20170525_models
        import json

        config = open_api_models.Config(
            access_key_id=settings.aliyun_sms_access_key_id,
            access_key_secret=settings.aliyun_sms_access_key_secret,
            endpoint="dysmsapi.aliyuncs.com"
        )
        client = Dysmsapi20170525Client(config)
        send_sms_request = dysmsapi_20170525_models.SendSmsRequest(
            phone_numbers=phone,
            sign_name=settings.aliyun_sms_sign_name,
            template_code=template_code,
            template_param=json.dumps(template_param)
        )
        response = client.send_sms(send_sms_request)
        if response.body.code == "OK":
            log_notification(
                user_id=user_id,
                channel=NotificationType.SMS,
                receiver=phone,
                template_code=template_code,
                content=content_summary,
                status=NotificationStatus.SENT
            )
            return True
        else:
            err_msg = f"Aliyun SMS failed: {response.body.code} - {response.body.message}"
            logger.error(err_msg)
            log_notification(
                user_id=user_id,
                channel=NotificationType.SMS,
                receiver=phone,
                template_code=template_code,
                content=content_summary,
                status=NotificationStatus.FAILED,
                error_message=err_msg
            )
            return False
    except Exception as exc:
        err_msg = f"Exception sending SMS: {str(exc)}"
        logger.error(err_msg, exc_info=True)
        log_notification(
            user_id=user_id,
            channel=NotificationType.SMS,
            receiver=phone,
            template_code=template_code,
            content=content_summary,
            status=NotificationStatus.FAILED,
            error_message=err_msg
        )
        return False


# ========== 邮件通知 ==========

def send_email(to_email: str, subject: str, html_content: str, user_id: int | None = None) -> bool:
    """发送邮件，自动路由 Resend / SMTP / Fallback"""
    settings = get_settings()

    if settings.email_provider == "fallback":
        logger.info("[Email Mock] Send Email to %s. Subject: %s", to_email, subject)
        log_notification(
            user_id=user_id,
            channel=NotificationType.EMAIL,
            receiver=to_email,
            template_code="DYNAMIC",
            content=f"Subject: {subject}\nHTML: {html_content[:200]}...",
            status=NotificationStatus.SENT
        )
        return True

    elif settings.email_provider == "resend" and settings.resend_api_key:
        try:
            url = "https://api.resend.com/emails"
            headers = {
                "Authorization": f"Bearer {settings.resend_api_key}",
                "Content-Type": "application/json"
            }
            data = {
                "from": settings.email_sender,
                "to": to_email,
                "subject": subject,
                "html": html_content
            }
            res = requests.post(url, json=data, headers=headers, timeout=10)
            if res.status_code in (200, 201):
                log_notification(
                    user_id=user_id,
                    channel=NotificationType.EMAIL,
                    receiver=to_email,
                    template_code="DYNAMIC",
                    content=f"Subject: {subject}\nHTML: {html_content[:200]}...",
                    status=NotificationStatus.SENT
                )
                return True
            else:
                err_msg = f"Resend failed with code {res.status_code}: {res.text}"
                logger.error(err_msg)
                log_notification(
                    user_id=user_id,
                    channel=NotificationType.EMAIL,
                    receiver=to_email,
                    template_code="DYNAMIC",
                    content=f"Subject: {subject}",
                    status=NotificationStatus.FAILED,
                    error_message=err_msg
                )
                return False
        except Exception as exc:
            err_msg = f"Exception using Resend API: {str(exc)}"
            logger.error(err_msg, exc_info=True)
            log_notification(
                user_id=user_id,
                channel=NotificationType.EMAIL,
                receiver=to_email,
                template_code="DYNAMIC",
                content=f"Subject: {subject}",
                status=NotificationStatus.FAILED,
                error_message=err_msg
            )
            return False

    elif settings.email_provider == "smtp":
        try:
            msg = MIMEMultipart("alternative")
            msg["Subject"] = subject
            msg["From"] = settings.email_sender
            msg["To"] = to_email
            msg.attach(MIMEText(html_content, "html", "utf-8"))

            server = smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=10)
            server.ehlo()
            if settings.smtp_port == 587:
                server.starttls()
                server.ehlo()
            if settings.smtp_username and settings.smtp_password:
                server.login(settings.smtp_username, settings.smtp_password)
            server.sendmail(settings.email_sender, [to_email], msg.as_string())
            server.quit()

            log_notification(
                user_id=user_id,
                channel=NotificationType.EMAIL,
                receiver=to_email,
                template_code="DYNAMIC",
                content=f"Subject: {subject}\nHTML: {html_content[:200]}...",
                status=NotificationStatus.SENT
            )
            return True
        except Exception as exc:
            err_msg = f"SMTP failed: {str(exc)}"
            logger.error(err_msg, exc_info=True)
            log_notification(
                user_id=user_id,
                channel=NotificationType.EMAIL,
                receiver=to_email,
                template_code="DYNAMIC",
                content=f"Subject: {subject}",
                status=NotificationStatus.FAILED,
                error_message=err_msg
            )
            return False

    # Default Fallback
    logger.info("[Email Mock] Send Email to %s. Subject: %s", to_email, subject)
    return True
