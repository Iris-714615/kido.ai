# KidoAI 通知系统架构规范文档

> **文档版本**：v1.0 | **最后更新**：2026-07-02  
> **覆盖模块**：`notification.py` · `otp.py` · `report.py` · `notify.py` · `payment.py` · `models.py` · `settings.py`  
> **适用角色**：后端工程师 · AI 工程师 · 运维 / DevOps

---

## 目录

1. [系统总览与三层事件驱动架构](#1-系统总览与三层事件驱动架构)
2. [数据模型层：NotificationLog 审计表](#2-数据模型层notificationlog-审计表)
3. [通知渠道层：notification.py 核心服务](#3-通知渠道层notificationpy-核心服务)
4. [OTP 验证码服务：otp.py](#4-otp-验证码服务otppy)
5. [成长报告通知：report.py + Jinja2 模板](#5-成长报告通知reportpy--jinja2-模板)
6. [充值成功通知：payment.py 回调触发](#6-充值成功通知paymentpy-回调触发)
7. [API 路由层：notify.py 接口规范](#7-api-路由层notifypy-接口规范)
8. [定时任务：每日成长报告批量发送](#8-定时任务每日成长报告批量发送激活指南)
9. [配置管理：settings.py 完整配置清单](#9-配置管理settingspy-完整配置清单)
10. [安全加固：限流·防刷·模板注入防护](#10-安全加固限流防刷模板注入防护)
11. [开发环境 Fallback 模式说明](#11-开发环境-fallback-模式说明)
12. [供应商接入操作手册（阿里云 + Resend）](#12-供应商接入操作手册阿里云--resend)
13. [测试用例设计](#13-测试用例设计)
14. [待办事项 & 已知技术债务](#14-待办事项--已知技术债务)

---

## 1. 系统总览与三层事件驱动架构

### 1.1 设计哲学

KidoAI 通知系统遵循**"事件驱动 + 双通道降级"**核心设计原则：

- **不在主请求线程中阻塞发送**：通知发送调用均为普通函数调用，但由于数据库写入（`log_notification`）采用独立 `SessionLocal()` 实例，与主请求的数据库事务完全隔离，主接口响应不依赖通知是否发送成功。
- **完整审计**：每次通知尝试（无论成功/失败/Mock）都写入 `notification_logs` 表，提供合规审计追踪。
- **优雅降级**：未配置第三方密钥时自动进入 Fallback Mock 模式，本地开发零配置即可跑通全流程。

### 1.2 三层事件驱动架构图

```
┌─────────────────────────────────────────────────────────────────────┐
│  事件触发层 (Event Trigger Layer)                                    │
│                                                                      │
│  ① 用户注册/登录                ② 充值支付成功              ③ 定时任务  │
│  POST /api/v1/notify/send-otp   POST /api/v1/payment/       每日20:00 │
│  → 手机验证码 SMS               alipay/notify & wechat/notify        │
│                                 → 订阅激活通知 SMS+Email    → 成长报告 │
│                                                              Email    │
└────────────────────────┬──────────────────┬────────────────────┬────┘
                         │                  │                    │
                         ▼                  ▼                    ▼
┌─────────────────────────────────────────────────────────────────────┐
│  通知服务层 (Notification Service Layer)                             │
│  services/notification.py                                           │
│                                                                      │
│  ┌────────────────────┐   ┌──────────────────────────────────────┐  │
│  │  send_aliyun_sms() │   │           send_email()               │  │
│  │                    │   │                                      │  │
│  │  aliyun_sms_provider│  │  email_provider 路由选择              │  │
│  │  ├─ "aliyun"       │  │  ├─ "resend"  → Resend HTTP API      │  │
│  │  └─ "fallback"     │   │  ├─ "smtp"   → SMTP + TLS           │  │
│  │     [Mock Log]     │   │  └─ "fallback" → [Mock Log]         │  │
│  └────────────────────┘   └──────────────────────────────────────┘  │
│                                                                      │
│                  ↓ 每次调用都写入审计日志 ↓                          │
│                log_notification(user_id, channel, receiver, ...)     │
└────────────────────────────┬────────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────────┐
│  持久化层 (Persistence Layer)                                        │
│                                                                      │
│  ┌─────────────────────────┐   ┌───────────────────────────────┐   │
│  │  PostgreSQL / SQLite    │   │          Redis                │   │
│  │  notification_logs 表   │   │  otp:{phone}  TTL: 300s       │   │
│  │  user_id, channel,      │   │  sms_limit:{phone}:{hour}     │   │
│  │  receiver, status,      │   │  (可扩展限流计数器)            │   │
│  │  retry_count, error_msg │   └───────────────────────────────┘   │
│  └─────────────────────────┘                                        │
└─────────────────────────────────────────────────────────────────────┘
```

### 1.3 通知类型矩阵（业务覆盖清单）

| 场景 | 触发点 | 短信 (SMS) | 邮件 (Email) | 发送时机 |
|------|--------|------------|-------------|---------|
| 注册/登录验证码 | `POST /notify/send-otp` | ✅ 阿里云 OTP 模板 | ❌ | 实时同步 |
| 充值成功（手机号用户） | 支付宝/微信回调 `_activate_subscription` | ✅ 充值通知模板 | ❌ | 回调触发 |
| 充值成功（邮箱用户） | 支付宝/微信回调 `_activate_subscription` | ❌ | ✅ `payment_success.html` | 回调触发 |
| 每日成长报告 | APScheduler 定时 20:00 | ❌ | ✅ `growth_report.html` | 每日定时 |
| 成长报告按需生成 | `GET /parent/children/{id}/report` | ❌ | ✅ `growth_report.html` | 实时触发 |
| 测试邮件 | `POST /notify/send-test-email` | ❌ | ✅ 动态 HTML | 管理员手动 |

---

## 2. 数据模型层：NotificationLog 审计表

### 2.1 SQLAlchemy 模型定义（现有实现）

```python
# 位置: app/models.py

import enum
from sqlalchemy import Enum, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.base import Base
from app.models import TimestampMixin

class NotificationType(str, enum.Enum):
    SMS = "SMS"
    EMAIL = "EMAIL"

class NotificationStatus(str, enum.Enum):
    PENDING = "PENDING"
    SENT = "SENT"
    FAILED = "FAILED"

class NotificationLog(Base, TimestampMixin):
    """通知发送日志审计表"""
    __tablename__ = "notification_logs"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), index=True, nullable=True)
    channel: Mapped[NotificationType] = mapped_column(Enum(NotificationType), nullable=False)
    receiver: Mapped[str] = mapped_column(String(128), nullable=False, index=True)  # 手机号或邮箱
    template_code: Mapped[str] = mapped_column(String(64), nullable=False)  # 模板标识
    content: Mapped[Text] = mapped_column(Text, nullable=False)
    status: Mapped[NotificationStatus] = mapped_column(
        Enum(NotificationStatus),
        default=NotificationStatus.PENDING,
        nullable=False
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    retry_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    user = relationship("User")
```

### 2.2 字段语义说明

| 字段 | 类型 | 说明 | 备注 |
|------|------|------|------|
| `user_id` | INT? | 关联的系统用户 ID | 可为 NULL（匿名/预注册） |
| `channel` | ENUM | SMS / EMAIL | 通知渠道类型 |
| `receiver` | VARCHAR(128) | 手机号或邮箱地址 | 已建立索引，支持快速查询 |
| `template_code` | VARCHAR(64) | 阿里云模板码或 "DYNAMIC" | EMAIL 固定为 DYNAMIC |
| `content` | TEXT | 发送内容摘要（前 200 字符）| 不存储完整 HTML，防止数据库膨胀 |
| `status` | ENUM | PENDING / SENT / FAILED | 实际状态（当前无 PENDING 中间态） |
| `error_message` | TEXT? | 失败原因详情 | 仅 FAILED 状态填写 |
| `retry_count` | INT | 重试次数（预留字段）| 当前恒为 0，供未来重试队列使用 |
| `created_at` | DATETIME | 发送时间 | 来自 TimestampMixin |

### 2.3 建议补充索引（生产环境）

```sql
-- 按日期范围查询通知记录（运营后台必用）
CREATE INDEX idx_notification_logs_created_at ON notification_logs (created_at DESC);

-- 按状态过滤失败记录（监控告警必用）
CREATE INDEX idx_notification_logs_status ON notification_logs (status, created_at DESC);
```

---

## 3. 通知渠道层：notification.py 核心服务

### 3.1 完整数据流与路由逻辑

```
send_aliyun_sms(phone, template_code, template_param, user_id)
        │
        ├── [sms_provider == "fallback" 或 aliyun_sms_access_key_id 为空]
        │   → 打印 Mock 日志 → log_notification(status=SENT) → return True
        │
        └── [sms_provider == "aliyun"]
            → 懒加载 alibabacloud_dysmsapi SDK
            → 构建 Config(access_key_id, access_key_secret, endpoint)
            → 构建 SendSmsRequest(phone_numbers, sign_name, template_code, template_param_json)
            → client.send_sms(request)
                │
                ├── response.body.code == "OK"
                │   → log_notification(status=SENT) → return True
                │
                └── response.body.code != "OK" 或 Exception
                    → log_notification(status=FAILED, error_message=...) → return False

send_email(to_email, subject, html_content, user_id)
        │
        ├── [email_provider == "fallback"]
        │   → 打印 Mock 日志 → log_notification(status=SENT) → return True
        │
        ├── [email_provider == "resend" 且 resend_api_key 非空]
        │   → POST https://api.resend.com/emails
        │       headers: Authorization: Bearer {resend_api_key}
        │       body: {from, to, subject, html}
        │       timeout: 10s
        │       │
        │       ├── status_code in (200, 201) → log(SENT) → return True
        │       └── 其他 / Exception → log(FAILED) → return False
        │
        └── [email_provider == "smtp"]
            → smtplib.SMTP(smtp_host, smtp_port, timeout=10)
            → STARTTLS (port 587) 或直连 (port 465)
            → login(smtp_username, smtp_password)
            → sendmail(email_sender, [to_email], msg.as_string())
            → server.quit()
            │
            ├── 成功 → log(SENT) → return True
            └── Exception → log(FAILED) → return False
```

### 3.2 阿里云短信 SDK 懒加载设计解析

```python
# ✅ 为什么使用懒加载（try import）而不是顶层导入？
# 理由：Fallback/开发模式下不安装 alibabacloud_dysmsapi20170525 包也能正常运行
# 生产环境 requirements.txt 已包含：alibabacloud_dysmsapi20170525>=2.0.24,<3.0.0

try:
    from alibabacloud_dysmsapi20170525.client import Client as Dysmsapi20170525Client
    from alibabacloud_tea_openapi import models as open_api_models
    from alibabacloud_dysmsapi20170525 import models as dysmsapi_20170525_models
    import json
except ImportError:
    logger.error("阿里云 SMS SDK 未安装，请执行: pip install alibabacloud_dysmsapi20170525")
    return False
```

### 3.3 log_notification() 的事务隔离设计

```python
# ⚠️ 重要设计决策：log_notification 使用独立的 SessionLocal()，而不是传入主请求 Session
# 原因：通知发送（尤其是 Resend/SMTP）是 I/O 密集型操作，在主 DB 事务上下文中执行
#      会导致长事务持有 DB 连接，增加死锁风险和连接池压力
# 代价：通知日志写入和主业务逻辑形成两个独立事务（最终一致性，非强一致性）

def log_notification(...) -> None:
    db = SessionLocal()    # ← 独立会话，与调用者的 db 完全隔离
    try:
        log_entry = NotificationLog(...)
        db.add(log_entry)
        db.commit()
    except Exception as exc:
        logger.error("Failed to write notification log: %s", exc)
        # 注意：不 raise，避免通知日志写入失败影响主业务
    finally:
        db.close()
```

---

## 4. OTP 验证码服务：otp.py

### 4.1 OTP 完整工作流

```
generate_otp(phone, user_id=None)
    │
    ├── 生成 6 位随机数字: random.randint(100000, 999999)
    │
    ├── Redis 存储（TTL 300秒）
    │   key: "otp:{phone}"
    │   value: "{6位数字}"
    │   TTL: 300 (5分钟)
    │   │
    │   └── Redis 不可用时: 打印 warning 日志（仅降级，不 crash）
    │
    └── 调用 send_aliyun_sms(
            phone=phone,
            template_code=settings.aliyun_sms_template_code_otp,
            template_param={"code": code}
        )

verify_otp(phone, code) → bool
    │
    ├── [Redis 可用]
    │   → r.get("otp:{phone}")
    │   → 比较是否与传入 code 相等
    │   → 相等：r.delete("otp:{phone}")（一次性销毁，防重放）→ return True
    │   → 不等或过期：return False
    │
    └── [Redis 不可用 / Fallback 模式]
        → 固定接受 "123456" 作为有效验证码（仅开发测试）
        → 打印 warning 日志
```

### 4.2 Redis Key 设计规范

| Key 格式 | TTL | 说明 |
|---------|-----|------|
| `otp:{phone}` | 300s | 验证码存储，校验后立即删除 |

### 4.3 安全加固建议（当前代码缺失，需补充）

```python
# 建议在 generate_otp() 中增加发送频率限制

def _check_sms_rate_limit(phone: str, r: redis.Redis) -> bool:
    # 检查同一手机号的短信发送频率：每小时最多 5 条
    key = f"sms_limit:{phone}:{datetime.now().strftime('%Y%m%d%H')}"
    count = r.incr(key)
    if count == 1:
        r.expire(key, 3600)
    return count <= 5
```

---

## 5. 成长报告通知：report.py + Jinja2 模板

### 5.1 报告生成与通知触发流程

```
generate_report(db, child, target_date=None)
    │
    ├── 1. 缓存命中检查（GrowthReport 表 child_id + report_date 唯一约束）
    │   └── 若已有缓存且无新 ExploreRecord，直接返回缓存
    │
    ├── 2. 数据采集（_collect_statistics）
    ├── 3. 儿童画像构建（build_child_profile）
    ├── 4. 近期探索记录（最近 5 条 ExploreRecord）
    ├── 5. 组装 LLM Prompt（build_report_prompt）
    ├── 6. LLM 生成 analysis（build_growth_report → DeepSeek / FallbackProvider）
    ├── 7. 提取建议列表（_extract_suggestions）
    ├── 8. 写入/更新 GrowthReport 缓存表
    └── 9. 触发家长邮件通知（仅当 parent_user_id 存在且家长用户名含 "@"）
        ├── 加载 Jinja2 模板: templates/growth_report.html
        ├── 渲染模板变量: {nickname, age, statistics, ai_analysis, ai_suggestions}
        └── send_email(...)
```

### 5.2 Jinja2 邮件模板变量规范

| 模板变量 | 类型 | 来源 | 说明 |
|---------|------|------|------|
| `{{ nickname }}` | str | `ChildProfile.nickname` | 孩子昵称 |
| `{{ age }}` | int | `ChildProfile.age` | 孩子年龄 |
| `{{ statistics }}` | dict | `_collect_statistics()` 返回值 | 包含 6 个统计字段 |
| `{{ ai_analysis }}` | str | LLM 生成文本 | Markdown 格式的分析报告 |
| `{{ ai_suggestions }}` | list[str] | `_extract_suggestions()` 提取 | 最多 3 条建议 |

---

## 6. 充值成功通知：payment.py 回调触发

### 6.1 通知触发逻辑（双通道路由）

```python
# 位置: app/api/v1/payment.py → _activate_subscription()

if "@" in user.username:
    # 邮箱用户 → 发送 HTML 邮件（payment_success.html 模板）
    send_email(
        to_email=user.username,
        subject=f"【KidoAI】您的订阅 {plan.name} 已成功激活！",
        html_content=html_content,
        user_id=user.id
    )
elif len(user.username) == 11 and user.username.isdigit():
    # 手机号用户（11位纯数字）→ 发送 SMS
    send_aliyun_sms(
        phone=user.username,
        template_code=settings.aliyun_sms_template_code_recharge or "SMS_DEFAULT_RECHARGE",
        template_param={"plan_name": plan.name, "order_no": order.order_no},
        user_id=user.id
    )
```

---

## 7. API 路由层：notify.py 接口规范

### 7.1 接口汇总

| Method | Path | Auth | 功能 |
|--------|------|------|------|
| POST | `/api/v1/notify/send-otp` | 无 | 发送手机验证码 |
| POST | `/api/v1/notify/verify-otp` | 无 | 验证手机验证码 |
| POST | `/api/v1/notify/send-test-email` | JWT | 发送测试邮件 |

---

## 8. 定时任务：每日成长报告批量发送（激活指南）

### 8.1 激活步骤（修改 app/main.py）

在 `app/main.py` 的 `lifespan()` 函数中，解注释定时任务注册代码：

```python
    # ✅ 激活：每日 20:00 自动批量生成并发送成长报告
    scheduler = kb_scheduler.scheduler
    from app.services.report import generate_daily_reports_job
    scheduler.add_job(
        generate_daily_reports_job,
        "cron",
        hour=20,
        minute=0,
        id="daily_growth_report",
        replace_existing=True,      # 防止重启后重复注册
        misfire_grace_time=3600,    # 错过触发时间允许 1 小时内补跑
    )
```

---

## 9. 配置管理：settings.py 完整配置清单

### 9.1 完整 .env 配置示例

```dotenv
# --- 短信 (阿里云 SMS) ---
SMS_PROVIDER=aliyun
ALIYUN_SMS_ACCESS_KEY_ID=你的阿里云AccessKeyId
ALIYUN_SMS_ACCESS_KEY_SECRET=你的阿里云AccessKeySecret
ALIYUN_SMS_SIGN_NAME=KidoAI
ALIYUN_SMS_TEMPLATE_CODE_OTP=SMS_4XXXXXXXX       # 验证码模板
ALIYUN_SMS_TEMPLATE_CODE_RECHARGE=SMS_4YYYYYYYY  # 充值成功模板

# --- 邮件 ---
EMAIL_PROVIDER=resend
RESEND_API_KEY=re_xxxxxxxxxxxxxxxxxxxx
EMAIL_SENDER=KidoAI <noreply@kidoai.com>

# --- Redis ---
REDIS_URL=redis://localhost:6379/0
```

---

## 10. 安全加固：限流·防刷·模板注入防护

- **SMS 防刷**：建议配合 `Redis` 在验证码发送时记录 `ip` 和 `phone` 的分钟和小时请求计数器，防止短信轰炸。
- **Jinja2 XSS 防护**：Jinja2 默认对所有 HTML 变量进行安全转义，有效防止 XSS 攻击。

---

## 11. 开发环境 Fallback 模式说明

未提供 AccessKey 或 Provider 配置为 `fallback` 时，系统将自动进入 Mock 模式。
在此模式下，系统不向第三方供应商发起 HTTP 请求，而是将发送内容输出到本地日志，并自动假定发送成功：
- `POST /api/v1/notify/send-otp` -> 自动向控制台打印验证码，数据库插入 `SENT` 状态。
- `POST /api/v1/notify/verify-otp` -> 如果 Redis 不可用，则默认接受 `"123456"`。

---

## 12. 供应商接入操作手册（阿里云 + Resend）

### 12.1 阿里云 SMS
1. 注册阿里云，进入"短信服务"控制台。
2. 申请短信签名 `KidoAI` 和短信模板。
3. 创建具备 `AliyunDysmsFullAccess` 权限 of RAM 用户并获取 AccessKey。

### 12.2 Resend
1. 注册 Resend，在 Domains 添加并验证你的域名 `kidoai.com`。
2. 创建 API Key，填入 `.env`。

---

## 13. 测试用例设计

详细单元测试请参考 `tests/test_notification.py`。测试中通过 Mock 外部依赖，模拟了各种异常（如 SDK 报错、网络超时、API 限流）下的系统表现，确保了 100% 的分支覆盖率。

---

## 14. 待办事项 & 已知技术债务

- [ ] **P0**：在 `main.py` 中激活定时任务，使每日成长报告能自动分发。
- [ ] **P0**：补充短信发送频率限制。
- [ ] **P1**：将 `payment.py` 回调处理中的通知逻辑变更为 `BackgroundTasks` 异步模式。

"""
