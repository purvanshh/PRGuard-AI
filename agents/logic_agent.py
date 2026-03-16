"""Logic analysis agent for PRGuard AI."""

from typing import List, Dict, Any

from schemas.agent_output import AgentOutput, Issue


def analyze_logic(diff_text: str, repo_metadata: Dict[str, Any] | None = None) -> AgentOutput:
    """
    Perform a lightweight logical correctness analysis on the given diff.

    This placeholder implementation only checks for obvious TODO markers in added lines.

    Args:
        diff_text: Unified diff string for the pull request.
        repo_metadata: Optional metadata about the repository or PR.

    Returns:
        AgentOutput containing detected logical issues.
    """
    issues: List[Issue] = []
    for idx, line in enumerate(diff_text.splitlines(), start=1):
        if line.startswith("+") and "TODO" in line:
            issues.append(
                Issue(
                    line=idx,
                    severity="low",
                    message="Found TODO in added code (placeholder logical rule).",
                    evidence=line[1:200],
                    confidence_source="inferred",
                )
            )

    confidence = 0.7 if issues else 0.5
    return AgentOutput(agent="logic", confidence=confidence, issues=issues)


__all__ = ["analyze_logic"]

