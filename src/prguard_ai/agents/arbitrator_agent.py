"""Confidence arbitrator agent for PRGuard AI."""

from __future__ import annotations

import re
from collections import defaultdict
from typing import Dict, Iterable, List

from prguard_ai.confidence.scoring_engine import (
    aggregate_confidence,
    aggregate_confidence_tier,
    confidence_breakdown,
)
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


def _issue_tokens(issue: Issue) -> set[str]:
    text = f"{issue.file_path or ''} {issue.message} {issue.evidence}".lower()
    return {token for token in re.findall(r"[a-z0-9_]+", text) if len(token) > 2}


def _issue_similarity(left: Issue, right: Issue) -> float:
    line_score = 0.0
    if (left.file_path or "") == (right.file_path or ""):
        distance = abs(left.line - right.line)
        line_score = 1.0 if distance == 0 else max(0.0, 1.0 - (distance / 5.0))

    left_tokens = _issue_tokens(left)
    right_tokens = _issue_tokens(right)
    if not left_tokens and not right_tokens:
        text_score = 0.0
    else:
        text_score = len(left_tokens & right_tokens) / max(len(left_tokens | right_tokens), 1)
    return (line_score * 0.55) + (text_score * 0.45)


def deduplicate_issues(issues: Iterable[Issue], threshold: float = 0.72, hard_loc_match: bool = False) -> List[Issue]:
    """Cluster semantically similar issues and keep the strongest representative.

    When ``hard_loc_match`` is enabled, issues sharing the same ``(file_path,
    line)`` are treated as one cluster even if their wording differs. This is
    used to consolidate deterministic Semgrep findings with LLM findings that
    point at the same location, preventing duplicate PR comments.
    """
    clusters: List[List[Issue]] = []
    for issue in issues:
        for cluster in clusters:
            same_location = (
                hard_loc_match
                and (issue.file_path or "") == (cluster[0].file_path or "")
                and issue.line == cluster[0].line
            )
            if same_location or any(_issue_similarity(issue, existing) >= threshold for existing in cluster):
                cluster.append(issue)
                break
        else:
            clusters.append([issue])

    severity_rank = {"high": 3, "medium": 2, "low": 1}
    merged: List[Issue] = []
    for cluster in clusters:
        cluster.sort(
            key=lambda item: (
                severity_rank.get(item.severity.lower(), 0),
                len(item.evidence),
                len(item.message),
            ),
            reverse=True,
        )
        winner = cluster[0].model_copy()
        if len(cluster) > 1:
            sources = sorted({item.confidence_source for item in cluster})
            winner.confidence_source = "+".join(sources)
            winner.message = f"{winner.message} ({len(cluster)} agents/findings corroborated this.)"
        merged.append(winner)

    return sorted(merged, key=lambda item: (item.file_path or "", item.line, item.severity))


def resolve_conflicts(outputs: Iterable[AgentOutput]) -> List[str]:
    """Identify same-location severity disagreements for the final review narrative."""
    by_location: Dict[tuple[str, int], List[tuple[str, Issue]]] = defaultdict(list)
    for output in outputs:
        for issue in output.issues:
            by_location[(issue.file_path or "", issue.line)].append((output.agent, issue))

    conflicts: List[str] = []
    for (file_path, line), items in by_location.items():
        severities = {issue.severity for _, issue in items}
        if len(items) > 1 and len(severities) > 1:
            agent_bits = ", ".join(f"{agent}:{issue.severity}" for agent, issue in items)
            location = f"{file_path}:{line}" if file_path else f"line {line}"
            conflicts.append(f"Resolved severity conflict at {location} across {agent_bits}.")
    return conflicts


def aggregate_confidence_with_weights(outputs: Iterable[AgentOutput]) -> float:
    """Legacy numeric wrapper for internal metrics."""
    return aggregate_confidence(outputs)


def arbitrate_confidence(context: ReviewContext, partial: bool = False) -> PullRequestReport:
    """
    Aggregate agent outputs from context into a single pull request report.
    """
    outputs = list(context.agent_outputs.values())
    failed_outputs = [o for o in outputs if getattr(o, "error", None)]
    if partial:
        successful_outputs = [o for o in outputs if o not in failed_outputs]
    else:
        successful_outputs = outputs
        for output in failed_outputs:
            raise ValueError(f"Agent {output.agent} failed: {output.error}")

    failure_notes = [
        f"{output.agent} agent failed and was excluded from partial arbitration: {output.error}"
        for output in failed_outputs
    ]

    if not successful_outputs:
        report = PullRequestReport(
            overall_confidence=0.0,
            aggregate_tier=aggregate_confidence_tier([]),
            agent_outputs=outputs,
            issues=[],
            disagreements=failure_notes,
        )
        return report

    overall_confidence = aggregate_confidence_with_weights(successful_outputs)

    raw_issues: List[Issue] = [issue for output in successful_outputs for issue in output.issues]
    issues = deduplicate_issues(raw_issues, threshold=0.99, hard_loc_match=True)
    disagreements = detect_agent_disagreements(successful_outputs) + resolve_conflicts(successful_outputs)

    report = PullRequestReport(
        overall_confidence=overall_confidence,
        aggregate_tier=aggregate_confidence_tier(successful_outputs),
        tier_breakdown=confidence_breakdown(raw_issues),
        agent_outputs=outputs,
        issues=issues,
        disagreements=failure_notes + disagreements,
    )
    return report


__all__ = [
    "arbitrate_confidence",
    "aggregate_confidence_with_weights",
    "deduplicate_issues",
    "detect_agent_disagreements",
    "resolve_conflicts",
]
