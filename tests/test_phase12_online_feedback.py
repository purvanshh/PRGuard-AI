from prguard_ai.evaluation.online_feedback import (
    assign_variant,
    finding_key,
    reaction_to_score,
    recalibrate_confidence,
    serialize_shadow_findings,
)
from prguard_ai.schemas.agent_output import Issue


def test_github_reaction_scores():
    assert reaction_to_score("+1") == 1.0
    assert reaction_to_score("-1") == 0.0
    assert reaction_to_score("eyes") is None


def test_feedback_links_to_finding_key():
    issue = Issue(line=7, severity="high", message="Unsafe eval", evidence="eval(x)", confidence_source="rule_based", file_path="src/app.py")
    assert finding_key("owner/repo#1", issue) == finding_key("owner/repo#1", issue)


def test_confidence_recalibration_returns_platt_parameters():
    slope, intercept = recalibrate_confidence([(0.9, 1), (0.8, 1), (0.2, 0), (0.1, 0)])
    assert slope > 0
    assert abs(intercept) < 5


def test_ab_routing_is_stable_and_rollout_bound():
    first = assign_variant("owner/repo#1", experiment="agent-v2", rollout=0.10)
    second = assign_variant("owner/repo#1", experiment="agent-v2", rollout=0.10)
    assert first == second
    assert assign_variant("owner/repo#1", experiment="agent-v2", rollout=0.0) == "current"
    assert assign_variant("owner/repo#1", experiment="agent-v2", rollout=1.0) == "candidate"


def test_shadow_findings_are_serialized_without_posting_state():
    issue = Issue(line=1, severity="low", message="msg", evidence="ev", confidence_source="inferred", file_path="a.py")
    payload = serialize_shadow_findings([issue])
    assert '"message": "msg"' in payload
