"""Local demo CLI for PRGuard AI.

Usage:

    python scripts/prguard_demo.py path/to/repo diff.patch [--record-demo]

This runs the style, logic, and security agents plus the arbitrator on the
provided diff, then prints a Markdown review report and per-agent timings.
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any, Dict

from agents.arbitrator_agent import arbitrate_confidence
from agents.logic_agent import analyze_logic
from agents.security_agent import analyze_security
from agents.style_agent import analyze_style
from schemas.agent_output import AgentOutput


def _run_demo(repo_path: Path, diff_path: Path, record_demo: bool) -> None:
    if not diff_path.exists():
        raise SystemExit(f"Diff file does not exist: {diff_path}")

    diff_text = diff_path.read_text(encoding="utf-8")
    repo_name = repo_path.name
    pr_id = f"{repo_name}#demo"
    repo_metadata: Dict[str, Any] = {
        "repository": repo_name,
        "pr_number": 0,
        "pr_id": pr_id,
    }

    timings: Dict[str, float] = {}

    start = time.perf_counter()
    style_output: AgentOutput = analyze_style(diff_text, repo_metadata)
    timings["style"] = time.perf_counter() - start

    start = time.perf_counter()
    logic_output: AgentOutput = analyze_logic(diff_text, repo_metadata)
    timings["logic"] = time.perf_counter() - start

    start = time.perf_counter()
    security_output: AgentOutput = analyze_security(diff_text, repo_metadata)
    timings["security"] = time.perf_counter() - start

    start = time.perf_counter()
    report = arbitrate_confidence([style_output, logic_output, security_output])
    timings["arbitrator"] = time.perf_counter() - start

    # Print Markdown report.
    print("PRGuard AI Review")
    print(f"Confidence: {float(report.overall_confidence):.2f}")
    print()

    def _count_issues(agent_name: str) -> int:
        for ao in report.agent_outputs:
            if ao.agent.lower() == agent_name:
                return len(ao.issues)
        return 0

    print(f"Style issues: {_count_issues('style')}")
    print(f"Logic issues: {_count_issues('logic')}")
    print(f"Security issues: {_count_issues('security')}")
    print()
    print("Agent runtime:")
    for agent in ["style", "logic", "security", "arbitrator"]:
        dur = timings.get(agent, 0.0)
        print(f"{agent}: {dur:.2f}s")

    if record_demo:
        payload = {
            "pr_id": pr_id,
            "repo": str(repo_path),
            "diff_path": str(diff_path),
            "timings": timings,
            "style_output": style_output.dict(),
            "logic_output": logic_output.dict(),
            "security_output": security_output.dict(),
            "report": report.dict(),
        }
        out_dir = Path("demo_recordings")
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"{repo_name}_demo.json"
        out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        print()
        print(f"Demo recording saved to {out_path}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a local PRGuard AI demo.")
    parser.add_argument("repo_path", type=str, help="Path to the repository root")
    parser.add_argument("diff_path", type=str, help="Path to a unified diff file")
    parser.add_argument(
        "--record-demo",
        action="store_true",
        help="Record agent outputs and final report to demo_recordings/",
    )
    args = parser.parse_args()

    _run_demo(Path(args.repo_path), Path(args.diff_path), record_demo=args.record_demo)


if __name__ == "__main__":
    main()

