"""Tests for Celery task definitions in eager mode (Phase 15 coverage lift)."""

from __future__ import annotations

import pytest
from prguard_ai.schemas.agent_output import AgentOutput, Issue
from prguard_ai.schemas.context import ReviewContext


SIMPLE_DIFF = """\
diff --git a/foo.py b/foo.py
--- a/foo.py
+++ b/foo.py
@@ -1 +1,3 @@
 x = 1
+eval(user_input)
+SECRET_KEY = 'abc123'
"""


def _make_agent_output(agent: str, **kwargs):
    from prguard_ai.schemas.agent_output import AgentOutput

    return AgentOutput(agent=agent, confidence=0.7, issues=[], **kwargs)


# ---------------------------------------------------------------------------
# run_style_agent / run_logic_agent / run_security_agent (direct call)
# ---------------------------------------------------------------------------

class TestCeleryAgentTasks:
    """Call the underlying task functions directly (bypassing Celery broker)."""

    def test_run_style_agent_returns_dict(self, monkeypatch):
        from prguard_ai.task_queue import celery_app as ca

        monkeypatch.setattr(ca, "analyze_style", lambda *a, **k: _make_agent_output("style"))
        result = ca.run_style_agent(SIMPLE_DIFF, {"pr_id": "owner/repo#1"})
        assert isinstance(result, dict)
        assert result["agent"] == "style"

    def test_run_logic_agent_returns_dict(self, monkeypatch):
        from prguard_ai.task_queue import celery_app as ca

        monkeypatch.setattr(ca, "analyze_logic", lambda *a, **k: _make_agent_output("logic"))
        result = ca.run_logic_agent(SIMPLE_DIFF, {"pr_id": "owner/repo#1"})
        assert result["agent"] == "logic"

    def test_run_security_agent_returns_dict(self, monkeypatch):
        from prguard_ai.task_queue import celery_app as ca

        monkeypatch.setattr(ca, "analyze_security", lambda *a, **k: _make_agent_output("security"))
        result = ca.run_security_agent(SIMPLE_DIFF, {"pr_id": "owner/repo#1"})
        assert result["agent"] == "security"

    def test_run_style_agent_handles_exception(self, monkeypatch):
        """On agent error, task returns an error dict instead of raising."""
        from prguard_ai.task_queue import celery_app as ca

        def boom(*a, **k):
            raise RuntimeError("LLM exploded")

        monkeypatch.setattr(ca, "analyze_style", boom)
        result = ca.run_style_agent(SIMPLE_DIFF)
        assert result["llm_skipped"] is True
        assert "LLM exploded" in result["error"]

    def test_run_logic_agent_handles_exception(self, monkeypatch):
        from prguard_ai.task_queue import celery_app as ca

        monkeypatch.setattr(ca, "analyze_logic", lambda *a, **k: (_ for _ in ()).throw(ValueError("bad")))

        result = ca.run_logic_agent(SIMPLE_DIFF)
        assert result["llm_skipped"] is True
        assert result["agent"] == "logic"

    def test_run_security_agent_handles_exception(self, monkeypatch):
        from prguard_ai.task_queue import celery_app as ca

        def boom(*a, **k):
            raise OSError("disk full")

        monkeypatch.setattr(ca, "analyze_security", boom)
        result = ca.run_security_agent(SIMPLE_DIFF)
        assert result["llm_skipped"] is True
        assert result["agent"] == "security"

    def test_run_style_agent_no_metadata(self, monkeypatch):
        """Task works without repo_metadata."""
        from prguard_ai.task_queue import celery_app as ca

        monkeypatch.setattr(ca, "analyze_style", lambda *a, **k: _make_agent_output("style"))
        result = ca.run_style_agent(SIMPLE_DIFF)
        assert result["agent"] == "style"


# ---------------------------------------------------------------------------
# run_arbitrator
# ---------------------------------------------------------------------------

class TestRunArbitrator:
    def test_run_arbitrator_with_valid_outputs(self, monkeypatch):
        from prguard_ai.task_queue import celery_app as ca

        outputs = [
            _make_agent_output("style").model_dump(),
            _make_agent_output("logic").model_dump(),
            _make_agent_output("security").model_dump(),
        ]
        result = ca.run_arbitrator(outputs)
        assert "overall_confidence" in result
        assert isinstance(result["disagreements"], list)

    def test_run_arbitrator_with_failed_agent(self, monkeypatch):
        """Arbitrator handles outputs where one agent failed (has error)."""
        from prguard_ai.task_queue import celery_app as ca

        failed = _make_agent_output("logic", error="timed out", llm_skipped=True)
        outputs = [
            _make_agent_output("style").model_dump(),
            failed.model_dump(),
            _make_agent_output("security").model_dump(),
        ]
        result = ca.run_arbitrator(outputs)
        assert "overall_confidence" in result

    def test_run_arbitrator_malformed_input_returns_degraded(self):
        from prguard_ai.task_queue import celery_app as ca

        # Completely invalid agent output dicts
        result = ca.run_arbitrator([{"bad": "data"}, {"also": "bad"}])
        assert "overall_confidence" in result

    def test_run_arbitrator_empty_list(self):
        from prguard_ai.task_queue import celery_app as ca

        result = ca.run_arbitrator([])
        assert result["overall_confidence"] == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# tasks.py — post_review and on_task_failure (mocked GitHub calls)
# ---------------------------------------------------------------------------

class TestPostReviewTask:
    def test_post_review_calls_format_and_post(self, monkeypatch):
        import prguard_ai.task_queue.tasks as tsk

        posted_bodies = []

        monkeypatch.setattr(tsk, "format_pr_review", lambda r: "formatted review")
        monkeypatch.setattr(tsk, "post_pr_comment", lambda **kw: posted_bodies.append(kw["body"]))
        monkeypatch.setattr(tsk, "post_inline_comment", lambda **kw: None)
        monkeypatch.setattr(tsk, "complete_pr_processing", lambda pr_id: None)
        monkeypatch.setattr(tsk, "TOTAL_PRS_PROCESSED", type("C", (), {"inc": lambda self: None})())
        monkeypatch.setattr(tsk, "REVIEW_CONFIDENCE", type("S", (), {"observe": lambda self, v: None})())

        report = {
            "overall_confidence": 0.8,
            "issues": [],
        }
        result = tsk.post_review(report, "owner/repo", 5)
        assert result == report
        assert "formatted review" in posted_bodies

    def test_post_review_posts_inline_for_high_severity(self, monkeypatch):
        import prguard_ai.task_queue.tasks as tsk

        inline_calls = []

        monkeypatch.setattr(tsk, "format_pr_review", lambda r: "body")
        monkeypatch.setattr(tsk, "post_pr_comment", lambda **kw: None)
        monkeypatch.setattr(tsk, "post_inline_comment", lambda **kw: inline_calls.append(kw))
        monkeypatch.setattr(tsk, "complete_pr_processing", lambda pr_id: None)
        monkeypatch.setattr(tsk, "TOTAL_PRS_PROCESSED", type("C", (), {"inc": lambda self: None})())
        monkeypatch.setattr(tsk, "REVIEW_CONFIDENCE", type("S", (), {"observe": lambda self, v: None})())

        report = {
            "overall_confidence": 0.9,
            "issues": [
                {"severity": "HIGH", "message": "injection", "evidence": "x", "file_path": "api.py", "line": 10},
                {"severity": "medium", "message": "warning", "evidence": "y", "file_path": "app.py", "line": 20},
                {"severity": "low", "message": "info", "evidence": "z", "file_path": None, "line": 30},
            ],
        }
        tsk.post_review(report, "owner/repo", 1)
        # Only HIGH and medium with file_path should be inline-commented
        assert len(inline_calls) == 2

    def test_post_review_cleans_up_sandbox(self, monkeypatch):
        import prguard_ai.task_queue.tasks as tsk

        cleaned = []
        monkeypatch.setattr(tsk, "format_pr_review", lambda r: "body")
        monkeypatch.setattr(tsk, "post_pr_comment", lambda **kw: None)
        monkeypatch.setattr(tsk, "post_inline_comment", lambda **kw: None)
        monkeypatch.setattr(tsk, "complete_pr_processing", lambda pr_id: None)
        monkeypatch.setattr(tsk, "TOTAL_PRS_PROCESSED", type("C", (), {"inc": lambda self: None})())
        monkeypatch.setattr(tsk, "REVIEW_CONFIDENCE", type("S", (), {"observe": lambda self, v: None})())
        monkeypatch.setattr("prguard_ai.analysis.repo_sandbox.cleanup_repository", lambda path: cleaned.append(path))

        report = {"overall_confidence": 0.5, "issues": [], "sandbox_path": "/tmp/prguard/test"}
        tsk.post_review(report, "owner/repo", 9)

        assert cleaned == ["/tmp/prguard/test"]


class TestOnTaskFailure:
    def test_on_task_failure_cleans_up_pr(self, monkeypatch):
        import prguard_ai.task_queue.tasks as tsk

        cleaned = []
        monkeypatch.setattr(tsk, "complete_pr_processing", lambda pr_id: cleaned.append(pr_id))

        tsk.on_task_failure(pr_id="owner/repo#7")
        assert "owner/repo#7" in cleaned

    def test_on_task_failure_without_pr_id_does_not_crash(self, monkeypatch):
        import prguard_ai.task_queue.tasks as tsk

        monkeypatch.setattr(tsk, "complete_pr_processing", lambda pr_id: None)
        monkeypatch.setattr(tsk, "_enqueue_dead_letter", lambda payload: None)
        # Should not raise
        tsk.on_task_failure()

    def test_on_task_failure_enqueues_dead_letter(self, monkeypatch):
        import prguard_ai.task_queue.tasks as tsk

        enqueued = []
        monkeypatch.setattr(tsk, "complete_pr_processing", lambda pr_id: None)
        monkeypatch.setattr(tsk, "_enqueue_dead_letter", lambda payload: enqueued.append(payload))

        tsk.on_task_failure("boom", pr_id="owner/repo#7", task_name="review_pr")
        assert enqueued[0]["pr_id"] == "owner/repo#7"


class TestPrepareRepository:
    def test_prepare_repository_returns_sandbox_path(self, monkeypatch):
        import prguard_ai.task_queue.tasks as tsk

        class Sandbox:
            temp_path = "/tmp/prguard/owner__repo#1/test"

        monkeypatch.setattr("prguard_ai.gh_client.github_client.get_pr_diff", lambda **kw: SIMPLE_DIFF)
        monkeypatch.setattr("prguard_ai.analysis.repo_sandbox.clone_repository", lambda **kw: Sandbox())
        monkeypatch.setattr("prguard_ai.analysis.repo_indexer.initialize_repo_index", lambda **kw: None)
        monkeypatch.setattr("prguard_ai.analysis.code_graph.build_code_graph", lambda *a, **k: None)

        result = tsk.prepare_repository("owner/repo#1", "owner/repo", 1, {"repository": {"clone_url": "https://github.com/owner/repo.git"}})
        assert result["diff_text"] == SIMPLE_DIFF
        assert result["sandbox_path"] == "/tmp/prguard/owner__repo#1/test"


class TestReviewContextConcurrency:
    def test_concurrent_refinement_no_lost_updates(self):
        from prguard_ai.db.redis_client import get_review_context, store_review_agent_output, store_review_context

        context = ReviewContext(
            pr_id="owner/repo#77",
            diff_text=SIMPLE_DIFF,
            agent_outputs={
                "style": AgentOutput(agent="style", confidence=0.5, issues=[]),
                "logic": AgentOutput(agent="logic", confidence=0.5, issues=[]),
                "security": AgentOutput(agent="security", confidence=0.5, issues=[]),
            },
        )
        store_review_context(context.pr_id, context)

        style_issue = Issue(
            line=1,
            severity="low",
            message="style",
            evidence="x",
            confidence_source="rule_based",
            file_path="foo.py",
        )
        logic_issue = Issue(
            line=2,
            severity="medium",
            message="logic",
            evidence="y",
            confidence_source="rule_based",
            file_path="foo.py",
        )

        store_review_agent_output(context.pr_id, "style", AgentOutput(agent="style", confidence=0.6, issues=[style_issue]))
        store_review_agent_output(context.pr_id, "logic", AgentOutput(agent="logic", confidence=0.7, issues=[logic_issue]))

        refreshed = get_review_context(context.pr_id)
        assert refreshed is not None
        assert refreshed.agent_outputs["style"].issues[0].message == "style"
        assert refreshed.agent_outputs["logic"].issues[0].message == "logic"
        assert refreshed.agent_outputs["security"].issues == []


class TestCeleryReliabilityConfig:
    def test_worker_reliability_flags_enabled(self):
        from prguard_ai.task_queue.celery_app import celery_app

        assert celery_app.conf.task_acks_late is True
        assert celery_app.conf.task_reject_on_worker_lost is True
