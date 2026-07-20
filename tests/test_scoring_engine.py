"""Tests for the confidence scoring engine."""

from prguard_ai.confidence.scoring_engine import (
    aggregate_confidence,
    aggregate_confidence_tier,
    calculate_agent_confidence,
    compute_confidence_tier,
    ConfidenceTier,
)
from prguard_ai.schemas.agent_output import AgentOutput, Issue


def make_issue(severity: str, source: str) -> Issue:
    return Issue(
        line=1,
        severity=severity,
        message="msg",
        evidence="ev",
        confidence_source=source,
        verified=source == "rule_based",
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
    assert aggregate_confidence([]) == 0.3


def test_tier_high_for_verified_rule_based_findings():
    output = AgentOutput(
        agent="security",
        confidence=0.5,
        issues=[make_issue("high", "rule_based"), make_issue("medium", "rule_based")],
    )

    assert compute_confidence_tier(output) == ConfidenceTier.HIGH


def test_tier_low_for_unverified_inferred_findings():
    output = AgentOutput(
        agent="logic",
        confidence=0.5,
        issues=[Issue(line=1, severity="medium", message="x", evidence="y", confidence_source="inferred")],
    )

    assert compute_confidence_tier(output) == ConfidenceTier.LOW


def test_aggregate_tier_downgrades_unverified_high_severity():
    outputs = [
        AgentOutput(
            agent="security",
            confidence=0.5,
            issues=[Issue(line=1, severity="high", message="x", evidence="y", confidence_source="llm_reasoning")],
        )
    ]

    assert aggregate_confidence_tier(outputs) == ConfidenceTier.LOW
