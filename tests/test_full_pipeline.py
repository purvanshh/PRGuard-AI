"""End-to-end style/logic/security + arbitrator smoke test."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Tuple

import pytest

from prguard_ai.agents.arbitrator_agent import arbitrate_confidence
from prguard_ai.agents.logic_agent import analyze_logic
from prguard_ai.agents.security_agent import analyze_security
from prguard_ai.agents.style_agent import analyze_style
from llm import client as llm_client
from prguard_ai.schemas.agent_output import AgentOutput
from prguard_ai.schemas.pr_report import PullRequestReport


FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"


def _mock_generate_analysis(prompt: str, *args: Any, **kwargs: Any) -> Tuple[str, dict]:
    # Always return an empty array, meaning "no additional issues".
    return "[]", {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}


@pytest.fixture(autouse=True)
def mock_llm(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(llm_client, "generate_analysis", _mock_generate_analysis)


def test_full_pipeline_with_sample_diff() -> None:
    diff_text = (FIXTURES / "sample_diff.txt").read_text(encoding="utf-8")
    repo_metadata = {"repository": "owner/repo", "pr_number": 1, "pr_id": "owner/repo#1"}

    style_output = analyze_style(diff_text, repo_metadata)
    logic_output = analyze_logic(diff_text, repo_metadata)
    security_output = analyze_security(diff_text, repo_metadata)

    assert isinstance(style_output, AgentOutput)
    assert isinstance(logic_output, AgentOutput)
    assert isinstance(security_output, AgentOutput)

    report: PullRequestReport = arbitrate_confidence(
        [style_output, logic_output, security_output]
    )

    assert isinstance(report, PullRequestReport)
    assert 0.0 <= report.overall_confidence <= 1.0
    assert isinstance(report.issues, list)
    md = report.to_markdown()
    assert "PRGuard AI Review" in md
    stats = report.summary_stats()
    assert set(stats.keys()) == {"high", "medium", "low"}

