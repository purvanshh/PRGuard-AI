from __future__ import annotations

from prguard_ai.agents.coordinator import CoordinatorAgent
from prguard_ai.schemas.agent_output import AgentOutput, Issue
from prguard_ai.schemas.context import DialogueTurn, ReviewContext


def test_coordinator_produces_guidance():
    context = ReviewContext(
        pr_id="owner/repo#1",
        diff_text="diff --git a/foo.py b/foo.py\n+eval(user_input)",
        agent_outputs={
            "style": AgentOutput(agent="style", confidence=0.5, issues=[]),
            "logic": AgentOutput(
                agent="logic",
                confidence=0.6,
                issues=[
                    Issue(
                        line=2,
                        severity="medium",
                        message="Input validation is unclear.",
                        evidence="eval(user_input)",
                        confidence_source="llm_reasoning",
                        file_path="foo.py",
                    )
                ],
            ),
            "security": AgentOutput(
                agent="security",
                confidence=0.8,
                issues=[
                    Issue(
                        line=2,
                        severity="high",
                        message="Use of eval/exec detected; this is often unsafe.",
                        evidence="eval(user_input)",
                        confidence_source="rule_based",
                        file_path="foo.py",
                    )
                ],
            ),
        },
    )

    guidance = CoordinatorAgent.moderate_round(context)

    assert guidance["critiques"]
    assert guidance["steering_questions"]


def test_convergence_state_tracks_high_severity_disagreement():
    context = ReviewContext(
        pr_id="owner/repo#1",
        diff_text="diff",
        agent_outputs={
            "style": AgentOutput(agent="style", confidence=0.5, issues=[]),
            "security": AgentOutput(
                agent="security",
                confidence=0.9,
                issues=[
                    Issue(
                        line=2,
                        severity="high",
                        message="Unsafe eval.",
                        evidence="eval(user_input)",
                        confidence_source="rule_based",
                    )
                ],
            ),
        },
    )

    state = CoordinatorAgent.convergence_state(context)

    assert state["active_agents"] == ["security", "style"]
    assert state["high_severity_agents"] == ["security"]
    assert state["unresolved_high_disagreement"] is True


def test_should_stop_continues_on_unresolved_high_severity_disagreement():
    context = ReviewContext(
        pr_id="owner/repo#1",
        diff_text="diff",
        round=1,
        dialogue=[
            DialogueTurn(speaker="style", message=""),
            DialogueTurn(speaker="security", message=""),
        ],
        agent_outputs={
            "style": AgentOutput(agent="style", confidence=0.5, issues=[]),
            "security": AgentOutput(
                agent="security",
                confidence=0.9,
                issues=[
                    Issue(
                        line=2,
                        severity="high",
                        message="Unsafe eval.",
                        evidence="eval(user_input)",
                        confidence_source="rule_based",
                    )
                ],
            ),
        },
    )

    assert CoordinatorAgent.should_stop(context, max_rounds=3) is False
