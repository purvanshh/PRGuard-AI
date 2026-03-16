"""Pydantic models representing aggregated pull request reports."""

from __future__ import annotations

from typing import List

from pydantic import BaseModel, Field

from .agent_output import AgentOutput, Issue


class PullRequestReport(BaseModel):
    """Represents the overall AI analysis result for a pull request."""

    overall_confidence: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Aggregated confidence across all agents.",
    )
    agent_outputs: List[AgentOutput] = Field(
        default_factory=list, description="Per-agent structured outputs."
    )
    issues: List[Issue] = Field(
        default_factory=list,
        description="Flattened list of issues collected from all agents.",
    )


__all__ = ["PullRequestReport"]

