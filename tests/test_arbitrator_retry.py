from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch
from prguard_ai.agents.arbitrator_agent import arbitrate_confidence
from prguard_ai.schemas.agent_output import AgentOutput, Issue
from prguard_ai.schemas.context import ReviewContext
from prguard_ai.gh_client.github_client import format_pr_review
from prguard_ai.task_queue.celery_app import (
    run_arbitrator,
    run_style_agent,
    run_logic_agent,
    run_security_agent,
)


def test_celery_task_configurations():
    """Verify time limits and retry parameters are configured properly on Celery tasks."""
    # Check arbitrator task configurations
    assert run_arbitrator.time_limit == 300
    assert run_arbitrator.soft_time_limit == 240
    assert run_arbitrator.max_retries == 2
    assert Exception in run_arbitrator.autoretry_for

    # Check agent tasks time limits
    for task in (run_style_agent, run_logic_agent, run_security_agent):
        assert task.time_limit == 300
        assert task.soft_time_limit == 240


def test_arbitrate_confidence_partial_success():
    """Verify arbitrator aggregates only successful agent outputs when partial=True."""
    success_style = AgentOutput(
        agent="style",
        confidence=0.8,
        issues=[
            Issue(
                line=5,
                severity="low",
                message="Style issue",
                evidence="x = 1",
                confidence_source="llm_reasoning",
            )
        ]
    )
    failed_logic = AgentOutput(
        agent="logic",
        confidence=0.0,
        issues=[],
        error="Connection Timeout to LLM"
    )

    context = ReviewContext(
        pr_id="test#1",
        diff_text="diff content",
        agent_outputs={
            "style": success_style,
            "logic": failed_logic,
        }
    )

    # Calling with partial=True should not raise value error, but filter out failed ones
    report = arbitrate_confidence(context, partial=True)
    assert 0.0 < report.overall_confidence <= 1.0  # style only
    assert len(report.issues) == 1
    assert report.issues[0].message == "Style issue"

    # Calling with partial=False should raise ValueError
    with pytest.raises(ValueError, match="Agent logic failed: Connection Timeout to LLM"):
        arbitrate_confidence(context, partial=False)


def test_arbitrate_confidence_all_failed():
    """Verify arbitrator returns a degraded empty report if all agents fail."""
    failed_style = AgentOutput(
        agent="style",
        confidence=0.0,
        issues=[],
        error="API Key Error"
    )
    failed_logic = AgentOutput(
        agent="logic",
        confidence=0.0,
        issues=[],
        error="LLM service down"
    )

    context = ReviewContext(
        pr_id="test#2",
        diff_text="diff content",
        agent_outputs={
            "style": failed_style,
            "logic": failed_logic,
        }
    )

    report = arbitrate_confidence(context, partial=True)
    assert report.overall_confidence == 0.0
    assert len(report.issues) == 0
    assert report.agent_outputs == [failed_style, failed_logic]


def test_degraded_formatting():
    """Verify format_pr_review omits confidence score and disagreements summary in degraded mode."""
    report = {
        "degraded": True,
        "overall_confidence": 0.85,
        "agent_outputs": [
            {
                "agent": "style",
                "confidence": 0.8,
                "issues": [
                    {
                        "line": 10,
                        "severity": "low",
                        "message": "Too long line",
                        "evidence": "xyz",
                        "confidence_source": "rule_based"
                    }
                ],
                "llm_skipped": False
            }
        ],
        "issues": [
            {
                "line": 10,
                "severity": "low",
                "message": "Too long line",
                "evidence": "xyz",
                "confidence_source": "rule_based"
            }
        ],
        "disagreements": ["style and logic disagree"]
    }

    markdown_comment = format_pr_review(report)

    # In degraded mode, "Confidence Score" and "Disagreement Summary" must NOT be in markdown
    assert "Confidence Score" not in markdown_comment
    assert "Disagreement Summary" not in markdown_comment
    # But files and issue details should be there
    assert "Too long line" in markdown_comment

    # In normal mode (degraded=False), they should be present
    report["degraded"] = False
    normal_markdown = format_pr_review(report)
    assert "Confidence Score" in normal_markdown
    assert "Disagreement Summary" in normal_markdown


def test_run_arbitrator_handles_errors_gracefully():
    """Verify the run_arbitrator Celery task catches errors and falls back to degraded mode."""
    agent_outputs = [
        {
            "agent": "style",
            "confidence": 0.7,
            "issues": [
                {
                    "line": 4,
                    "severity": "low",
                    "message": "Indent",
                    "evidence": "  ",
                    "confidence_source": "rule_based"
                }
            ],
            "llm_skipped": False,
            "error": None
        }
    ]

    # Force a failure during arbitration
    with patch("prguard_ai.task_queue.celery_app.arbitrate_confidence", side_effect=ValueError("Arbitration crash")):
        res = run_arbitrator(agent_outputs)
        assert res["degraded"] is True
        assert res["overall_confidence"] == 0.0
        assert len(res["issues"]) == 1
        assert res["issues"][0].message == "Indent"
        assert res["error"] == "Arbitration crash"
