#!/usr/bin/env python3
"""Generate a labels.jsonl template from a results file and manifest.

Usage:
    python scripts/generate_labels_template.py \
        --results dataset/real_cve_prs_batch2/results.json \
        --manifest dataset/real_cve_prs_batch2/manifest.json \
        --output dataset/real_cve_prs_batch2/labels.jsonl
"""

import argparse
import json
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description="Generate labels template")
    parser.add_argument("--results", required=True, help="Results JSON from batch_review.py")
    parser.add_argument("--manifest", required=True, help="Manifest JSON from scrape_cve_prs.py")
    parser.add_argument("--output", required=True, help="Output labels.jsonl path")
    args = parser.parse_args()

    results = json.loads(Path(args.results).read_text())
    manifest = json.loads(Path(args.manifest).read_text())

    manifest_map = {e["pr_id"]: e for e in manifest}

    lines = []
    for r in results:
        pr_id = r["pr_id"]
        entry = manifest_map.get(pr_id, {})
        cve = entry.get("cve", "")
        title = entry.get("title", "")

        lines.append(json.dumps({
            "pr_id": pr_id,
            "repo": entry.get("repo", ""),
            "title": title,
            "cve": cve,
            "expected_issues": [],
            "notes": "",
        }))

    output_path = Path(args.output)
    output_path.write_text("\n".join(lines) + "\n")
    print(f"Wrote {len(lines)} labels to {output_path}")
    print("Edit the 'expected_issues' and 'notes' fields to add ground truth.")


if __name__ == "__main__":
    main()
