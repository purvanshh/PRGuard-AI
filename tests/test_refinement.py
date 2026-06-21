from __future__ import annotations

import json
from unittest.mock import MagicMock
import pytest

from prguard_ai.schemas.agent_output import AgentOutput, Issue
from prguard_ai.schemas.context import ReviewContext
from prguard_ai.agents.style_agent import StyleAgent
from prguard_ai.agents.logic_agent import LogicAgent
from prguard_ai.agents.security_agent import SecurityAgent
from prguard_ai.task_queue.celery_app import celery_app
from prguard_ai.task_queue.orchestrator import review_pr
from prguard_ai.db.redis_client import get_review_context


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

    mocked_issues = [
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
    ]

    def _mock_gen(prompt, *args, **kwargs):
        return json.dumps(mocked_issues), {}

    monkeypatch.setattr("prguard_ai.agents.style_agent.generate_analysis", _mock_gen)

    refined = StyleAgent.refine(initial_output, context)
    assert refined.agent == "style"
    assert len(refined.issues) == 2
    assert refined.issues[0].confidence_source == "llm_reasoning"
    assert refined.issues[1].confidence_source == "refined"
    assert refined.issues[0].file_path == "foo.py"


def test_review_pr_orchestrator(monkeypatch):
    # Set Celery to always eager for testing synchronous execution
    monkeypatch.setattr(celery_app.conf, "task_always_eager", True)

    # Mock github client posting methods directly inside orchestrator module
    monkeypatch.setattr("prguard_ai.task_queue.orchestrator.post_pr_comment", MagicMock())
    monkeypatch.setattr("prguard_ai.task_queue.orchestrator.post_inline_comment", MagicMock())

    # Mock generate_analysis in all agent modules to prevent external LLM calls or offline stubs
    monkeypatch.setattr("prguard_ai.agents.style_agent.generate_analysis", lambda *args, **kwargs: ("[]", {}))
    monkeypatch.setattr("prguard_ai.agents.logic_agent.generate_analysis", lambda *args, **kwargs: ("[]", {}))
    monkeypatch.setattr("prguard_ai.agents.security_agent.generate_analysis", lambda *args, **kwargs: ("[]", {}))

    pr_id = "test#2"
    diff_text = "diff --git a/foo.py b/foo.py\n+new line"
    repo_metadata = {"repository": "owner/repo", "pr_number": 2, "pr_id": pr_id}

    report_dict = review_pr(pr_id, diff_text, repo_metadata)
    assert "overall_confidence" in report_dict
    assert "issues" in report_dict

    # Verify context stored in Redis
    ctx = get_review_context(pr_id)
    assert ctx is not None
    assert ctx.round == 1
    assert "style" in ctx.agent_outputs
    assert "logic" in ctx.agent_outputs
    assert "security" in ctx.agent_outputs
