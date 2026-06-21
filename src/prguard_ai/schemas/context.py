from __future__ import annotations

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field
from prguard_ai.schemas.agent_output import AgentOutput


class ReviewContext(BaseModel):
    """Shared review context for multi-agent PR analysis and refinement."""

    pr_id: str = Field(..., description="Unique pull request identifier (e.g. repo#num).")
    diff_text: str = Field(..., description="The Git diff text of the PR.")
    repo_metadata: Optional[Dict[str, Any]] = Field(
        default=None, description="Optional metadata about the repository."
    )
    agent_outputs: Dict[str, AgentOutput] = Field(
        default_factory=dict, description="Initial and refined outputs from each agent."
    )
    round: int = Field(default=0, description="Current refinement/dialogue round.")


__all__ = ["ReviewContext"]
