from __future__ import annotations

import json
from unittest.mock import MagicMock
import pytest

from prguard_ai.schemas.agent_output import AgentOutput, Issue
from prguard_ai.schemas.context import ReviewContext, DialogueTurn
from prguard_ai.agents.style_agent import StyleAgent
from prguard_ai.agents.logic_agent import LogicAgent
from prguard_ai.agents.security_agent import SecurityAgent
from prguard_ai.agents.coordinator import CoordinatorAgent
from prguard_ai.task_queue.celery_app import celery_app
from prguard_ai.task_queue.orchestrator import review_pr
from prguard_ai.db.redis_client import get_review_context
import prguard_ai.llm.client as llm_client


def test_style_agent_refine(monkeypatch):
    initial_output = AgentOutput(
        agent="style",
        confidence=0.5,
        issues=[
            Issue(
                line=10,
                severity="low",
                message="Initial style issue",
                evidence="evidence",
                confidence_source="llm_reasoning",
            )
        ],
    )
    context = ReviewContext(
        pr_id="test#1",
        diff_text="diff --git a/foo.py b/foo.py\n+new line",
        agent_outputs={
            "style": initial_output,
            "logic": AgentOutput(agent="logic", confidence=0.6, issues=[]),
            "security": AgentOutput(agent="security", confidence=0.7, issues=[]),
        },
    )

    mocked_response = {
        "message": "I agree with other agents. Added a refined issue on line 12.",
        "issues": [
            {
                "line": 10,
                "severity": "low",
                "message": "Initial style issue",
                "evidence": "evidence",
                "confidence_source": "llm_reasoning",
                "file_path": "foo.py",
            },
            {
                "line": 12,
                "severity": "medium",
                "message": "Refined style issue",
                "evidence": "new evidence",
                "confidence_source": "refined",
                "file_path": "foo.py",
            },
        ],
    }

    def _mock_gen(prompt, *args, **kwargs):
        return json.dumps(mocked_response), {}

    monkeypatch.setattr("prguard_ai.agents.style_agent.generate_analysis", _mock_gen)

    message, refined = StyleAgent.refine(initial_output, context)
    assert message == "I agree with other agents. Added a refined issue on line 12."
    assert refined.agent == "style"
    assert len(refined.issues) == 2
    assert refined.issues[0].confidence_source == "llm_reasoning"
    assert refined.issues[1].confidence_source == "refined"
    assert refined.issues[0].file_path == "foo.py"


def test_coordinator_stopping_conditions():
    ctx = ReviewContext(
        pr_id="test#3",
        diff_text="some diff",
        agent_outputs={
            "style": AgentOutput(agent="style", confidence=0.5, issues=[]),
            "logic": AgentOutput(agent="logic", confidence=0.6, issues=[]),
        },
        round=1,
    )

    # Round limit stopping
    assert CoordinatorAgent.should_stop(ctx, max_rounds=1) is True

    # Under limit, no stop
    assert CoordinatorAgent.should_stop(ctx, max_rounds=3) is False

    # Stop on empty messages
    ctx.dialogue = [
        DialogueTurn(speaker="style", message=""),
        DialogueTurn(speaker="logic", message="   "),
    ]
    assert CoordinatorAgent.should_stop(ctx, max_rounds=3) is True

    # No stop if at least one agent is speaking
    ctx.dialogue = [
        DialogueTurn(speaker="style", message="Hello"),
        DialogueTurn(speaker="logic", message=""),
    ]
    assert CoordinatorAgent.should_stop(ctx, max_rounds=3) is False


def test_review_pr_orchestrator(monkeypatch):
    # Set Celery to always eager for testing synchronous execution
    monkeypatch.setattr(celery_app.conf, "task_always_eager", True)

    # Mock generate_analysis in all agent modules to return correct JSON structure
    mocked_response = {
        "message": "Let's align",
        "issues": []
    }
    monkeypatch.setattr("prguard_ai.agents.style_agent.generate_analysis", lambda *args, **kwargs: (json.dumps(mocked_response), {}))
    monkeypatch.setattr("prguard_ai.agents.logic_agent.generate_analysis", lambda *args, **kwargs: (json.dumps(mocked_response), {}))
    monkeypatch.setattr("prguard_ai.agents.security_agent.generate_analysis", lambda *args, **kwargs: (json.dumps(mocked_response), {}))

    pr_id = "test#2"
    diff_text = "diff --git a/foo.py b/foo.py\n+new line"
    repo_metadata = {"repository": "owner/repo", "pr_number": 2, "pr_id": pr_id}

    report_dict = review_pr({"diff_text": diff_text, "sandbox_path": None}, pr_id, repo_metadata)
    assert "overall_confidence" in report_dict
    assert "issues" in report_dict

    # Verify context stored in Redis
    ctx = get_review_context(pr_id)
    assert ctx is not None
    # The loop should stop at round 2 because of the consecutive no-change stopping condition
    # (round 1 had no changes compared to initial, and round 2 had no changes compared to round 1).
    assert ctx.round == 2
    assert "style" in ctx.agent_outputs
    assert "logic" in ctx.agent_outputs
    assert "security" in ctx.agent_outputs
    assert len(ctx.dialogue) > 0
    assert ctx.coordinator_guidance
