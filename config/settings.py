"""Application settings for PRGuard AI."""

from __future__ import annotations

from functools import lru_cache

from pydantic import BaseSettings, Field


class Settings(BaseSettings):
    """Environment-driven configuration settings."""

    openai_api_key: str = Field("", env="OPENAI_API_KEY")
    github_token: str = Field("", env="GITHUB_TOKEN")
    github_webhook_secret: str = Field("", env="GITHUB_WEBHOOK_SECRET")
    redis_url: str = Field("redis://redis:6379/0", env="REDIS_URL")

    class Config:
        env_file = ".env"
        case_sensitive = False


@lru_cache()
def get_settings() -> Settings:
    """Return cached settings instance."""
    return Settings()


settings = get_settings()

__all__ = ["settings", "Settings", "get_settings"]

