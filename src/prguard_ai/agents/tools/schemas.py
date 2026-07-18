"""Typed schemas for agent tool invocations."""

from __future__ import annotations

from typing import Any, Dict, Optional

from pydantic import BaseModel, Field


class ToolInvocation(BaseModel):
    """A single requested tool invocation."""

    tool: str = Field(..., description="Tool name.")
    args: Dict[str, Any] = Field(default_factory=dict, description="Tool arguments.")
    rationale: str = Field(default="", description="Why the agent is calling the tool.")


class ToolResult(BaseModel):
    """Structured result returned by a tool call."""

    tool: str
    ok: bool = True
    output: Any = None
    error: Optional[str] = None


class ToolCallRecord(BaseModel):
    """Persisted record of a tool invocation and its result."""

    invocation: ToolInvocation
    result: ToolResult

