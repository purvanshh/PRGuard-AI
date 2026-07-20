#!/usr/bin/env python3
"""Analyze PRGuard evaluation results against ground truth labels.

Usage:
    python scripts/analyze_real_results.py                          # default: batch1
    python scripts/analyze_real_results.py --labels dataset/real_cve_prs/labels.jsonl --results dataset/real_cve_prs/evaluation_results.json
    python scripts/analyze_real_results.py --labels dataset/real_cve_prs_batch2/labels.jsonl --results dataset/real_cve_prs_batch2/results.json
    python scripts/analyze_real_results.py --summary               # summary only, no labels needed
"""

import argparse
import json
from pathlib import Path


def load_labels(path: str) -> list:
    text = Path(path).read_text().strip()
    return [json.loads(line) for line in text.split("\n") if line.strip()]


def main():
    parser = argparse.ArgumentParser(description="Evaluate PRGuard results")
    parser.add_argument("--labels", default="dataset/real_cve_prs/labels.jsonl")
    parser.add_argument("--results", default="dataset/real_cve_prs/evaluation_results.json")
    parser.add_argument("--summary", action="store_true", help="Summary only (no ground truth needed)")
    args = parser.parse_args()

    results = json.loads(Path(args.results).read_text())

    if args.summary:
        print_summary(results)
        return

    labels = load_labels(args.labels)
    print_evaluation(results, labels)


def print_summary(results: list):
    print("=== PRGuard Review Summary ===\n")
    ok = [r for r in results if "error" not in r]
    errors = [r for r in results if "error" in r]

    print(f"Total PRs:       {len(results)}")
    print(f"Successful:      {len(ok)}")
    print(f"Errors:          {len(errors)}")
    print()

    if ok:
        total_style = sum(r["style"]["issue_count"] for r in ok)
        total_logic = sum(r["logic"]["issue_count"] for r in ok)
        total_security = sum(r["security"]["issue_count"] for r in ok)
        with_sec = sum(1 for r in ok if r["security"]["issue_count"] > 0)
        total_tokens = sum(r.get("tokens_used", 0) for r in ok)
        avg_time = sum(r.get("elapsed_s", 0) for r in ok) / len(ok)

        print(f"Style issues:    {total_style}")
        print(f"Logic issues:    {total_logic}")
        print(f"Security issues: {total_security}")
        print(f"PRs w/ security: {with_sec}")
        print(f"Total tokens:    {total_tokens}")
        print(f"Avg time/PR:     {avg_time:.0f}s")
        print()

        for r in ok:
            sec = r["security"]
            top = sec["issues"][0]["message"][:70] if sec["issues"] else "(none)"
            print(f"  {r['pr_id']:30s}  S:{r['style']['issue_count']}  L:{r['logic']['issue_count']}  C:{sec['issue_count']}  [{top}]")

    if errors:
        print(f"\nErrors ({len(errors)}):")
        for r in errors:
            print(f"  {r['pr_id']}: {r.get('error', 'Unknown')}")


def print_evaluation(results: list, labels: list):
    print("=== Real PR Evaluation ===\n")

    tp = fp = fn = 0

    for label in labels:
        pr_id = label["pr_id"]
        result = next((r for r in results if r["pr_id"] == pr_id), None)

        if not result or "error" in result:
            print(f"PR #{pr_id}: ERROR - {result.get('error', 'Not found')}")
            continue

        expected = len(label.get("expected_issues", []))
        found_security = result["security"]["issue_count"]

        if expected > 0 and found_security > 0:
            tp += 1
            status = "HIT"
        elif expected == 0 and found_security > 0:
            fp += 1
            status = "FALSE POSITIVE"
        elif expected > 0 and found_security == 0:
            fn += 1
            status = "MISS"
        else:
            status = "CORRECT (no issues)"

        print(f"PR #{pr_id}: {status}")
        print(f"  Expected: {expected} | Found: {found_security}")
        if result["security"]["issues"]:
            print(f"  Top finding: {result['security']['issues'][0]['message'][:80]}")
        print()

    precision = tp / (tp + fp) if (tp + fp) > 0 else 0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0

    print(f"=== Metrics ===")
    print(f"True Positives:  {tp}")
    print(f"False Positives: {fp}")
    print(f"False Negatives: {fn}")
    print(f"Precision:       {precision:.2f}")
    print(f"Recall:          {recall:.2f}")
    print(f"F1:              {f1:.2f}")


if __name__ == "__main__":
    main()
