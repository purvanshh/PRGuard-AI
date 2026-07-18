"""Strict GitHub webhook payload models."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator


class WebhookRepository(BaseModel):
    model_config = ConfigDict(extra="forbid")

    full_name: str = Field(pattern=r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
    clone_url: HttpUrl | None = None
    html_url: HttpUrl | None = None

    @field_validator("full_name")
    @classmethod
    def no_parent_segments(cls, value: str) -> str:
        owner, repo = value.split("/", 1)
        if owner in {".", ".."} or repo in {".", ".."} or ".." in {owner, repo}:
            raise ValueError("Repository name cannot contain parent-directory segments.")
        return value


class WebhookInstallation(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: int


class WebhookPullRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    number: int | None = None


class WebhookPayload(BaseModel):
    model_config = ConfigDict(extra="ignore")

    action: str
    number: int = Field(gt=0)
    repository: WebhookRepository
    pull_request: WebhookPullRequest | None = None
    installation: WebhookInstallation | None = None


__all__ = ["WebhookPayload", "WebhookRepository", "WebhookInstallation", "WebhookPullRequest"]
