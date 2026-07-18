from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field
from prguard_ai.schemas.agent_output import AgentOutput


class DialogueTurn(BaseModel):
    """Represents a single message sent during the multi-agent dialogue."""

    speaker: str = Field(..., description="The name of the agent speaking.")
    message: str = Field(..., description="The natural language message sent by the agent.")
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="Timestamp when the message was sent.",
    )


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
    dialogue: List[DialogueTurn] = Field(
        default_factory=list, description="Debate and dialogue history between the agents."
    )
    sandbox_path: Optional[str] = Field(
        default=None,
        description="Optional sandbox path holding the checked-out repository during analysis.",
    )


__all__ = ["ReviewContext", "DialogueTurn"]
