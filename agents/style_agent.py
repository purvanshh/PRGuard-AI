"""Style analysis agent for PRGuard AI."""

from typing import List, Dict, Any

from schemas.agent_output import AgentOutput, Issue


def analyze_style(diff_text: str, repo_metadata: Dict[str, Any] | None = None) -> AgentOutput:
    """
    Perform a lightweight style analysis on the given diff.

    This is a placeholder implementation that flags long lines as style issues.

    Args:
        diff_text: Unified diff string for the pull request.
        repo_metadata: Optional additional metadata about the repository or PR.

    Returns:
        AgentOutput containing detected style issues.
    """
    issues: List[Issue] = []
    for idx, line in enumerate(diff_text.splitlines(), start=1):
        if line.startswith("+") and not line.startswith("+++"):
            content = line[1:]
            if len(content) > 120:
                issues.append(
                    Issue(
                        line=idx,
                        severity="medium",
                        message="Line exceeds 120 characters (placeholder style rule).",
                        evidence=content[:200],
                        confidence_source="rule_based",
                    )
                )

    confidence = 0.8 if issues else 0.4
    return AgentOutput(agent="style", confidence=confidence, issues=issues)


__all__ = ["analyze_style"]

