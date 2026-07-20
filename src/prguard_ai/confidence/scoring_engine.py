"""Tiered confidence scoring for PRGuard AI."""

from __future__ import annotations

from enum import Enum
from typing import Dict, Iterable

from prguard_ai.schemas.agent_output import AgentOutput, Issue


class ConfidenceTier(str, Enum):
    """Human-readable confidence tiers with no fake decimal precision."""

    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


TIER_TO_NUMERIC: Dict[ConfidenceTier, float] = {
    ConfidenceTier.HIGH: 0.9,
    ConfidenceTier.MEDIUM: 0.6,
    ConfidenceTier.LOW: 0.3,
}

SOURCE_WEIGHTS: Dict[str, float] = {
    "rule_based": 0.88,
    "llm_reasoning": 0.62,
    "refined": 0.72,
    "inferred": 0.38,
}
SEVERITY_WEIGHTS: Dict[str, float] = {
    "high": 0.9,
    "medium": 0.72,
    "low": 0.45,
}


def _counts(issues: Iterable[Issue]) -> dict[str, int]:
    items = list(issues)
    return {
        "total": len(items),
        "rule_based": sum(1 for issue in items if issue.confidence_source == "rule_based"),
        "llm_reasoning": sum(1 for issue in items if issue.confidence_source == "llm_reasoning"),
        "inferred": sum(1 for issue in items if issue.confidence_source == "inferred"),
        "verified": sum(1 for issue in items if issue.verified),
    }


def confidence_breakdown(issues: Iterable[Issue]) -> dict[str, int]:
    """Return raw confidence evidence counts for review text and logs."""
    return _counts(issues)


def compute_confidence_tier(agent_output: AgentOutput) -> ConfidenceTier:
    """Return a confidence tier for one agent output."""
    if not agent_output.issues:
        return ConfidenceTier.HIGH

    counts = _counts(agent_output.issues)
    total = max(counts["total"], 1)
    rule_ratio = counts["rule_based"] / total
    verified_ratio = counts["verified"] / total
    inferred_ratio = counts["inferred"] / total

    if rule_ratio > 0.5 and verified_ratio > 0.5:
        return ConfidenceTier.HIGH
    if inferred_ratio > 0.5 or verified_ratio < 0.2:
        return ConfidenceTier.LOW
    return ConfidenceTier.MEDIUM


def aggregate_confidence_tier(outputs: Iterable[AgentOutput]) -> ConfidenceTier:
    """Aggregate confidence tiers conservatively across agents."""
    outputs_list = list(outputs)
    if not outputs_list:
        return ConfidenceTier.LOW

    tiers = [compute_confidence_tier(output) for output in outputs_list]
    has_unverified_high = any(
        issue.severity == "high" and not issue.verified
        for output in outputs_list
        for issue in output.issues
    )
    if ConfidenceTier.LOW in tiers or has_unverified_high:
        return ConfidenceTier.LOW
    if ConfidenceTier.MEDIUM in tiers:
        return ConfidenceTier.MEDIUM
    return ConfidenceTier.HIGH


def estimate_issue_confidence(
    issues: Iterable[Issue],
    *,
    empty_confidence: float,
    max_issue_bonus: float = 0.09,
) -> float:
    """Estimate legacy numeric confidence while user-facing output stays tiered."""
    issues_list = list(issues)
    if not issues_list:
        return empty_confidence

    scores = []
    for issue in issues_list:
        source_score = SOURCE_WEIGHTS.get(issue.confidence_source, SOURCE_WEIGHTS["inferred"])
        severity_score = SEVERITY_WEIGHTS.get(issue.severity.lower(), SEVERITY_WEIGHTS["low"])
        verification_bonus = 0.04 if issue.verified else 0.0
        scores.append(min(1.0, (source_score + severity_score) / 2 + verification_bonus))

    issue_bonus = min(len(issues_list), 3) * (max_issue_bonus / 3.0)
    return max(0.0, min(1.0, sum(scores) / len(scores) + issue_bonus))


def calculate_agent_confidence(output: AgentOutput) -> float:
    """Legacy numeric adapter for code paths that still store floats internally."""
    return TIER_TO_NUMERIC[compute_confidence_tier(output)]


def aggregate_confidence(outputs: Iterable[AgentOutput]) -> float:
    """Legacy numeric adapter for metrics; user-facing output should use tiers."""
    return TIER_TO_NUMERIC[aggregate_confidence_tier(outputs)]


__all__ = [
    "ConfidenceTier",
    "aggregate_confidence",
    "aggregate_confidence_tier",
    "calculate_agent_confidence",
    "compute_confidence_tier",
    "confidence_breakdown",
    "estimate_issue_confidence",
]
