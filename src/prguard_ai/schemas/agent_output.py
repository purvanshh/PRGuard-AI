"""Pydantic models representing agent outputs for PRGuard AI."""

from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field, field_validator


class Issue(BaseModel):
    """Represents a single issue detected by an analysis agent."""

    line: int = Field(..., ge=1, description="1-based line number in the file or diff.")
    severity: str = Field(..., description="Issue severity such as low, medium, high.")
    message: str = Field(..., description="Human-readable description of the issue.")
    evidence: str = Field(..., description="Excerpt or snippet supporting the finding.")
    confidence_source: str = Field(
        ..., description="Source of confidence, e.g. rule_based, llm_reasoning, inferred."
    )
    file_path: Optional[str] = Field(
        default=None,
        description="Optional path to the file where the issue was detected.",
    )

    @field_validator("severity")
    @classmethod
    def _normalize_severity(cls, value: str) -> str:
        return value.lower()

    @classmethod
    def validate_and_sanitize(cls, item: object) -> Issue:
        """Validate and sanitize an issue dictionary/object."""
        import html
        
        if isinstance(item, cls):
            validated = item.model_copy()
        elif isinstance(item, dict):
            validated = cls.model_validate(item)
        else:
            raise TypeError(f"Expected dict or Issue, got {type(item)}")

        def sanitize(s: str) -> str:
            cleaned = "".join(c for c in s if c.isprintable() or c in "\n\r\t")
            return html.escape(cleaned)

        validated.message = sanitize(validated.message)
        validated.evidence = sanitize(validated.evidence)
        return validated


class AgentOutput(BaseModel):
    """Structured output produced by a single analysis agent."""

    agent: str = Field(..., description="Agent name, e.g. style, logic, security.")
    confidence: float = Field(..., ge=0.0, le=1.0, description="Overall agent confidence.")
    issues: List[Issue] = Field(default_factory=list, description="List of detected issues.")
    llm_skipped: bool = Field(default=False, description="Flag indicating if LLM processing was skipped.")
    error: Optional[str] = Field(default=None, description="Optional error message if the agent run failed.")


__all__ = ["Issue", "AgentOutput"]

