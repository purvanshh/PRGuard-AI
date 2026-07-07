"""Confidence arbitrator agent for PRGuard AI."""

from __future__ import annotations

from typing import Dict, Iterable, List, Tuple

from prguard_ai.confidence.scoring_engine import aggregate_confidence, calculate_agent_confidence
from prguard_ai.schemas.agent_output import AgentOutput, Issue
from prguard_ai.schemas.pr_report import PullRequestReport
from prguard_ai.schemas.context import ReviewContext


def detect_agent_disagreements(outputs: Iterable[AgentOutput]) -> List[str]:
    """
    Detect high-level disagreements between agents based on severity patterns.
    """
    outputs_list = list(outputs)
    if not outputs_list:
        return []

    disagreements: List[str] = []
    agent_issue_summary: Dict[str, Dict[str, int]] = {}

    for o in outputs_list:
        summary: Dict[str, int] = {"high": 0, "medium": 0, "low": 0}
        for issue in o.issues:
            sev = issue.severity.lower()
            if sev in summary:
                summary[sev] += 1
        agent_issue_summary[o.agent] = summary

    for agent_a, summary_a in agent_issue_summary.items():
        for agent_b, summary_b in agent_issue_summary.items():
            if agent_a >= agent_b:
                continue
            high_a = summary_a["high"]
            high_b = summary_b["high"]
            if high_a > 0 and high_b == 0:
                disagreements.append(
                    f"{agent_a} reports high-severity issues while {agent_b} does not."
                )
            if high_b > 0 and high_a == 0:
                disagreements.append(
                    f"{agent_b} reports high-severity issues while {agent_a} does not."
                )

    return disagreements


def aggregate_confidence_with_weights(outputs: Iterable[AgentOutput]) -> float:
    """
    Wrapper over aggregate_confidence for clarity.
    """
    return aggregate_confidence(outputs)


def arbitrate_confidence(context: ReviewContext, partial: bool = False) -> PullRequestReport:
    """
    Aggregate agent outputs from context into a single pull request report.
    """
    outputs = list(context.agent_outputs.values())
    if partial:
        successful_outputs = [o for o in outputs if not getattr(o, "error", None)]
    else:
        successful_outputs = outputs
        for o in outputs:
            if getattr(o, "error", None):
                raise ValueError(f"Agent {o.agent} failed: {o.error}")

    if not successful_outputs:
        report = PullRequestReport(
            overall_confidence=0.0,
            agent_outputs=outputs,
            issues=[],
        )
        setattr(report, "disagreements", [])
        return report

    overall_confidence = aggregate_confidence_with_weights(successful_outputs)

    issues: List[Issue] = [issue for output in successful_outputs for issue in output.issues]
    disagreements = detect_agent_disagreements(successful_outputs)

    report = PullRequestReport(
        overall_confidence=overall_confidence,
        agent_outputs=outputs,
        issues=issues,
    )
    # Attach disagreements into the model via a dynamic attribute for downstream use.
    setattr(report, "disagreements", disagreements)
    return report


__all__ = ["arbitrate_confidence", "detect_agent_disagreements"]

