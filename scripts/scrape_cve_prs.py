#!/usr/bin/env python3
"""Scrape CVE fix PR diffs from public repos for evaluation.

Usage:
    python scripts/scrape_cve_prs.py \
        --repos python/cpython nodejs/node \
        --total 40 \
        --out dataset/real_cve_prs_batch2
"""

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path


REPOS = [
    "python/cpython",
    "nodejs/node",
]

CVE_QUERIES = [
    "CVE",
    "security fix",
    "security vulnerability",
    "GHSA",
    "fix security",
]


def search_prs(repo: str, query: str, limit: int) -> list[dict]:
    out = subprocess.run(
        [
            "gh", "search", "prs",
            "--repo", repo,
            query,
            "--merged",
            "--limit", str(limit),
            "--json", "number,title,url,repository,body",
        ],
        capture_output=True, text=True, timeout=30,
    )
    if out.returncode != 0:
        print(f"  gh search failed for {repo} / '{query}': {out.stderr.strip()}")
        return []
    return json.loads(out.stdout)


def download_diff(repo: str, pr_number: int, out_path: Path) -> bool:
    url = f"https://github.com/{repo}/pull/{pr_number}.diff"
    out = subprocess.run(
        ["curl", "-sfL", url],
        capture_output=True, text=True, timeout=30,
    )
    if out.returncode != 0 or not out.stdout.strip():
        return False
    out_path.write_text(out.stdout)
    return True


def extract_cve(body: str) -> str:
    import re
    for match in re.finditer(r"CVE-\d{4}-\d{4,}", body or ""):
        return match.group(0)
    return ""


def main():
    parser = argparse.ArgumentParser(description="Scrape CVE fix PR diffs")
    parser.add_argument("--repos", nargs="+", default=REPOS, help="GitHub repos")
    parser.add_argument("--total", type=int, default=40, help="Total PRs to scrape")
    parser.add_argument("--out", default="dataset/real_cve_prs_batch2", help="Output directory")
    args = parser.parse_args()

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    all_prs: list[dict] = []
    seen: set[str] = set()

    per_repo = max(1, args.total // len(args.repos))

    for repo in args.repos:
        print(f"\nSearching {repo}...")
        for query in CVE_QUERIES:
            if len(all_prs) >= args.total:
                break
            remaining = args.total - len(all_prs)
            prs = search_prs(repo, query, min(per_repo, remaining))
            for pr in prs:
                key = f"{repo}#{pr['number']}"
                if key not in seen:
                    pr["repo"] = repo
                    pr["key"] = key
                    pr["cve"] = extract_cve(pr.get("body", ""))
                    all_prs.append(pr)
                    seen.add(key)
            time.sleep(1.5)

    all_prs = all_prs[:args.total]
    print(f"\nFound {len(all_prs)} unique PRs to download")

    manifest = []
    for pr in all_prs:
        pr_id = f"{pr['repo'].replace('/', '_')}_{pr['number']}"
        diff_path = out_dir / f"{pr_id}.diff"

        print(f"  [{pr_id}] {pr['title'][:70]}...", end=" ")
        ok = download_diff(pr["repo"], pr["number"], diff_path)
        if ok:
            print("OK")
        else:
            print("FAILED")
            continue

        manifest.append({
            "pr_id": pr_id,
            "repo": pr["repo"],
            "pr_number": pr["number"],
            "title": pr["title"],
            "url": pr["url"],
            "cve": pr["cve"],
            "diff_file": str(diff_path),
        })
        time.sleep(1.0)

    manifest_path = out_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2))
    print(f"\nSaved {len(manifest)} PRs to {out_dir}")
    print(f"Manifest: {manifest_path}")


if __name__ == "__main__":
    main()
