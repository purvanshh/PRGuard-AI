"""Pydantic models representing aggregated pull request reports."""

from __future__ import annotations

from typing import Dict, List

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
    disagreements: List[str] = Field(
        default_factory=list,
        description="High-level notes where agents disagree or emphasize different risks.",
    )

    def to_markdown(self) -> str:
        """Render the report as a Markdown PR comment body."""
        lines: List[str] = []
        lines.append("## PRGuard AI Review")
        lines.append("")
        lines.append(f"**Confidence Score:** {self.overall_confidence:.2f}")
        lines.append("")

        sections: Dict[str, List[Issue]] = {"style": [], "logic": [], "security": []}
        for output in self.agent_outputs:
            agent_name = output.agent.lower()
            if agent_name in sections:
                sections[agent_name].extend(output.issues)

        def _render_section(title: str, issues: List[Issue]) -> None:
            lines.append(f"### {title}")
            if not issues:
                lines.append("_No issues detected._")
            else:
                for issue in issues:
                    lines.append(
                        f"- `{issue.severity.upper()}` (line {issue.line}): {issue.message}"
                    )
            lines.append("")

        _render_section("Style", sections["style"])
        _render_section("Logic", sections["logic"])
        _render_section("Security", sections["security"])

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

