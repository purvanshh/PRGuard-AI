"""Pydantic models representing aggregated pull request reports."""

from __future__ import annotations

from typing import Dict, List

from pydantic import BaseModel, Field

from prguard_ai.confidence.scoring_engine import ConfidenceTier, confidence_breakdown

from .agent_output import AgentOutput, Issue


class PullRequestReport(BaseModel):
    """Represents the overall AI analysis result for a pull request."""

    overall_confidence: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Aggregated confidence across all agents.",
    )
    confidence_interval: tuple[float, float] | None = Field(
        default=None,
        description="Deprecated numeric compatibility bounds.",
    )
    aggregate_tier: ConfidenceTier = Field(default=ConfidenceTier.LOW, description="Tiered review confidence.")
    tier_breakdown: Dict[str, int] = Field(
        default_factory=dict,
        description="Raw evidence counts behind the confidence tier.",
    )
    agent_outputs: List[AgentOutput] = Field(
        default_factory=list, description="Per-agent structured outputs."
    )
    issues: List[Issue] = Field(
        default_factory=list,
        description="Flattened list of issues collected from all agents.",
    )
    disagreements: List[str] = Field(
        default_factory=list,
        description="High-level notes where agents disagree or emphasize different risks.",
    )

    def to_markdown(self) -> str:
        """Render the report as a Markdown PR comment body."""
        lines: List[str] = []
        lines.append("## PRGuard AI Review")
        lines.append("")
        breakdown = self.tier_breakdown or confidence_breakdown(self.issues)
        lines.append(
            f"**Confidence:** {self.aggregate_tier.value.title()} "
            f"({breakdown.get('rule_based', 0)} rule-based, "
            f"{breakdown.get('llm_reasoning', 0)} LLM-reasoned, "
            f"{breakdown.get('verified', 0)} verified by tool)"
        )
        lines.append("")

        lines.append("### Findings")
        if not self.issues:
            lines.append("_No issues detected._")
        else:
            for issue in self.issues:
                location = f"{issue.file_path}:{issue.line}" if issue.file_path else f"line {issue.line}"
                lines.append(f"- `{issue.severity.upper()}` `{location}`: {issue.message}")
                lines.append(f"  - Evidence: {issue.evidence}")
                lines.append(f"  - Confidence basis: {issue.confidence_source}")
        lines.append("")

        lines.append("### Disagreement Summary")
        if self.disagreements:
            for d in self.disagreements:
                lines.append(f"- {d}")
        else:
            lines.append("_No major disagreements detected between agents._")

        return "\n".join(lines)

    def summary_stats(self) -> Dict[str, int]:
        """Return simple counts of issues by severity."""
        counts: Dict[str, int] = {"high": 0, "medium": 0, "low": 0}
        for issue in self.issues:
            key = issue.severity.lower()
            if key in counts:
                counts[key] += 1
        return counts


__all__ = ["PullRequestReport"]
