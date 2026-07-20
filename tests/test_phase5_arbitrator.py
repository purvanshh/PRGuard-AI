from prguard_ai.agents.arbitrator_agent import (
    deduplicate_issues,
    resolve_conflicts,
)
from prguard_ai.schemas.agent_output import AgentOutput, Issue
from prguard_ai.schemas.pr_report import PullRequestReport


def issue(line: int, severity: str, message: str, file_path: str = "app.py") -> Issue:
    return Issue(
        line=line,
        severity=severity,
        message=message,
        evidence="user input reaches sql query",
        confidence_source="llm_reasoning",
        file_path=file_path,
    )


def test_deduplicate_issues_clusters_similar_findings():
    findings = [
        issue(10, "high", "SQL injection through user input"),
        issue(10, "medium", "User input can reach SQL query"),
        issue(30, "low", "Line too long"),
    ]

    deduped = deduplicate_issues(findings)

    assert len(deduped) == 2
    assert any("corroborated" in item.message for item in deduped)


def test_resolve_conflicts_reports_same_line_severity_disagreement():
    outputs = [
        AgentOutput(agent="security", confidence=0.8, issues=[issue(7, "high", "Unsafe eval")]),
        AgentOutput(agent="logic", confidence=0.7, issues=[issue(7, "medium", "Input validation gap")]),
    ]

    conflicts = resolve_conflicts(outputs)

    assert conflicts
    assert "app.py:7" in conflicts[0]


def test_report_markdown_is_single_narrative_findings_section():
    report = PullRequestReport(
        overall_confidence=0.77,
        issues=[issue(12, "high", "SQL injection")],
        agent_outputs=[AgentOutput(agent="security", confidence=0.8, issues=[])],
    )

    markdown = report.to_markdown()

    assert "### Findings" in markdown
    assert "### Style" not in markdown
    assert "**Confidence:**" in markdown
    assert "Confidence basis" in markdown
