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

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
