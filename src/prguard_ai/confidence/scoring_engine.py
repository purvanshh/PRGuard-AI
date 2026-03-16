"""Confidence scoring engine for PRGuard AI."""

from __future__ import annotations

from typing import Iterable, Dict

from prguard_ai.schemas.agent_output import AgentOutput, Issue


CONFIDENCE_WEIGHTS: Dict[str, float] = {
    "rule_based": 0.9,
    "llm_reasoning": 0.6,
    "inferred": 0.3,
}


def _weight_for_source(source: str) -> float:
    """Return a numeric weight for a confidence source label."""
    return CONFIDENCE_WEIGHTS.get(source, CONFIDENCE_WEIGHTS["inferred"])


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


__all__ = ["calculate_agent_confidence", "aggregate_confidence"]

