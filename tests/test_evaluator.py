"""Tests for the PRGuard AI evaluation framework (Phase 14)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Unit tests for _f1_score
# ---------------------------------------------------------------------------

def test_f1_score_both_zero():
    """F1 is 0.0 when both precision and recall are 0."""
    from prguard_ai.evaluation.evaluator import _f1_score

    assert _f1_score(0.0, 0.0) == pytest.approx(0.0)


def test_f1_score_perfect():
    """F1 is 1.0 for perfect precision and recall."""
    from prguard_ai.evaluation.evaluator import _f1_score

    assert _f1_score(1.0, 1.0) == pytest.approx(1.0)


def test_f1_score_formula():
    """F1 follows harmonic mean formula for non-trivial inputs."""
    from prguard_ai.evaluation.evaluator import _f1_score

    precision, recall = 0.8, 0.4
    expected = 2 * 0.8 * 0.4 / (0.8 + 0.4)
    assert _f1_score(precision, recall) == pytest.approx(expected)


def test_f1_score_one_zero():
    """F1 is 0.0 when either precision or recall is 0."""
    from prguard_ai.evaluation.evaluator import _f1_score

    assert _f1_score(1.0, 0.0) == pytest.approx(0.0)
    assert _f1_score(0.0, 1.0) == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# Unit tests for evaluate_pr with mocked agents
# ---------------------------------------------------------------------------

SIMPLE_DIFF = """\
diff --git a/foo.py b/foo.py
--- a/foo.py
+++ b/foo.py
@@ -1 +1,2 @@
 x = 1
+eval(user_input)  # dangerous
"""


def _make_agent_output(agent: str, issues=None):
    from prguard_ai.schemas.agent_output import AgentOutput, Issue

    return AgentOutput(
        agent=agent,
        confidence=0.8,
        issues=issues or [],
    )


def test_evaluate_pr_no_expected_issues(monkeypatch):
    """evaluate_pr without expected_issues returns zero TP/FN."""
    from prguard_ai.evaluation import evaluator

    monkeypatch.setattr(evaluator, "analyze_style", lambda *a, **k: _make_agent_output("style"))
    monkeypatch.setattr(evaluator, "analyze_logic", lambda *a, **k: _make_agent_output("logic"))
    monkeypatch.setattr(evaluator, "analyze_security", lambda *a, **k: _make_agent_output("security"))

    result = evaluator.evaluate_pr(SIMPLE_DIFF)

    assert result["true_positive"] == 0
    assert result["missed_issue"] == 0
    assert "f1" in result
    assert "confidence" in result
    assert "agent_metrics" in result


def test_evaluate_pr_perfect_match(monkeypatch):
    """evaluate_pr returns TP=1, FP=0, FN=0, precision=1, recall=1, f1=1 on perfect match."""
    from prguard_ai.schemas.agent_output import Issue
    from prguard_ai.evaluation import evaluator

    detected_issue = Issue(
        line=2,
        severity="high",
        message="eval() call detected",
        evidence="eval(user_input)",
        confidence_source="rule_based",
    )

    monkeypatch.setattr(evaluator, "analyze_style", lambda *a, **k: _make_agent_output("style"))
    monkeypatch.setattr(evaluator, "analyze_logic", lambda *a, **k: _make_agent_output("logic"))
    monkeypatch.setattr(
        evaluator, "analyze_security",
        lambda *a, **k: _make_agent_output("security", [detected_issue])
    )

    expected = [{"line": 2, "message": "eval() call detected"}]
    result = evaluator.evaluate_pr(SIMPLE_DIFF, expected)

    assert result["true_positive"] == 1
    assert result["false_positive"] == 0
    assert result["missed_issue"] == 0
    assert result["precision"] == pytest.approx(1.0)
    assert result["recall"] == pytest.approx(1.0)
    assert result["f1"] == pytest.approx(1.0)
    assert result["agent_metrics"]["security"]["true_positive"] == 1


def test_evaluate_pr_all_fp(monkeypatch):
    """evaluate_pr returns precision=0 when detected issues don't match expected."""
    from prguard_ai.schemas.agent_output import Issue
    from prguard_ai.evaluation import evaluator

    wrong_issue = Issue(
        line=99,
        severity="low",
        message="unrelated finding",
        evidence="something",
        confidence_source="rule_based",
    )

    monkeypatch.setattr(evaluator, "analyze_style", lambda *a, **k: _make_agent_output("style"))
    monkeypatch.setattr(evaluator, "analyze_logic", lambda *a, **k: _make_agent_output("logic"))
    monkeypatch.setattr(
        evaluator, "analyze_security",
        lambda *a, **k: _make_agent_output("security", [wrong_issue])
    )

    expected = [{"line": 2, "message": "eval() call detected"}]
    result = evaluator.evaluate_pr(SIMPLE_DIFF, expected)

    assert result["false_positive"] >= 1
    assert result["missed_issue"] == 1
    assert result["precision"] == pytest.approx(0.0)
    assert result["f1"] == pytest.approx(0.0)


def test_evaluate_pr_all_fn(monkeypatch):
    """evaluate_pr returns recall=0 when all expected issues are missed."""
    from prguard_ai.evaluation import evaluator

    monkeypatch.setattr(evaluator, "analyze_style", lambda *a, **k: _make_agent_output("style"))
    monkeypatch.setattr(evaluator, "analyze_logic", lambda *a, **k: _make_agent_output("logic"))
    monkeypatch.setattr(evaluator, "analyze_security", lambda *a, **k: _make_agent_output("security"))

    expected = [{"line": 2, "message": "eval() call detected"}]
    result = evaluator.evaluate_pr(SIMPLE_DIFF, expected)

    assert result["missed_issue"] == 1
    assert result["recall"] == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# Tests for evaluate_dataset_file and run_evaluation_suite
# ---------------------------------------------------------------------------

def test_evaluate_dataset_file(tmp_path, monkeypatch):
    """evaluate_dataset_file reads JSON, runs evaluate_pr, and augments with id/description."""
    from prguard_ai.evaluation import evaluator

    monkeypatch.setattr(evaluator, "analyze_style", lambda *a, **k: _make_agent_output("style"))
    monkeypatch.setattr(evaluator, "analyze_logic", lambda *a, **k: _make_agent_output("logic"))
    monkeypatch.setattr(evaluator, "analyze_security", lambda *a, **k: _make_agent_output("security"))

    dataset = {
        "id": "test-case-1",
        "description": "Test case for evaluator",
        "diff": SIMPLE_DIFF,
        "expected_issues": [{"line": 2, "message": "eval() call detected"}],
    }
    fixture = tmp_path / "test_case.json"
    fixture.write_text(json.dumps(dataset))

    result = evaluator.evaluate_dataset_file(fixture)

    assert result["id"] == "test-case-1"
    assert result["description"] == "Test case for evaluator"
    assert "precision" in result
    assert "recall" in result
    assert "f1" in result


def test_run_evaluation_suite_single_file(tmp_path, monkeypatch):
    """run_evaluation_suite on a single file returns a single-element list."""
    from prguard_ai.evaluation import evaluator

    monkeypatch.setattr(evaluator, "analyze_style", lambda *a, **k: _make_agent_output("style"))
    monkeypatch.setattr(evaluator, "analyze_logic", lambda *a, **k: _make_agent_output("logic"))
    monkeypatch.setattr(evaluator, "analyze_security", lambda *a, **k: _make_agent_output("security"))

    dataset = {"id": "s1", "description": "Single", "diff": SIMPLE_DIFF, "expected_issues": []}
    fixture = tmp_path / "single.json"
    fixture.write_text(json.dumps(dataset))

    results = evaluator.run_evaluation_suite(fixture)
    assert len(results) == 1
    assert results[0]["id"] == "s1"


def test_run_evaluation_suite_directory(tmp_path, monkeypatch):
    """run_evaluation_suite on a directory processes all JSON files."""
    from prguard_ai.evaluation import evaluator

    monkeypatch.setattr(evaluator, "analyze_style", lambda *a, **k: _make_agent_output("style"))
    monkeypatch.setattr(evaluator, "analyze_logic", lambda *a, **k: _make_agent_output("logic"))
    monkeypatch.setattr(evaluator, "analyze_security", lambda *a, **k: _make_agent_output("security"))

    for i in range(3):
        f = tmp_path / f"case_{i}.json"
        f.write_text(json.dumps({
            "id": f"c{i}", "description": f"Case {i}",
            "diff": SIMPLE_DIFF, "expected_issues": [],
        }))

    results = evaluator.run_evaluation_suite(tmp_path)
    assert len(results) == 3
    ids = {r["id"] for r in results}
    assert ids == {"c0", "c1", "c2"}


def test_semantic_issue_match_handles_near_duplicates():
    from prguard_ai.evaluation.evaluator import semantic_issue_match

    detected = {"line": 10, "message": "Potential SQL injection via string-concatenated query", "severity": "high"}
    expected = {"line": 11, "message": "String concatenated SQL query may allow injection", "severity": "high"}

    assert semantic_issue_match(detected, expected) is True


def test_summarize_evaluation_results(monkeypatch):
    from prguard_ai.evaluation import evaluator

    monkeypatch.setattr(evaluator, "analyze_style", lambda *a, **k: _make_agent_output("style"))
    monkeypatch.setattr(evaluator, "analyze_logic", lambda *a, **k: _make_agent_output("logic"))
    monkeypatch.setattr(evaluator, "analyze_security", lambda *a, **k: _make_agent_output("security"))

    results = evaluator.run_evaluation_suite(Path(__file__).parent.parent / "src" / "prguard_ai" / "evaluation" / "dataset")
    summary = evaluator.summarize_evaluation_results(results)

    assert summary["cases"] >= 1
    assert "overall" in summary
    assert "per_agent" in summary


def test_existing_dataset_file_is_valid_json():
    """The bundled example_1.json dataset file is valid JSON with required fields."""
    dataset_dir = Path(__file__).parent.parent / "src" / "prguard_ai" / "evaluation" / "dataset"
    fixture = dataset_dir / "example_1.json"
    assert fixture.exists(), "example_1.json must exist in the evaluation dataset directory"

    data = json.loads(fixture.read_text())
    assert "diff" in data
    assert "expected_issues" in data
    assert isinstance(data["expected_issues"], list)
