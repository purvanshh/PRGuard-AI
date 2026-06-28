"""Evaluation framework for PRGuard AI agents.

Usage (CLI):
    python -m prguard_ai.evaluation.evaluator --dataset path/to/example.json
    python -m prguard_ai.evaluation.evaluator --dataset path/to/dataset/
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from prguard_ai.agents.logic_agent import analyze_logic
from prguard_ai.agents.security_agent import analyze_security
from prguard_ai.agents.style_agent import analyze_style
from prguard_ai.agents.arbitrator_agent import arbitrate_confidence
from prguard_ai.schemas.agent_output import AgentOutput


def _normalize_issue(issue: Dict[str, Any]) -> Tuple[int, str]:
    return int(issue.get("line", 0)), str(issue.get("message", "")).strip()


def _f1_score(precision: float, recall: float) -> float:
    """Compute F1 score from precision and recall."""
    if precision + recall == 0.0:
        return 0.0
    return 2.0 * precision * recall / (precision + recall)


def evaluate_pr(
    diff_text: str,
    expected_issues: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Run all agents on a diff and compare against expected issues (if provided).

    Returns basic precision/recall/F1-style metrics.

    Args:
        diff_text: The unified diff text to analyse.
        expected_issues: Optional list of dicts with ``line`` and ``message`` keys
            representing the ground-truth issues. If *None* or empty, only the
            detected issue count and confidence are returned.

    Returns:
        A dict containing ``true_positive``, ``false_positive``, ``missed_issue``,
        ``precision``, ``recall``, ``f1``, and ``confidence`` keys.
    """
    repo_metadata = {"repository": "eval/repo", "pr_number": 0, "pr_id": "eval#0"}

    style_output: AgentOutput = analyze_style(diff_text, repo_metadata)
    logic_output: AgentOutput = analyze_logic(diff_text, repo_metadata)
    security_output: AgentOutput = analyze_security(diff_text, repo_metadata)

    from prguard_ai.schemas.context import ReviewContext

    ctx = ReviewContext(
        pr_id="eval#0",
        diff_text=diff_text,
        repo_metadata=repo_metadata,
        agent_outputs={
            "style": style_output,
            "logic": logic_output,
            "security": security_output,
        },
    )
    report = arbitrate_confidence(ctx)

    detected = {_normalize_issue(i.model_dump()) for i in report.issues}

    if not expected_issues:
        return {
            "true_positive": 0,
            "false_positive": len(detected),
            "missed_issue": 0,
            "precision": 0.0,
            "recall": 0.0,
            "f1": 0.0,
            "confidence": float(report.overall_confidence),
        }

    expected_set = {_normalize_issue(e) for e in expected_issues}

    tp = len(detected & expected_set)
    fp = len(detected - expected_set)
    fn = len(expected_set - detected)

    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    f1 = _f1_score(precision, recall)

    return {
        "true_positive": tp,
        "false_positive": fp,
        "missed_issue": fn,
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "confidence": float(report.overall_confidence),
    }


def evaluate_dataset_file(path: Path) -> Dict[str, Any]:
    """Evaluate a single dataset JSON file and return metrics.

    Args:
        path: Path to a JSON file with ``diff`` and ``expected_issues`` fields.

    Returns:
        Metrics dict from :func:`evaluate_pr`, augmented with ``id`` and ``description``.
    """
    data = json.loads(path.read_text())
    diff_text = data.get("diff", "")
    expected = data.get("expected_issues") or []
    metrics = evaluate_pr(diff_text, expected)
    metrics["id"] = data.get("id", path.stem)
    metrics["description"] = data.get("description", "")
    return metrics


def run_evaluation_suite(dataset_path: Path) -> List[Dict[str, Any]]:
    """Run evaluation over all ``.json`` files in *dataset_path*.

    If *dataset_path* is a single file, only that file is evaluated.

    Args:
        dataset_path: A directory of ``.json`` dataset files or a single file.

    Returns:
        A list of per-file metrics dicts.
    """
    if dataset_path.is_file():
        return [evaluate_dataset_file(dataset_path)]

    results = []
    for json_file in sorted(dataset_path.glob("*.json")):
        results.append(evaluate_dataset_file(json_file))
    return results


__all__ = [
    "evaluate_pr",
    "evaluate_dataset_file",
    "run_evaluation_suite",
]


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Run PRGuard AI evaluation against a dataset file or directory."
    )
    parser.add_argument(
        "--dataset",
        required=True,
        type=Path,
        help="Path to a dataset JSON file or directory of JSON files.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Optional path to write the results JSON.",
    )
    args = parser.parse_args()

    if not args.dataset.exists():
        print(f"Error: dataset path does not exist: {args.dataset}", file=sys.stderr)
        sys.exit(1)

    results = run_evaluation_suite(args.dataset)

    output = json.dumps(results, indent=2)
    print(output)

    if args.output:
        args.output.write_text(output)
        print(f"\nResults written to {args.output}", file=sys.stderr)
