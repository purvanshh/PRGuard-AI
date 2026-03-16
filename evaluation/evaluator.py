"""Evaluation framework for PRGuard AI agents."""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

from agents.logic_agent import analyze_logic
from agents.security_agent import analyze_security
from agents.style_agent import analyze_style
from agents.arbitrator_agent import arbitrate_confidence
from schemas.agent_output import AgentOutput


def _normalize_issue(issue: Dict[str, Any]) -> Tuple[int, str]:
    return int(issue.get("line", 0)), str(issue.get("message", "")).strip()


def evaluate_pr(
    diff_text: str,
    expected_issues: List[Dict[str, Any]] | None = None,
) -> Dict[str, Any]:
    """
    Run all agents on a diff and compare against expected issues (if provided).

    Returns basic precision/recall-style metrics.
    """
    repo_metadata = {"repository": "eval/repo", "pr_number": 0, "pr_id": "eval#0"}

    style_output: AgentOutput = analyze_style(diff_text, repo_metadata)
    logic_output: AgentOutput = analyze_logic(diff_text, repo_metadata)
    security_output: AgentOutput = analyze_security(diff_text, repo_metadata)

    report = arbitrate_confidence([style_output, logic_output, security_output])

    detected = {_normalize_issue(i.dict()) for i in report.issues}

    if not expected_issues:
        return {
            "true_positive": 0,
            "false_positive": len(detected),
            "missed_issue": 0,
            "precision": 0.0,
            "recall": 0.0,
        }

    expected_set = {
        _normalize_issue(e)
        for e in expected_issues
    }

    tp = len(detected & expected_set)
    fp = len(detected - expected_set)
    fn = len(expected_set - detected)

    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0

    return {
        "true_positive": tp,
        "false_positive": fp,
        "missed_issue": fn,
        "precision": precision,
        "recall": recall,
    }


__all__ = ["evaluate_pr"]

