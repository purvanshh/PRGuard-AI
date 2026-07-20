#!/usr/bin/env python3
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from prguard_ai.analysis.diff_parser import parse_diff
from prguard_ai.agents.style_agent import StyleAgent
from prguard_ai.agents.logic_agent import LogicAgent
from prguard_ai.agents.security_agent import SecurityAgent
from prguard_ai.llm.client import LLMClient
from prguard_ai.llm.token_budget import TokenBudget


def run_prguard_on_diff(diff_path: Path) -> dict:
    diff_text = diff_path.read_text()
    files = parse_diff(diff_text)

    pr_id = diff_path.stem

    budget = TokenBudget(pr_id=pr_id, max_tokens=8000)
    llm = LLMClient(token_budget=budget)

    style = StyleAgent(llm=llm)
    logic = LogicAgent(llm=llm)
    security = SecurityAgent(llm=llm)

    style_out = style.run_react_loop(diff_text)
    logic_out = logic.run_react_loop(diff_text)
    security_out = security.run_react_loop(diff_text)

    return {
        "pr_id": pr_id,
        "files_changed": len(files),
        "style": {
            "issue_count": len(style_out.issues),
            "issues": [{"line": i.line, "severity": i.severity, "message": i.message[:100]}
                      for i in style_out.issues[:5]]
        },
        "logic": {
            "issue_count": len(logic_out.issues),
            "issues": [{"line": i.line, "severity": i.severity, "message": i.message[:100]}
                      for i in logic_out.issues[:5]]
        },
        "security": {
            "issue_count": len(security_out.issues),
            "issues": [{"line": i.line, "severity": i.severity, "message": i.message[:100]}
                      for i in security_out.issues[:5]]
        },
        "tokens_used": budget.used,
        "llm_calls": getattr(llm, 'call_count', 0),
    }


def main():
    pr_dir = Path("dataset/real_cve_prs")
    diffs = sorted(pr_dir.glob("*.diff"))

    print(f"Found {len(diffs)} diffs\n")

    results = []
    for diff_path in diffs:
        print(f"Processing {diff_path.name}...")
        try:
            result = run_prguard_on_diff(diff_path)
            results.append(result)
            print(f"  Style: {result['style']['issue_count']} | "
                  f"Logic: {result['logic']['issue_count']} | "
                  f"Security: {result['security']['issue_count']} | "
                  f"Tokens: {result['tokens_used']}")
        except Exception as e:
            print(f"  - Error: {e}")
            results.append({"pr_id": diff_path.stem, "error": str(e)})

    output_path = Path("dataset/real_cve_prs/evaluation_results.json")
    output_path.write_text(json.dumps(results, indent=2))
    print(f"\nResults saved to {output_path}")

    total_security = sum(1 for r in results if "security" in r and r["security"]["issue_count"] > 0)
    total_tokens = sum(r.get("tokens_used", 0) for r in results if "tokens_used" in r)

    print(f"\nSummary:")
    print(f"  PRs processed: {len(results)}")
    print(f"  PRs with security findings: {total_security}")
    print(f"  Total tokens: {total_tokens}")
    print(f"  Avg tokens/PR: {total_tokens // max(len(results), 1)}")


if __name__ == "__main__":
    main()
