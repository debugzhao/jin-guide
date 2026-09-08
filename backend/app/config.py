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

    # Intake chat 匿名限流（docs/backend-prd-v2.md §11.4）
    intake_anon_daily_limit: int = 4
    intake_anon_ip_daily_limit: int = 20

    # ── 上下文硬预算（P0-2：硬 Token 预算缺失）────────────────────────────
    # kimi-k2.6 的输入上下文上限。注意：这是「模型能力」口径，不是「实际可用
    # 输入」口径——OpenRouter 等托管入口按 32K 暴露该模型（见后端注释），而
    # Moonshot 官方为 256K。这里登记的 32768 是**保守假设**，必须在第一次真实
    # 调用回放里用 service 端 usage.prompt_tokens 校准后再上硬裁剪；在校准完成
    # 前，只能用于「估算超窗告警」，不能据此静默丢弃用户上下文。
    # 用环境变量 KIMI_K2_6_MODEL_WINDOW 覆盖，便于按不同托管口径切换。
    kimi_k2_6_model_window: int = 32768
    # 输入窗口的安全余量（协议开销、tokenizer 估算误差、工具 Schema 等），
    # 输入估算 + 输出预算 + 余量 必须落在 model_window 内。
    # 命名避开 kimi_/model_ 前缀：pydantic 默认把 model_ 视为受保护命名空间。
    context_window_safety_margin: int = 1024

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
