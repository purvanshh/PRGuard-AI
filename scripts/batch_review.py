#!/usr/bin/env python3
"""Run PRGuard batch review on scraped PR diffs.

Saves results incrementally so progress is never lost.

Usage:
    python scripts/batch_review.py \
        --input dataset/real_cve_prs_batch2 \
        --parallel 4 \
        --output dataset/real_cve_prs_batch2/results.json
"""

import argparse
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from prguard_ai.analysis.diff_parser import parse_diff
from prguard_ai.agents.style_agent import StyleAgent
from prguard_ai.agents.logic_agent import LogicAgent
from prguard_ai.agents.security_agent import SecurityAgent
from prguard_ai.llm.client import LLMClient
from prguard_ai.llm.token_budget import TokenBudget


def review_single(pr_id: str, diff_text: str, idx: int, total: int) -> dict:
    start = time.perf_counter()
    print(f"[{idx}/{total}] Reviewing {pr_id}...", flush=True)

    try:
        files = parse_diff(diff_text)
        budget = TokenBudget(pr_id=pr_id, max_tokens=8000)
        llm = LLMClient(token_budget=budget)

        style = StyleAgent(llm=llm)
        logic = LogicAgent(llm=llm)
        security = SecurityAgent(llm=llm)

        style_out = style.run_react_loop(diff_text)
        logic_out = logic.run_react_loop(diff_text)
        security_out = security.run_react_loop(diff_text)

        elapsed = time.perf_counter() - start

        result = {
            "pr_id": pr_id,
            "files_changed": len(files),
            "elapsed_s": round(elapsed, 1),
            "style": {
                "issue_count": len(style_out.issues),
                "issues": [
                    {"line": i.line, "severity": i.severity, "message": i.message[:100]}
                    for i in style_out.issues[:10]
                ],
            },
            "logic": {
                "issue_count": len(logic_out.issues),
                "issues": [
                    {"line": i.line, "severity": i.severity, "message": i.message[:100]}
                    for i in logic_out.issues[:10]
                ],
            },
            "security": {
                "issue_count": len(security_out.issues),
                "issues": [
                    {"line": i.line, "severity": i.severity, "message": i.message[:100]}
                    for i in security_out.issues[:10]
                ],
            },
            "tokens_used": budget.used,
            "llm_calls": getattr(llm, "call_count", 0),
        }
        print(f"  Done: {result['style']['issue_count']}S / {result['logic']['issue_count']}L / {result['security']['issue_count']}C  [{elapsed:.0f}s]", flush=True)
        return result

    except Exception as e:
        elapsed = time.perf_counter() - start
        print(f"  ERROR ({elapsed:.0f}s): {e}", flush=True)
        return {"pr_id": pr_id, "error": str(e), "elapsed_s": round(elapsed, 1)}


def load_existing(output_path: Path) -> list:
    if output_path.exists():
        return json.loads(output_path.read_text())
    return []


def save_results(results: list, output_path: Path):
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(results, indent=2))
    print(f"  (checkpoint: {len(results)} results)", flush=True)


def main():
    parser = argparse.ArgumentParser(description="Batch review PR diffs")
    parser.add_argument("--input", default="dataset/real_cve_prs_batch2", help="Input directory with .diff files")
    parser.add_argument("--output", default="dataset/real_cve_prs_batch2/results.json", help="Output results file")
    parser.add_argument("--parallel", type=int, default=4, help="Parallel reviewers")
    parser.add_argument("--manifest", default="manifest.json", help="Manifest filename in input dir")
    parser.add_argument("--resume", action="store_true", help="Resume from existing results")
    args = parser.parse_args()

    input_dir = Path(args.input)
    output_path = Path(args.output)

    existing = load_existing(output_path) if args.resume else []
    done_ids = {r["pr_id"] for r in existing}
    if done_ids:
        print(f"Resuming: {len(existing)} already done, skipping {len(done_ids)} PRs")

    # Load manifest if available
    manifest_path = input_dir / args.manifest
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text())
        diffs: list[tuple[str, str]] = []
        for entry in manifest:
            if entry["pr_id"] in done_ids:
                continue
            diff_path = Path(entry["diff_file"])
            if diff_path.exists():
                diffs.append((entry["pr_id"], diff_path.read_text(encoding="utf-8")))
            else:
                print(f"Missing diff: {diff_path}")
    else:
        diff_files = sorted(input_dir.glob("*.diff"))
        diffs = [(f.stem, f.read_text(encoding="utf-8")) for f in diff_files if f.stem not in done_ids]

    if not diffs:
        print("No diffs to process (all done or none found)")
        if existing:
            print_summary(existing)
        return

    print(f"Reviewing {len(diffs)} PRs ({args.parallel} parallel)...\n")

    results = list(existing)
    with ThreadPoolExecutor(max_workers=args.parallel) as pool:
        futures = {
            pool.submit(review_single, pr_id, diff_text, i + 1, len(diffs)): (i, pr_id)
            for i, (pr_id, diff_text) in enumerate(diffs)
        }
        for future in as_completed(futures):
            i, pr_id = futures[future]
            try:
                result = future.result()
            except Exception as e:
                result = {"pr_id": pr_id, "error": str(e)}
            results.append(result)
            save_results(results, output_path)

    results.sort(key=lambda r: r.get("pr_id", ""))
    save_results(results, output_path)

    print_summary(results)


def print_summary(results: list):
    total = len(results)
    ok = sum(1 for r in results if "error" not in r)
    with_security = sum(1 for r in results if "security" in r and r["security"]["issue_count"] > 0)
    total_tokens = sum(r.get("tokens_used", 0) for r in results if "tokens_used" in r)

    print("\n" + "=" * 50)
    print(f"Total:     {total}")
    print(f"OK:        {ok}")
    print(f"Errors:    {total - ok}")
    print(f"Security:  {with_security}")
    print(f"Tokens:    {total_tokens}")
    print(f"Avg tok:   {total_tokens // max(ok, 1)}")


if __name__ == "__main__":
    main()
