from __future__ import annotations

from prguard_ai.agents.coordinator import CoordinatorAgent
from prguard_ai.schemas.agent_output import AgentOutput, Issue
from prguard_ai.schemas.context import ReviewContext


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
