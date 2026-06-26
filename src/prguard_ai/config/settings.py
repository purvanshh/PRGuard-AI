"""Application settings for PRGuard AI."""

from __future__ import annotations

import os
from pydantic_settings import BaseSettings
from pydantic import Field, model_validator


class Settings(BaseSettings):
    """Environment-driven configuration settings."""

    openai_api_key: str = Field("", validation_alias="OPENAI_API_KEY")
    nvidia_api_key: str = Field("", validation_alias="NVIDIA_API_KEY")
    github_token: str = Field("", validation_alias="GITHUB_TOKEN")
    github_webhook_secret: str = Field("", validation_alias="GITHUB_WEBHOOK_SECRET")
    redis_url: str = Field("redis://redis:6379/0", validation_alias="REDIS_URL")
    chroma_persist_dir: str = Field(".chroma", validation_alias="CHROMA_PERSIST_DIR")
    prguard_offline_mode: bool = Field(False, validation_alias="PRGUARD_OFFLINE_MODE")
    llm_circuit_fail_max: int = Field(5, validation_alias="LLM_CIRCUIT_FAIL_MAX")
    llm_circuit_reset_timeout: int = Field(60, validation_alias="LLM_CIRCUIT_RESET_TIMEOUT")
    database_url: str = Field("postgresql+asyncpg://postgres:postgres@localhost:5432/prguard", validation_alias="DATABASE_URL")

    # Audited environment configurations
    prguard_analysis_image: str = Field("prguard-ai-analysis:latest", validation_alias="PRGUARD_ANALYSIS_IMAGE")
    github_app_private_key: str = Field("", validation_alias="GITHUB_APP_PRIVATE_KEY")
    github_app_id: str = Field("", validation_alias="GITHUB_APP_ID")
    github_app_installation_id: str = Field("", validation_alias="GITHUB_APP_INSTALLATION_ID")
    prguard_fake_diff_path: str = Field("", validation_alias="PRGUARD_FAKE_DIFF_PATH")
    otel_exporter_otlp_endpoint: str = Field("http://localhost:4317", validation_alias="OTEL_EXPORTER_OTLP_ENDPOINT")
    redis_mode: str = Field("single", validation_alias="REDIS_MODE")
    celery_eager: bool = Field(False, validation_alias="CELERY_EAGER")
    redis_socket_timeout: float = Field(2.0, validation_alias="REDIS_SOCKET_TIMEOUT")
    redis_connect_retries: int = Field(3, validation_alias="REDIS_CONNECT_RETRIES")
    redis_sentinel_hosts: str = Field("", validation_alias="REDIS_SENTINEL_HOSTS")
    redis_sentinel_service_name: str = Field("mymaster", validation_alias="REDIS_SENTINEL_SERVICE_NAME")
    redis_fallback_to_memory: bool = Field(False, validation_alias="REDIS_FALLBACK_TO_MEMORY")

    # Hardcoded constants centralized
    max_files_per_pr: int = Field(50, validation_alias="MAX_FILES_PER_PR")
    global_concurrency_limit: int = Field(5, validation_alias="GLOBAL_CONCURRENCY_LIMIT")
    processing_ttl_seconds: int = Field(900, validation_alias="PROCESSING_TTL_SECONDS")
    daily_limit_usd: float = Field(5.0, validation_alias="DAILY_LIMIT_USD")
    max_tokens_per_request: int = Field(2048, validation_alias="MAX_TOKENS_PER_REQUEST")
    max_tokens_per_pr: int = Field(8000, validation_alias="MAX_TOKENS_PER_PR")
    admin_token: str = Field("admin-secret-token", validation_alias="ADMIN_TOKEN")

    model_config = {"extra": "ignore", "env_file": ".env"}

    @model_validator(mode="after")
    def validate_keys(self) -> Settings:
        if "PYTEST_CURRENT_TEST" not in os.environ and not self.prguard_offline_mode:
            if not self.github_token:
                raise ValueError("GITHUB_TOKEN must not be empty")
            if not self.github_webhook_secret:
                raise ValueError("GITHUB_WEBHOOK_SECRET must not be empty")
            if not self.openai_api_key and not self.nvidia_api_key:
                raise ValueError("Either OPENAI_API_KEY or NVIDIA_API_KEY must be provided")
        return self


settings = Settings()

__all__ = ["settings", "Settings"]



