#!/usr/bin/env python
"""Run evaluation benchmarks for PRGuard AI."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

from evaluation.evaluator import evaluate_pr


DATASET_DIR = Path("evaluation/dataset")
REPORT_PATH = Path("evaluation/report.md")


def load_dataset() -> List[Dict[str, Any]]:
    entries: List[Dict[str, Any]] = []
    if not DATASET_DIR.exists():
        return entries
    for path in sorted(DATASET_DIR.glob("*.json")):
        with path.open("r", encoding="utf-8") as f:
            entries.append(json.load(f))
    return entries


def main() -> None:
    dataset = load_dataset()
    if not dataset:
        print("No evaluation dataset found under evaluation/dataset/")
        return

    total_tp = total_fp = total_fn = 0
    confidences: List[float] = []

    lines: List[str] = []
    lines.append("# PRGuard AI Evaluation Report")
    lines.append("")
    lines.append("| ID | Precision | Recall | TP | FP | FN |")
    lines.append("| --- | --- | --- | --- | --- | --- |")

    for entry in dataset:
        diff = entry.get("diff", "")
        expected = entry.get("expected_issues") or []
        result = evaluate_pr(diff, expected_issues=expected)

        tp = int(result["true_positive"])
        fp = int(result["false_positive"])
        fn = int(result["missed_issue"])
        precision = float(result["precision"])
        recall = float(result["recall"])

        total_tp += tp
        total_fp += fp
        total_fn += fn

        # Confidence is computed inside evaluate_pr via arbitrator.
        conf = float(result.get("confidence", 0.0)) if "confidence" in result else 0.0
        confidences.append(conf)

        lines.append(
            f"| {entry.get('id', '')} | {precision:.2f} | {recall:.2f} | {tp} | {fp} | {fn} |"
        )

    micro_precision = (
        total_tp / (total_tp + total_fp) if (total_tp + total_fp) > 0 else 0.0
    )
    micro_recall = total_tp / (total_tp + total_fn) if (total_tp + total_fn) > 0 else 0.0
    f1 = (
        2 * micro_precision * micro_recall / (micro_precision + micro_recall)
        if (micro_precision + micro_recall) > 0
        else 0.0
    )
    avg_conf = sum(confidences) / len(confidences) if confidences else 0.0

    lines.append("")
    lines.append("## Aggregate Metrics")
    lines.append("")
    lines.append(f"- **Precision**: {micro_precision:.3f}")
    lines.append(f"- **Recall**: {micro_recall:.3f}")
    lines.append(f"- **F1 score**: {f1:.3f}")
    lines.append(f"- **Average confidence**: {avg_conf:.3f}")

    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text("\n".join(lines), encoding="utf-8")

    print(REPORT_PATH.read_text(encoding="utf-8"))


if __name__ == "__main__":
    main()

