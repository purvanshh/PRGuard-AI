"""Application settings for PRGuard AI."""

from __future__ import annotations

from pydantic import BaseSettings, Field


class Settings(BaseSettings):
    """Environment-driven configuration settings."""

    openai_api_key: str = Field("", env="OPENAI_API_KEY")
    github_token: str = Field("", env="GITHUB_TOKEN")
    github_webhook_secret: str = Field("", env="GITHUB_WEBHOOK_SECRET")
    redis_url: str = Field("redis://redis:6379/0", env="REDIS_URL")
    chroma_persist_dir: str = Field(".chroma", env="CHROMA_PERSIST_DIR")

    class Config:
        env_file = ".env"
        case_sensitive = False


settings = Settings()

__all__ = ["settings", "Settings"]


