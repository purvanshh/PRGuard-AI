"""Integration tests for Semgrep findings flowing into the arbitrator (Phase 4)."""

import json
from pathlib import Path

import pytest

from prguard_ai.agents.arbitrator_agent import arbitrate_confidence, deduplicate_issues
from prguard_ai.confidence.scoring_engine import (
    SOURCE_WEIGHTS,
    aggregate_confidence_tier,
    compute_confidence_tier,
    estimate_issue_confidence,
)
from prguard_ai.schemas.agent_output import AgentOutput, Issue
from prguard_ai.schemas.context import ReviewContext
from prguard_ai.semgrep import run_semgrep_scan, semgrep_enabled_for


def _semgrep_output(issues=None):
    return AgentOutput(agent="semgrep", confidence=0.9, issues=issues or [])


def _issue(line, severity="high", message="x", source="llm_reasoning", file_path="app.py"):
    return Issue(
        line=line,
        severity=severity,
        message=message,
        evidence="evidence",
        confidence_source=source,
        file_path=file_path,
        verified=source in ("rule_based", "semgrep"),
    )


def test_flag_defaults_to_disabled(monkeypatch):
    monkeypatch.delenv("PRGUARD_FLAG_SEMGREP_INTEGRATION", raising=False)
    monkeypatch.delenv("PRGUARD_FLAG_SEMGREP_INTEGRATION_ROLLOUT_PERCENT", raising=False)
    assert semgrep_enabled_for("owner/repo") is False


def test_flag_enabled_with_rollout(monkeypatch):
    monkeypatch.setenv("PRGUARD_FLAG_SEMGREP_INTEGRATION", "true")
    monkeypatch.delenv("PRGUARD_FLAG_SEMGREP_INTEGRATION_ROLLOUT_PERCENT", raising=False)
    assert semgrep_enabled_for("owner/repo") is True


def test_flag_enabled_with_zero_rollout(monkeypatch):
    monkeypatch.setenv("PRGUARD_FLAG_SEMGREP_INTEGRATION", "true")
    monkeypatch.setenv("PRGUARD_FLAG_SEMGREP_INTEGRATION_ROLLOUT_PERCENT", "0")
    assert semgrep_enabled_for("owner/repo") is False


def test_run_semgrep_scan_disabled_returns_graceful_output(monkeypatch):
    monkeypatch.delenv("PRGUARD_FLAG_SEMGREP_INTEGRATION", raising=False)
    output = run_semgrep_scan("diff", {"repository": "owner/repo", "sandbox_path": "/tmp/x"})
    assert output.agent == "semgrep"
    assert output.issues == []
    assert output.llm_skipped is True


def test_run_semgrep_scan_no_sandbox(monkeypatch):
    monkeypatch.setenv("PRGUARD_FLAG_SEMGREP_INTEGRATION", "true")
    output = run_semgrep_scan("diff", {"repository": "owner/repo"})
    assert output.agent == "semgrep"
    assert output.issues == []
    assert output.llm_skipped is True
    assert any("sandbox" in t for t in output.reasoning_trace)


def test_run_semgrep_scan_emits_issues(monkeypatch, tmp_path):
    from prguard_ai.semgrep import agent as semgrep_agent
    from prguard_ai.semgrep.parser import SemgrepFinding

    sandbox = tmp_path / "sandbox"
    sandbox.mkdir()
    (sandbox / "app.py").write_text("x = eval('1')\n")

    monkeypatch.setenv("PRGUARD_FLAG_SEMGREP_INTEGRATION", "true")
    fake_findings = [SemgrepFinding("rules.python.no-unsafe-eval", "high", "Detected eval", "app.py", 1, "x = eval('1')")]

    class _FakeScanner:
        configs = ["p/owasp-top-ten"]

        def scan(self, target, baseline_ref=None):
            return fake_findings

    monkeypatch.setattr(semgrep_agent, "_load_scanner", lambda: _FakeScanner())
    output = run_semgrep_scan("diff --git a/app.py b/app.py\n+ x = eval('1')\n", {"repository": "owner/repo", "sandbox_path": str(sandbox)})
    assert len(output.issues) == 1
    issue = output.issues[0]
    assert issue.confidence_source == "semgrep"
    assert issue.verified is True
    assert issue.file_path == "app.py"
    assert issue.line == 1


def test_semgrep_issues_filtered_to_changed_files(monkeypatch, tmp_path):
    from prguard_ai.semgrep import agent as semgrep_agent
    from prguard_ai.semgrep.parser import SemgrepFinding

    sandbox = tmp_path / "sandbox"
    sandbox.mkdir()
    monkeypatch.setenv("PRGUARD_FLAG_SEMGREP_INTEGRATION", "true")
    findings = [
        SemgrepFinding("r1", "high", "m", "changed.py", 1, "e"),
        SemgrepFinding("r2", "high", "m", "unchanged.py", 2, "e"),
    ]

    class _FakeScanner:
        configs = ["p/owasp-top-ten"]

        def scan(self, target, baseline_ref=None):
            return findings

    monkeypatch.setattr(semgrep_agent, "_load_scanner", lambda: _FakeScanner())
    diff = "diff --git a/changed.py b/changed.py\n--- a/changed.py\n+++ b/changed.py\n@@ -0,0 +1 @@\n+new\n"
    output = run_semgrep_scan(diff, {"repository": "owner/repo", "sandbox_path": str(sandbox)})
    assert len(output.issues) == 1
    assert output.issues[0].file_path == "changed.py"


def test_arbitrator_consolidates_same_location_findings():
    semgrep_issue = _issue(10, "high", "[semgrep/rules.python.no-sql-string-concat] SQL concat", source="semgrep")
    llm_issue = _issue(10, "medium", "User input can reach SQL query", source="llm_reasoning")
    deduped = deduplicate_issues([llm_issue, semgrep_issue], threshold=0.99, hard_loc_match=True)
    assert len(deduped) == 1
    assert "semgrep" in deduped[0].confidence_source


def test_arbitrator_keeps_distinct_locations_separate():
    a = _issue(10, "high", "A", source="semgrep")
    b = _issue(20, "high", "B", source="llm_reasoning")
    deduped = deduplicate_issues([a, b], threshold=0.99, hard_loc_match=True)
    assert len(deduped) == 2


def test_arbitrate_confidence_includes_semgrep_output():
    context = ReviewContext(
        pr_id="owner/repo#1",
        diff_text="diff",
        agent_outputs={
            "security": AgentOutput(agent="security", confidence=0.8, issues=[_issue(7, "high", "Unsafe eval")]),
            "semgrep": _semgrep_output([_issue(9, "high", "[semgrep/r] eval", source="semgrep")]),
        },
    )
    report = arbitrate_confidence(context)
    assert any(i.confidence_source == "semgrep" for i in report.issues)
    assert "semgrep" in report.tier_breakdown


def test_semgrep_source_weight_is_highest():
    assert SOURCE_WEIGHTS["semgrep"] >= 0.9
    assert SOURCE_WEIGHTS["semgrep"] > SOURCE_WEIGHTS["rule_based"]


def test_semgrep_issues_drive_high_tier():
    output = _semgrep_output([_issue(1, "high", "m", source="semgrep")])
    assert compute_confidence_tier(output) == "high"


def test_semgrep_only_review_is_high_confidence():
    output = _semgrep_output([_issue(1, "high", "m", source="semgrep")])
    assert aggregate_confidence_tier([output]) == "high"


def test_estimate_confidence_uses_semgrep_weight():
    confidence = estimate_issue_confidence([_issue(1, "high", "m", source="semgrep")], empty_confidence=0.5)
    assert confidence > 0.8


@pytest.mark.skipif(
    not __import__("shutil").which("semgrep")
    and not (Path(__file__).resolve().parent.parent / ".venv" / "bin" / "semgrep").exists(),
    reason="semgrep binary not installed",
)
def test_real_semgrep_binary_end_to_end(monkeypatch, tmp_path):
    import sys

    from prguard_ai.semgrep.scanner import SemgrepScanner

    venv_bin = Path(sys.executable).parent / "semgrep"
    binary = "semgrep" if __import__("shutil").which("semgrep") else str(venv_bin)
    rules_dir = Path(__file__).resolve().parent.parent / "rules"

    sandbox = tmp_path / "sandbox"
    sandbox.mkdir()
    (sandbox / "vuln.py").write_text("import pickle\nx = pickle.loads(blob)\n")
    (sandbox / "safe.py").write_text("import json\nx = json.loads(blob)\n")

    scanner = SemgrepScanner(binary=binary, configs=[str(rules_dir)], timeout_seconds=60)
    findings = scanner.scan(sandbox, baseline_ref=None)
    assert any(f.rule_id == "rules.python.no-unsafe-pickle" for f in findings)
    matched = [f for f in findings if f.rule_id == "rules.python.no-unsafe-pickle"]
    assert matched[0].severity == "medium"


def test_review_pr_chord_includes_semgrep_when_enabled(monkeypatch):
    import json as _json

    from prguard_ai.task_queue.celery_app import celery_app
    from prguard_ai.task_queue.orchestrator import review_pr
    from prguard_ai.db.redis_client import get_review_context

    monkeypatch.setattr(celery_app.conf, "task_always_eager", True)
    monkeypatch.setenv("PRGUARD_FLAG_SEMGREP_INTEGRATION", "true")
    mocked = {"message": "", "issues": []}
    monkeypatch.setattr("prguard_ai.agents.style_agent.generate_analysis", lambda *a, **k: (_json.dumps(mocked), {}))
    monkeypatch.setattr("prguard_ai.agents.logic_agent.generate_analysis", lambda *a, **k: (_json.dumps(mocked), {}))
    monkeypatch.setattr("prguard_ai.agents.security_agent.generate_analysis", lambda *a, **k: (_json.dumps(mocked), {}))

    pr_id = "semgrep-test#3"
    result = review_pr(
        {"diff_text": "diff --git a/foo.py b/foo.py\n+new line", "sandbox_path": None},
        pr_id,
        {"repository": "owner/repo", "pr_number": 3, "pr_id": pr_id},
    )
    assert result["status"] == "enqueued"
    ctx = get_review_context(pr_id)
    assert ctx is not None
    assert "semgrep" in ctx.agent_outputs
