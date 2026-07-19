"""Tests for the confidence scoring engine."""

from prguard_ai.confidence.scoring_engine import (
    aggregate_confidence,
    calculate_agent_confidence,
    calibrated_confidence,
    fit_platt_scaling,
    update_learned_weights,
)
from prguard_ai.schemas.agent_output import AgentOutput, Issue


def make_issue(severity: str, source: str) -> Issue:
    return Issue(
        line=1,
        severity=severity,
        message="msg",
        evidence="ev",
        confidence_source=source,
    )


def test_calculate_agent_confidence_uses_weights():
    base = AgentOutput(agent="test", confidence=0.5, issues=[make_issue("low", "rule_based")])
    refined = calculate_agent_confidence(base)
    assert 0.5 < refined <= 1.0


def test_aggregate_confidence_handles_multiple_agents():
    outputs = [
        AgentOutput(agent="a", confidence=0.5, issues=[make_issue("high", "rule_based")]),
        AgentOutput(agent="b", confidence=0.4, issues=[make_issue("low", "inferred")]),
    ]
    score = aggregate_confidence(outputs)
    assert 0.0 <= score <= 1.0


def test_aggregate_confidence_empty():
    assert aggregate_confidence([]) == 0.0


def test_calibrated_confidence_includes_uncertainty():
    calibrated = calibrated_confidence(0.85, sample_count=100)

    assert 0.0 <= calibrated.lower <= calibrated.probability <= calibrated.upper <= 1.0
    assert calibrated.margin < 0.2


def test_platt_scaling_learns_from_feedback():
    slope, intercept = fit_platt_scaling([(0.9, 1), (0.8, 1), (0.2, 0), (0.1, 0)])

    assert slope > 0
    assert calibrated_confidence(0.9, slope=slope, intercept=intercept).probability > calibrated_confidence(
        0.2, slope=slope, intercept=intercept
    ).probability


def test_update_learned_weights_replaces_hardcoded_source_scores():
    weights = update_learned_weights([("llm_reasoning", 1), ("llm_reasoning", 0), ("llm_reasoning", 1)])

    assert weights["llm_reasoning"] == 0.6667
