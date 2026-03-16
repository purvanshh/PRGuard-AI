"""Local demo script to run a PR review on a sample diff."""

from __future__ import annotations

from pathlib import Path

from prguard_ai.agents.arbitrator_agent import arbitrate_confidence
from prguard_ai.agents.logic_agent import analyze_logic
from prguard_ai.agents.security_agent import analyze_security
from prguard_ai.agents.style_agent import analyze_style
from prguard_ai.schemas.agent_output import AgentOutput
from prguard_ai.schemas.pr_report import PullRequestReport


def main() -> None:
    fixtures_dir = Path(__file__).resolve().parent.parent / "fixtures"
    diff_path = fixtures_dir / "sample_diff.txt"
    diff_text = diff_path.read_text(encoding="utf-8")

    repo_metadata = {"repository": "demo/repo", "pr_number": 1, "pr_id": "demo/repo#1"}

    style_output: AgentOutput = analyze_style(diff_text, repo_metadata)
    logic_output: AgentOutput = analyze_logic(diff_text, repo_metadata)
    security_output: AgentOutput = analyze_security(diff_text, repo_metadata)

    report: PullRequestReport = arbitrate_confidence(
        [style_output, logic_output, security_output]
    )

    print(report.to_markdown())


if __name__ == "__main__":
    main()

