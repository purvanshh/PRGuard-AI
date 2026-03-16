"""Tests for the confidence scoring engine."""

from confidence.scoring_engine import calculate_agent_confidence, aggregate_confidence
from schemas.agent_output import AgentOutput, Issue


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

