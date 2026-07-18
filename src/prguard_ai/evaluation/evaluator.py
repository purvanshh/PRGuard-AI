"""Evaluation framework for PRGuard AI agents.

Usage (CLI):
    python -m prguard_ai.evaluation.evaluator --dataset path/to/example.json
    python -m prguard_ai.evaluation.evaluator --dataset path/to/dataset/
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from prguard_ai.agents.arbitrator_agent import arbitrate_confidence
from prguard_ai.agents.logic_agent import analyze_logic
from prguard_ai.agents.security_agent import analyze_security
from prguard_ai.agents.style_agent import analyze_style
from prguard_ai.schemas.agent_output import AgentOutput
from prguard_ai.schemas.context import ReviewContext


def _normalize_issue(issue: Dict[str, Any]) -> Tuple[int, str]:
    return int(issue.get("line", 0)), str(issue.get("message", "")).strip()


def _normalize_text(text: str) -> List[str]:
    return [token for token in re.split(r"[^a-z0-9]+", text.lower()) if token]


def _message_similarity(left: str, right: str) -> float:
    left_tokens = set(_normalize_text(left))
    right_tokens = set(_normalize_text(right))
    if not left_tokens and not right_tokens:
        return 1.0
    if not left_tokens or not right_tokens:
        return 0.0
    overlap = len(left_tokens & right_tokens)
    union = len(left_tokens | right_tokens)
    return overlap / union if union else 0.0


def semantic_issue_match(
    detected: Dict[str, Any],
    expected: Dict[str, Any],
    *,
    threshold: float = 0.55,
) -> bool:
    """Match issues semantically using line proximity and message similarity."""
    detected_line = int(detected.get("line", 0) or 0)
    expected_line = int(expected.get("line", 0) or 0)
    line_distance = abs(detected_line - expected_line)
    line_score = 1.0 if line_distance == 0 else 0.8 if line_distance <= 1 else 0.6 if line_distance <= 3 else 0.0

    message_score = _message_similarity(str(detected.get("message", "")), str(expected.get("message", "")))
    severity_bonus = 0.1 if str(detected.get("severity", "")).lower() == str(expected.get("severity", "")).lower() else 0.0
    score = (0.65 * message_score) + (0.35 * line_score) + severity_bonus
    return score >= threshold


def _f1_score(precision: float, recall: float) -> float:
    """Compute F1 score from precision and recall."""
    if precision + recall == 0.0:
        return 0.0
    return 2.0 * precision * recall / (precision + recall)


def _confidence_interval(samples: Sequence[float]) -> Dict[str, float]:
    if not samples:
        return {"mean": 0.0, "lower": 0.0, "upper": 0.0}
    mean = sum(samples) / len(samples)
    if len(samples) == 1:
        return {"mean": mean, "lower": mean, "upper": mean}
    variance = sum((value - mean) ** 2 for value in samples) / (len(samples) - 1)
    margin = 1.96 * math.sqrt(variance / len(samples))
    return {"mean": mean, "lower": max(0.0, mean - margin), "upper": min(1.0, mean + margin)}


def _greedy_match(
    detected: Sequence[Dict[str, Any]],
    expected: Sequence[Dict[str, Any]],
) -> Tuple[int, int, int]:
    remaining_expected = list(expected)
    tp = 0
    fp = 0
    for issue in detected:
        match_index = next(
            (index for index, candidate in enumerate(remaining_expected) if semantic_issue_match(issue, candidate)),
            None,
        )
        if match_index is None:
            fp += 1
            continue
        tp += 1
        remaining_expected.pop(match_index)
    fn = len(remaining_expected)
    return tp, fp, fn


def _metrics_for_detected(
    detected: Sequence[Dict[str, Any]],
    expected_issues: Optional[Sequence[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    if not expected_issues:
        return {
            "true_positive": 0,
            "false_positive": len(detected),
            "missed_issue": 0,
            "precision": 0.0,
            "recall": 0.0,
            "f1": 0.0,
        }

    tp, fp, fn = _greedy_match(list(detected), list(expected_issues))
    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    return {
        "true_positive": tp,
        "false_positive": fp,
        "missed_issue": fn,
        "precision": precision,
        "recall": recall,
        "f1": _f1_score(precision, recall),
    }


def _run_agents(diff_text: str) -> Tuple[Dict[str, AgentOutput], Any]:
    repo_metadata = {"repository": "eval/repo", "pr_number": 0, "pr_id": "eval#0"}
    outputs = {
        "style": analyze_style(diff_text, repo_metadata),
        "logic": analyze_logic(diff_text, repo_metadata),
        "security": analyze_security(diff_text, repo_metadata),
    }
    ctx = ReviewContext(
        pr_id="eval#0",
        diff_text=diff_text,
        repo_metadata=repo_metadata,
        agent_outputs=outputs,
    )
    return outputs, arbitrate_confidence(ctx)


def evaluate_pr(
    diff_text: str,
    expected_issues: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Run all agents on a diff and compare against expected issues."""
    outputs, report = _run_agents(diff_text)
    aggregate_detected = [issue.model_dump() for issue in report.issues]
    overall_metrics = _metrics_for_detected(aggregate_detected, expected_issues)
    overall_metrics["confidence"] = float(report.overall_confidence)
    overall_metrics["semantic_matches"] = overall_metrics["true_positive"]

    per_agent: Dict[str, Dict[str, Any]] = {}
    for name, output in outputs.items():
        agent_detected = [issue.model_dump() for issue in output.issues]
        metrics = _metrics_for_detected(agent_detected, expected_issues)
        metrics["confidence"] = float(output.confidence)
        metrics["issue_count"] = len(agent_detected)
        per_agent[name] = metrics

    overall_metrics["agent_metrics"] = per_agent
    return overall_metrics


def evaluate_dataset_file(path: Path) -> Dict[str, Any]:
    """Evaluate a single dataset JSON file and return metrics."""
    data = json.loads(path.read_text())
    diff_text = data.get("diff", "")
    expected = data.get("expected_issues") or []
    metrics = evaluate_pr(diff_text, expected)
    metrics["id"] = data.get("id", path.stem)
    metrics["description"] = data.get("description", "")
    metrics["expected_issue_count"] = len(expected)
    return metrics


def summarize_evaluation_results(results: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """Aggregate per-case results into a compact report."""
    if not results:
        return {"cases": 0, "overall": {}, "per_agent": {}}

    overall_f1 = [float(result.get("f1", 0.0)) for result in results]
    overall_precision = [float(result.get("precision", 0.0)) for result in results]
    overall_recall = [float(result.get("recall", 0.0)) for result in results]

    per_agent_scores: Dict[str, List[float]] = {"style": [], "logic": [], "security": []}
    for result in results:
        for agent, metrics in result.get("agent_metrics", {}).items():
            per_agent_scores.setdefault(agent, []).append(float(metrics.get("f1", 0.0)))

    return {
        "cases": len(results),
        "overall": {
            "f1": _confidence_interval(overall_f1),
            "precision": _confidence_interval(overall_precision),
            "recall": _confidence_interval(overall_recall),
        },
        "per_agent": {agent: _confidence_interval(scores) for agent, scores in per_agent_scores.items()},
    }


def run_evaluation_suite(dataset_path: Path) -> List[Dict[str, Any]]:
    """Run evaluation over all ``.json`` files in *dataset_path*."""
    if dataset_path.is_file():
        return [evaluate_dataset_file(dataset_path)]

    results = []
    for json_file in sorted(dataset_path.glob("*.json")):
        results.append(evaluate_dataset_file(json_file))
    return results


def _build_cli_payload(results: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    return {
        "results": list(results),
        "summary": summarize_evaluation_results(results),
    }


__all__ = [
    "evaluate_pr",
    "evaluate_dataset_file",
    "run_evaluation_suite",
    "semantic_issue_match",
    "summarize_evaluation_results",
    "_f1_score",
]


if __name__ == "__main__":
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
    payload = _build_cli_payload(results)
    output = json.dumps(payload, indent=2)
    print(output)

    if args.output:
        args.output.write_text(output, encoding="utf-8")
        print(f"\nResults written to {args.output}", file=sys.stderr)
