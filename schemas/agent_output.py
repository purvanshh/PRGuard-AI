"""Pydantic models representing agent outputs for PRGuard AI."""

from __future__ import annotations

from typing import List

from pydantic import BaseModel, Field, validator


class Issue(BaseModel):
    """Represents a single issue detected by an analysis agent."""

    line: int = Field(..., ge=1, description="1-based line number in the file or diff.")
    severity: str = Field(..., description="Issue severity such as low, medium, high.")
    message: str = Field(..., description="Human-readable description of the issue.")
    evidence: str = Field(..., description="Excerpt or snippet supporting the finding.")
    confidence_source: str = Field(
        ..., description="Source of confidence, e.g. rule_based, llm_reasoning, inferred."
    )

    @validator("severity")
    def _normalize_severity(cls, value: str) -> str:
        return value.lower()


class AgentOutput(BaseModel):
    """Structured output produced by a single analysis agent."""

    agent: str = Field(..., description="Agent name, e.g. style, logic, security.")
    confidence: float = Field(..., ge=0.0, le=1.0, description="Overall agent confidence.")
    issues: List[Issue] = Field(default_factory=list, description="List of detected issues.")


__all__ = ["Issue", "AgentOutput"]

