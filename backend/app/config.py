from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/wenjin"
    redis_url: str = "redis://localhost:6379"
    litellm_base_url: str = "http://localhost:4000/v1"
    litellm_master_key: str = "sk-wenjin-dev"
    secret_key: str = "dev-secret-key-change-in-production"
    langsmith_api_key: str = ""
    langsmith_project: str = "wenjin-agent-dev"
    openai_api_key: str = ""
    cohere_api_key: str = ""
    env: str = "development"
    # 仅用于调试的功能。默认关闭，因为模型生成的推理过程可能包含
    # 不该暴露给终端用户的内部上下文信息。
    enable_reasoning_display: bool = False
    # Resend —— 免费额度每天 100 封邮件：https://resend.com
    resend_api_key: str = ""
    email_from: str = "问津 <onboarding@resend.dev>"
    # 邮箱注册邀请码，固定 8 位，生产环境可用 REGISTER_INVITE_CODE 覆盖
    register_invite_code: str = "CFVD6EGQ"

    data_pipeline_enabled: bool = False
    data_pipeline_raw_root: str = "data/raw"
    data_pipeline_report_root: str = "data/reports"

    # Intake chat 匿名限流 + 重复/相似问题去重（docs/backend-prd-v2.md §11.4）
    intake_anon_daily_limit: int = 4
    intake_anon_ip_daily_limit: int = 20
    dedup_window_minutes: int = 30
    dedup_similarity_threshold: float = 0.85

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
