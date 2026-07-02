from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "KidoAI"
    api_prefix: str = "/api/v1"
    database_url: str = "sqlite:///./data/kidoai.db"
    redis_url: str = "redis://localhost:6379/0"
    storage_dir: Path = Field(default=Path("./data/uploads"))
    secret_key: str = "change-me"
    access_token_ttl_minutes: int = 60 * 24 * 7
    cors_allow_origins: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173", "http://localhost:5174", "http://127.0.0.1:5174", "http://localhost:5175", "http://127.0.0.1:5175"]

    @field_validator("cors_allow_origins", mode="before")
    @classmethod
    def _parse_cors_origins(cls, value: object) -> list[str]:
        if isinstance(value, str):
            stripped = value.strip()
            # 支持 JSON 数组格式
            if stripped.startswith("["):
                import json
                return json.loads(stripped)
            # 支持逗号分隔或单值
            return [item.strip() for item in stripped.split(",") if item.strip()]
        if isinstance(value, (list, tuple)):
            return [str(item) for item in value]
        return value  # type: ignore[return-value]

    ai_provider: str = "fallback"
    openai_api_key: str | None = None
    openai_model: str = "gpt-4o-mini"
    demo_username: str = "demo_child"
    demo_password: str = "demo123"
    demo_nickname: str = "小探险家"
    demo_age: int = 6

    # DeepSeek（通过 LangChain 调用，用于成长报告等 LLM 场景）
    deepseek_api_key: str | None = None
    deepseek_base_url: str = "https://api.deepseek.com/v1"
    deepseek_model: str = "deepseek-chat"
    deepseek_temperature: float = 0.7

    # DashScope（阿里云通义千问，OpenAI 兼容模式）
    dashscope_api_key: str | None = None
    dashscope_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    dashscope_model: str = "qwen-plus"
    dashscope_embedding_model: str = "text-embedding-v2"
    dashscope_temperature: float = 0.7

    # RAG 多轮对话历史最少保留轮数（1 轮 = 1 次提问 + 1 次回答）
    rag_history_min_turns: int = 5

    coze_api_key: str | None = None
    coze_api_base: str = "https://api.coze.cn"
    coze_timeout: int = 30
    coze_chat_workflow_id: str = "kidoai-chat-reply"
    coze_explore_workflow_id: str = "kidoai-explore-analysis"
    coze_summary_workflow_id: str = "kidoai-memory-summary"
    coze_bot_id: str | None = None
    coze_user_id_prefix: str = "kidoai-child-"

    # ========== 短信与邮箱通知配置 ==========
    # 短信 (Aliyun SMS)
    sms_provider: str = "fallback"  # aliyun / fallback
    aliyun_sms_access_key_id: str = ""
    aliyun_sms_access_key_secret: str = ""
    aliyun_sms_sign_name: str = ""
    aliyun_sms_template_code_otp: str = ""  # 注册验证码模板
    aliyun_sms_template_code_recharge: str = ""  # 充值成功通知模板
    aliyun_sms_template_code_report: str = ""  # 成长报告提审/更新模板

    # 邮箱 (SMTP or Resend API)
    email_provider: str = "fallback"  # resend / smtp / fallback
    resend_api_key: str = ""
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    email_sender: str = "KidoAI <noreply@kidoai.com>"

    # ========== 支付配置 ==========
    # 支付宝
    alipay_app_id: str = ""
    alipay_private_key: str = ""
    alipay_public_key: str = ""
    alipay_gateway: str = "https://openapi-sandbox.dl.alipaydev.com/gateway.do"
    alipay_notify_url: str = ""
    alipay_return_url: str = ""
    alipay_sandbox: bool = True

    # 微信支付
    wechat_app_id: str = ""
    wechat_mch_id: str = ""
    wechat_api_v3_key: str = ""
    wechat_private_key: str = ""
    wechat_cert_serial_no: str = ""
    wechat_notify_url: str = ""

    # 支付回调基础地址（用于拼接 notify/return URL）
    payment_base_url: str = "http://localhost:8000"

    @field_validator("storage_dir", mode="before")
    @classmethod
    def _coerce_storage_dir(cls, value: object) -> Path:
        return Path(value) if not isinstance(value, Path) else value

    def ensure_directories(self) -> None:
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        Path("./data").mkdir(parents=True, exist_ok=True)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    settings = Settings()
    settings.ensure_directories()
    return settings
