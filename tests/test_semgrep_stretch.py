"""Tests for the Semgrep stretch features: autofix, dynamic weights, and
agent tool synergy."""

import json
import subprocess

import pytest

from prguard_ai.semgrep import autofix
from prguard_ai.semgrep import weights
from prguard_ai.semgrep.weights import (
    DEFAULT_SEMGREP_WEIGHT,
    DynamicSemgrepWeight,
    MemoryFeedbackProvider,
    NoopFeedbackProvider,
    compute_effective_weight,
)


# --------------------------------------------------------------------------
# D1: Autofix
# --------------------------------------------------------------------------

def test_autofix_disabled_by_default(monkeypatch, tmp_path):
    monkeypatch.delenv("PRGUARD_FLAG_SEMGREP_AUTOFIX", raising=False)
    result = autofix.apply_semgrep_autofix(tmp_path, "diff --git a/x.txt b/x.txt\n")
    assert result["applied"] is False


def test_autofix_rejects_non_git_repo(monkeypatch, tmp_path):
    monkeypatch.setenv("PRGUARD_FLAG_SEMGREP_AUTOFIX", "true")
    result = autofix.apply_semgrep_autofix(tmp_path, "diff --git a/x.txt b/x.txt\n")
    assert result["applied"] is False
    assert "not a git repository" in result["detail"]


def test_autofix_applies_patch_and_commits(monkeypatch, tmp_path):
    import os

    monkeypatch.setenv("PRGUARD_FLAG_SEMGREP_AUTOFIX", "true")
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "app.py").write_text("x = 1\n")
    _git = lambda *a: subprocess.run(  # noqa: E731
        ["git", "-C", str(repo), *a], capture_output=True, text=True, check=False
    )
    _git("init")
    _git("config", "user.email", "test@example.com")
    _git("config", "user.name", "Test")
    _git("add", ".")
    _git("commit", "-m", "initial")

    patch = "diff --git a/app.py b/app.py\n--- a/app.py\n+++ b/app.py\n@@ -1 +1 @@\n-x = 1\n+x = 2\n"
    result = autofix.apply_semgrep_autofix(repo, patch)
    assert result["applied"] is True
    assert (repo / "app.py").read_text() == "x = 2\n"
    assert os.path.exists(repo / ".git")


def test_autofix_rejects_bad_patch(monkeypatch, tmp_path):
    monkeypatch.setenv("PRGUARD_FLAG_SEMGREP_AUTOFIX", "true")
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "app.py").write_text("x = 1\n")
    subprocess.run(["git", "-C", str(repo), "init"], capture_output=True, check=False)
    result = autofix.apply_semgrep_autofix(repo, "not a real diff")
    assert result["applied"] is False
    assert "patch rejected" in result["detail"]


# --------------------------------------------------------------------------
# D2: Dynamic weights
# --------------------------------------------------------------------------

def test_weight_kept_below_sample_threshold():
    assert compute_effective_weight("r1", total_findings=5, ignored_findings=3) == DEFAULT_SEMGREP_WEIGHT


def test_weight_reduced_when_fp_rate_high():
    assert compute_effective_weight("r1", total_findings=20, ignored_findings=8) == 0.6


def test_weight_kept_when_fp_rate_low():
    assert compute_effective_weight("r1", total_findings=20, ignored_findings=2) == DEFAULT_SEMGREP_WEIGHT


def test_weight_clamps_ignored_to_total():
    assert compute_effective_weight("r1", total_findings=10, ignored_findings=999) == 0.6


def test_zero_total_keeps_base_weight():
    assert compute_effective_weight("r1", total_findings=0, ignored_findings=0) == DEFAULT_SEMGREP_WEIGHT


def test_noop_provider_keeps_full_weight():
    resolver = DynamicSemgrepWeight(provider=NoopFeedbackProvider())
    assert resolver.weight_for("r1") == DEFAULT_SEMGREP_WEIGHT


def test_memory_provider_reduces_noisy_rule():
    resolver = DynamicSemgrepWeight(
        provider=MemoryFeedbackProvider({"rules.python.no-shell-true": (20, 8)})
    )
    assert resolver.weight_for("rules.python.no-shell-true") == 0.6
    assert resolver.weight_for("rules.python.no-request-timeout") == DEFAULT_SEMGREP_WEIGHT


def test_db_provider_noops_in_testing(monkeypatch):
    from prguard_ai.semgrep.weights import DatabaseFeedbackProvider

    assert DatabaseFeedbackProvider().ignored_counts("r1") is None


def test_findings_to_issues_carries_rule_id():
    from prguard_ai.semgrep.parser import SemgrepFinding, findings_to_issues

    finding = SemgrepFinding("rules.python.no-shell-true", "medium", "m", "app.py", 1, "e")
    issue = findings_to_issues([finding])[0]
    assert issue.rule_id == "rules.python.no-shell-true"


def test_scoring_uses_source_weight_override():
    from prguard_ai.confidence.scoring_engine import estimate_issue_confidence
    from prguard_ai.schemas.agent_output import Issue

    issue = Issue(
        line=1, severity="high", message="m", evidence="e",
        confidence_source="semgrep", verified=True, source_weight_override=0.6,
    )
    confidence = estimate_issue_confidence([issue], empty_confidence=0.5)
    assert 0.75 < confidence < 0.9


def test_apply_dynamic_weights_demotes_noisy_rule(monkeypatch):
    from prguard_ai.semgrep import agent as semgrep_agent
    from prguard_ai.semgrep.parser import SemgrepFinding, findings_to_issues
    from prguard_ai.semgrep.weights import MemoryFeedbackProvider

    class _Provider:
        def __init__(self):
            self.inner = MemoryFeedbackProvider({"rules.python.no-shell-true": (20, 10)})

        def ignored_counts(self, rule_id, days=30):
            return self.inner.ignored_counts(rule_id, days)

    monkeypatch.setattr("prguard_ai.semgrep.weights.get_db_feedback_provider", lambda: _Provider())
    findings = [
        SemgrepFinding("rules.python.no-shell-true", "medium", "m", "app.py", 1, "e"),
        SemgrepFinding("rules.python.no-request-timeout", "medium", "m", "app.py", 2, "e"),
    ]
    issues = findings_to_issues(findings)
    semgrep_agent._apply_dynamic_weights(issues)
    by_rule = {i.rule_id: i.source_weight_override for i in issues}
    assert by_rule["rules.python.no-shell-true"] == 0.6
    assert by_rule["rules.python.no-request-timeout"] is None


# --------------------------------------------------------------------------
# D3: semgrep_scan tool + agent synergy
# --------------------------------------------------------------------------

def test_executor_semgrep_tool_returns_empty_when_disabled(monkeypatch, tmp_path):
    from prguard_ai.agents.tools.executor import AgentToolExecutor
    from prguard_ai.agents.tools.schemas import ToolInvocation

    monkeypatch.delenv("PRGUARD_FLAG_SEMGREP_INTEGRATION", raising=False)
    monkeypatch.delenv("PRGUARD_FLAG_SEMGREP_INTEGRATION_ROLLOUT_PERCENT", raising=False)
    executor = AgentToolExecutor({"repository": "owner/repo", "sandbox_path": str(tmp_path)})
    result = executor.execute(ToolInvocation(tool="semgrep_scan", args={"tool_name": "semgrep_scan"}))
    assert result.ok
    assert result.output["findings"] == []


def test_executor_semgrep_tool_surfaces_findings(monkeypatch, tmp_path):
    from prguard_ai.agents.tools.executor import AgentToolExecutor
    from prguard_ai.agents.tools.schemas import ToolInvocation
    from prguard_ai.semgrep.parser import SemgrepFinding

    sandbox = tmp_path / "sandbox"
    sandbox.mkdir()

    class _FakeScanner:
        def scan(self, target, baseline_ref=None):
            return [SemgrepFinding("rules.python.no-unsafe-eval", "high", "eval!", "app.py", 1, "eval(x)")]

    monkeypatch.setenv("PRGUARD_FLAG_SEMGREP_INTEGRATION", "true")
    monkeypatch.setattr("prguard_ai.semgrep.agent._load_scanner", lambda: _FakeScanner())
    executor = AgentToolExecutor({"repository": "owner/repo", "sandbox_path": str(sandbox)})
    result = executor.execute(ToolInvocation(tool="semgrep_scan", args={"tool_name": "semgrep_scan", "limit": 5}))
    assert result.ok
    assert len(result.output["findings"]) == 1
    assert result.output["findings"][0]["rule_id"] == "rules.python.no-unsafe-eval"


def test_security_agent_prompt_includes_semgrep_findings(monkeypatch, tmp_path):
    from prguard_ai.agents.security_agent import SecurityAgent
    from prguard_ai.semgrep.parser import SemgrepFinding

    captured = {}

    def _fake_generate(prompt, **kwargs):
        captured["prompt"] = prompt
        return "[]", {}

    class _FakeScanner:
        def scan(self, target, baseline_ref=None):
            return [SemgrepFinding("rules.python.no-shell-true", "medium", "shell=True", "app.py", 2, "subprocess.run(cmd, shell=True)")]

    monkeypatch.setenv("PRGUARD_FLAG_SEMGREP_INTEGRATION", "true")
    monkeypatch.setattr("prguard_ai.semgrep.agent._load_scanner", lambda: _FakeScanner())
    monkeypatch.setattr("prguard_ai.agents.security_agent.generate_analysis", _fake_generate)

    sandbox = tmp_path / "sandbox"
    sandbox.mkdir()
    agent = SecurityAgent(repo_metadata={"repository": "owner/repo", "sandbox_path": str(sandbox), "pr_id": "owner/repo#1"})
    output = agent.run_react_loop("diff --git a/app.py b/app.py\n--- a/app.py\n+++ b/app.py\n@@ -1,1 +1,1 @@\n+ subprocess.run(cmd, shell=True)\n")
    assert output is not None
    assert "Semgrep" in captured["prompt"]
    assert "no-shell-true" in captured["prompt"]
    assert "AGREE" in captured["prompt"]
