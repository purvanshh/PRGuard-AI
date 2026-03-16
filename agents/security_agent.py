"""Security analysis agent for PRGuard AI."""

from typing import List, Dict, Any

from schemas.agent_output import AgentOutput, Issue


SUSPECT_KEYWORDS = ["eval(", "exec(", "subprocess.Popen", "os.system"]


def analyze_security(diff_text: str, repo_metadata: Dict[str, Any] | None = None) -> AgentOutput:
    """
    Perform a lightweight security analysis on the given diff.

    This placeholder implementation flags added lines containing obviously dangerous APIs.

    Args:
        diff_text: Unified diff string for the pull request.
        repo_metadata: Optional metadata about the repository or PR.

    Returns:
        AgentOutput containing detected security issues.
    """
    issues: List[Issue] = []
    for idx, line in enumerate(diff_text.splitlines(), start=1):
        if not line.startswith("+") or line.startswith("+++"):
            continue
        content = line[1:]
        for keyword in SUSPECT_KEYWORDS:
            if keyword in content:
                issues.append(
                    Issue(
                        line=idx,
                        severity="high",
                        message=f"Potentially unsafe usage detected: {keyword}",
                        evidence=content[:200],
                        confidence_source="rule_based",
                    )
                )
                break

    confidence = 0.9 if issues else 0.6
    return AgentOutput(agent="security", confidence=confidence, issues=issues)


__all__ = ["analyze_security"]

