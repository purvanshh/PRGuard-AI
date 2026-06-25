"""Application settings for PRGuard AI."""

from __future__ import annotations

from pydantic_settings import BaseSettings
from pydantic import Field


class Settings(BaseSettings):
    """Environment-driven configuration settings."""

    openai_api_key: str = Field("", env="OPENAI_API_KEY")
    nvidia_api_key: str = Field("", env="NVIDIA_API_KEY")
    github_token: str = Field("", env="GITHUB_TOKEN")
    github_webhook_secret: str = Field("", env="GITHUB_WEBHOOK_SECRET")
    redis_url: str = Field("redis://redis:6379/0", env="REDIS_URL")
    chroma_persist_dir: str = Field(".chroma", env="CHROMA_PERSIST_DIR")
    prguard_offline_mode: bool = Field(False, env="PRGUARD_OFFLINE_MODE")
    llm_circuit_fail_max: int = Field(5, env="LLM_CIRCUIT_FAIL_MAX")
    llm_circuit_reset_timeout: int = Field(60, env="LLM_CIRCUIT_RESET_TIMEOUT")
    database_url: str = Field("postgresql+asyncpg://postgres:postgres@localhost:5432/prguard", env="DATABASE_URL")

    model_config = {"extra": "ignore", "env_file": ".env"}


settings = Settings()

__all__ = ["settings", "Settings"]


