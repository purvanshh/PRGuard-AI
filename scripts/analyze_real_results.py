#!/usr/bin/env python3
import json
from pathlib import Path

def main():
    results = json.loads(Path("dataset/real_cve_prs/evaluation_results.json").read_text())
    labels = [json.loads(line) for line in Path("dataset/real_cve_prs/labels.jsonl").read_text().strip().split('\n') if line.strip()]

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
    print(f"Precision: {precision:.2f}")
    print(f"Recall:    {recall:.2f}")
    print(f"F1:        {f1:.2f}")

if __name__ == "__main__":
    main()
