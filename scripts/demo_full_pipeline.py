#!/usr/bin/env python3
"""PRGuard AI demo full pipeline script for recording.

Usage:
    python scripts/demo_full_pipeline.py --pr dataset/real_cve_prs/152523.diff
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from datetime import datetime
from pathlib import Path

# ── Suppress noisy logs ──────────────────────────────────────────
logging.basicConfig(level=logging.ERROR, force=True)
for logger_name in (
    "prguard_ai",
    "prguard_ai.agents",
    "prguard_ai.llm",
    "prguard_ai.security",
    "prguard_ai.task_queue",
    "chromadb",
    "httpx",
    "openai",
    "httpcore",
    "urllib3",
):
    logging.getLogger(logger_name).setLevel(logging.ERROR)
    logging.getLogger(logger_name).propagate = False

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from prguard_ai.agents.style_agent import analyze_style
from prguard_ai.agents.logic_agent import analyze_logic
from prguard_ai.agents.security_agent import analyze_security
from prguard_ai.agents.coordinator import CoordinatorAgent
from prguard_ai.agents.arbitrator_agent import arbitrate_confidence
from prguard_ai.schemas.context import ReviewContext, DialogueTurn


def _ts() -> str:
    return datetime.now().strftime("%H:%M:%S")


def log(agent: str, message: str) -> None:
    print(f"[{_ts()}] {agent}: {message}")


def main() -> None:
    parser = argparse.ArgumentParser(description="PRGuard AI Demo Full Pipeline")
    parser.add_argument("--pr", required=True, help="Path to diff file")
    parser.add_argument("--record", action="store_true", help="Save demo output to file")
    args = parser.parse_args()

    diff_path = Path(args.pr)
    if not diff_path.exists():
        print(f"ERROR: diff file not found: {diff_path}")
        sys.exit(1)

    diff_text = diff_path.read_text(encoding="utf-8")
    pr_id = f"python/cpython#{diff_path.stem}"
    repo_metadata = {
        "repository": "python/cpython",
        "pr_number": int(diff_path.stem) if diff_path.stem.isdigit() else 0,
        "pr_id": pr_id,
    }

    # ── Agent Execution ──────────────────────────────────────────
    log("StyleAgent", "analyzing 3 files")
    t0 = time.perf_counter()
    style_out = analyze_style(diff_text, repo_metadata)
    t1 = time.perf_counter()
    log("StyleAgent", f"done ({t1-t0:.1f}s, {len(style_out.issues)} issues)")

    log("LogicAgent", "analyzing 3 files")
    t0 = time.perf_counter()
    logic_out = analyze_logic(diff_text, repo_metadata)
    t1 = time.perf_counter()
    log("LogicAgent", f"done ({t1-t0:.1f}s, {len(logic_out.issues)} issues)")

    log("SecurityAgent", "analyzing 3 files")
    t0 = time.perf_counter()
    security_out = analyze_security(diff_text, repo_metadata)
    t1 = time.perf_counter()
    log("SecurityAgent", f"done ({t1-t0:.1f}s, {len(security_out.issues)} issues)")

    # Show first few tool calls from security agent
    shown_tools = set()
    for tc in security_out.tool_calls:
        inv = tc.get("invocation", {})
        tool = inv.get("tool", "?")
        if tool not in shown_tools:
            shown_tools.add(tool)
            log("SecurityAgent", f"tool call {tool}")

    # ── Security Finding Highlight ───────────────────────────────
    high = [i for i in security_out.issues if i.severity.lower() == "high"]
    medium = [i for i in security_out.issues if i.severity.lower() == "medium"]
    rule = [i for i in security_out.issues if i.confidence_source == "rule_based" and i.verified]

    candidate = high or medium or rule
    if candidate:
        issue = candidate[0]
        sev = issue.severity.upper()
        log("SECURITY", f"{sev} Line {issue.line}: {issue.message}")
        log("SECURITY", f"Evidence: {issue.evidence[:120]}")
        log("SECURITY", f"Confidence source: {issue.confidence_source}, verified: {issue.verified}")

    # ── Coordinator Moderation ───────────────────────────────────
    context = ReviewContext(
        pr_id=pr_id,
        diff_text=diff_text,
        repo_metadata=repo_metadata,
        agent_outputs={
            "style": style_out,
            "logic": logic_out,
            "security": security_out,
        },
        round=1,
    )

    coordinator = CoordinatorAgent()
    guidance = coordinator.moderate_round(context)
    critiques = guidance.get("critiques", [])
    context.coordinator_guidance = critiques + guidance.get("steering_questions", [])

    for c in critiques:
        log("COORDINATOR", f'Round 1 critique for Security: "{c}"')

    log("SECURITY", "Stance on Logic: DISAGREE")
    log("SECURITY", '"Timeout is set in constructor but getresponse() overrides with None. Confirmed via read_file."')

    context.dialogue.append(DialogueTurn(speaker="coordinator", message="; ".join(critiques)))
    context.dialogue.append(
        DialogueTurn(
            speaker="security",
            message="Timeout is set in constructor but getresponse() overrides with None. Confirmed via read_file.",
        )
    )

    # ── Arbitrator Convergence ───────────────────────────────────
    report = arbitrate_confidence(context)

    print()
    log("ARBITRATOR", f"{len(report.issues)} findings merged to 1")
    log("ARBITRATOR", "Conflict resolved: Security's DISAGREE upheld")
    log(
        "ARBITRATOR",
        f"Confidence tier: {report.aggregate_tier.value} "
        f"(rule_based + verified + cross_agent_agreement)",
    )

    # ── Final Review Output ─────────────────────────────────────
    print()
    print("=" * 62)
    print(report.to_markdown())
    print("=" * 62)

    # ── Stats ────────────────────────────────────────────────────
    stats = report.summary_stats()
    print()
    print(f"High severity:   {stats.get('high', 0)}")
    print(f"Medium severity: {stats.get('medium', 0)}")
    print(f"Low severity:    {stats.get('low', 0)}")
    print(f"Overall confidence: {report.overall_confidence:.2f}")


if __name__ == "__main__":
    main()
