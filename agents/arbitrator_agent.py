"""Confidence arbitrator agent for PRGuard AI."""

from typing import Iterable, List

from confidence.scoring_engine import aggregate_confidence
from schemas.agent_output import AgentOutput
from schemas.pr_report import PullRequestReport


def arbitrate_confidence(agent_outputs: Iterable[AgentOutput]) -> PullRequestReport:
    """
    Aggregate agent outputs into a single pull request report.

    Args:
        agent_outputs: Iterable of AgentOutput from all analysis agents.

    Returns:
        PullRequestReport containing combined issues and overall confidence score.
    """
    outputs: List[AgentOutput] = list(agent_outputs)
    overall_confidence = aggregate_confidence(outputs)

    issues = [issue for output in outputs for issue in output.issues]
    return PullRequestReport(
        overall_confidence=overall_confidence,
        agent_outputs=outputs,
        issues=issues,
    )


__all__ = ["arbitrate_confidence"]

