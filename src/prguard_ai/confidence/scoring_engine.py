"""Confidence scoring engine for PRGuard AI."""

from __future__ import annotations

from typing import Iterable, Dict

from prguard_ai.schemas.agent_output import AgentOutput, Issue


CONFIDENCE_WEIGHTS: Dict[str, float] = {
    "rule_based": 0.9,
    "llm_reasoning": 0.6,
    "refined": 0.7,
    "inferred": 0.3,
}
SEVERITY_CONFIDENCE_WEIGHTS: Dict[str, float] = {
    "low": 0.45,
    "medium": 0.65,
    "high": 0.85,
}


def _weight_for_source(source: str) -> float:
    """Return a numeric weight for a confidence source label."""
    return CONFIDENCE_WEIGHTS.get(source, CONFIDENCE_WEIGHTS["inferred"])


def estimate_issue_confidence(
    issues: Iterable[Issue],
    *,
    empty_confidence: float,
    max_issue_bonus: float = 0.09,
) -> float:
    """
    Estimate an agent confidence directly from the detected issues.

    This keeps base agent confidence aligned with the quality of the findings
    before the arbitrator applies its own cross-agent refinement.
    """
    issues_list = list(issues)
    if not issues_list:
        return max(0.0, min(1.0, empty_confidence))

    combined_scores = []
    for issue in issues_list:
        source_score = _weight_for_source(issue.confidence_source)
        severity_score = SEVERITY_CONFIDENCE_WEIGHTS.get(
            issue.severity.lower(),
            SEVERITY_CONFIDENCE_WEIGHTS["low"],
        )
        combined_scores.append((source_score + severity_score) / 2.0)

    avg_score = sum(combined_scores) / len(combined_scores)
    issue_bonus = min(len(issues_list), 3) * (max_issue_bonus / 3.0)
    return max(0.0, min(1.0, avg_score + issue_bonus))


def calculate_agent_confidence(output: AgentOutput) -> float:
    """
    Calculate a refined confidence score for a single agent output.

    The base agent confidence is adjusted according to the mix of confidence sources
    in its issues using the configured weights.
    """
    if not output.issues:
        return output.confidence

    total_weight = 0.0
    for issue in output.issues:
        total_weight += _weight_for_source(issue.confidence_source)

    avg_weight = total_weight / max(len(output.issues), 1)
    # Blend the original confidence with the average weight.
    refined = (output.confidence + avg_weight) / 2.0
    return max(0.0, min(1.0, refined))


def aggregate_confidence(outputs: Iterable[AgentOutput]) -> float:
    """
    Aggregate confidence across agents into a single score.

    Each agent's refined confidence is averaged, with additional influence from
    the highest-severity issues.
    """
    outputs_list = list(outputs)
    if not outputs_list:
        return 0.0

    refined_scores = [calculate_agent_confidence(o) for o in outputs_list]
    base_avg = sum(refined_scores) / len(refined_scores)

    # Boost slightly if any high-severity issues exist.
    has_high_severity = any(
        issue.severity.lower() == "high" for o in outputs_list for issue in o.issues
    )
    if has_high_severity:
        base_avg = min(1.0, base_avg + 0.1)

    return base_avg


__all__ = ["calculate_agent_confidence", "aggregate_confidence", "estimate_issue_confidence"]
