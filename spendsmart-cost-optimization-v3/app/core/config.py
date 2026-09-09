from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    app_name: str = "SpendSmart Cost Optimization"
    app_env: str = "dev"
    log_level: str = "INFO"

    database_url: str = "sqlite:///./spendsmart_finops.db"

    spendsmart_base_url: str = "https://uniteconpro-api.opstree.net"
    spendsmart_api_token: str = ""
    spendsmart_verify_ssl: bool = True
    spendsmart_timeout_seconds: int = 30

    raw_data_dir: str = "./data/raw/spendsmart"

    llm_provider: str = "groq"
    llm_model: str = "llama-3.1-8b-instant"
    groq_api_key: str = ""
    enable_llm: bool = False


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
