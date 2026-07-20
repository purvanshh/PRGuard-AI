"""Tests for Pydantic schemas: Issue, AgentOutput, PullRequestReport (Phase 15)."""

from __future__ import annotations

import pytest


# ---------------------------------------------------------------------------
# Issue schema tests
# ---------------------------------------------------------------------------

class TestIssueSchema:
    """Tests for the Issue Pydantic model."""

    def _make_issue(self, **overrides):
        from prguard_ai.schemas.agent_output import Issue

        defaults = {
            "line": 10,
            "severity": "HIGH",
            "message": "SQL injection detected",
            "evidence": "conn.execute('SELECT * FROM users WHERE name = ' + user_input)",
            "confidence_source": "rule_based",
        }
        defaults.update(overrides)
        return Issue(**defaults)

    def test_severity_normalised_to_lowercase(self):
        issue = self._make_issue(severity="HIGH")
        assert issue.severity == "high"

    def test_optional_file_path_defaults_to_none(self):
        issue = self._make_issue()
        assert issue.file_path is None

    def test_file_path_accepted(self):
        issue = self._make_issue(file_path="api/routes.py")
        assert issue.file_path == "api/routes.py"

    def test_line_must_be_positive(self):
        with pytest.raises(Exception):
            self._make_issue(line=0)

    def test_validate_and_sanitize_with_dict(self):
        from prguard_ai.schemas.agent_output import Issue

        raw = {
            "line": 5,
            "severity": "medium",
            "message": "<script>alert(1)</script>",
            "evidence": "some code",
            "confidence_source": "llm_reasoning",
        }
        issue = Issue.validate_and_sanitize(raw)
        assert "&lt;script&gt;" in issue.message

    def test_validate_and_sanitize_strips_non_printable(self):
        from prguard_ai.schemas.agent_output import Issue

        raw = {
            "line": 5,
            "severity": "low",
            "message": "msg\x00with\x01null",
            "evidence": "code",
            "confidence_source": "rule_based",
        }
        issue = Issue.validate_and_sanitize(raw)
        assert "\x00" not in issue.message
        assert "\x01" not in issue.message

    def test_validate_and_sanitize_with_issue_object(self):
        from prguard_ai.schemas.agent_output import Issue

        original = Issue(
            line=3, severity="low", message="bad code",
            evidence="x = eval(y)", confidence_source="rule_based",
        )
        result = Issue.validate_and_sanitize(original)
        assert result.message == "bad code"

    def test_validate_and_sanitize_raises_on_invalid_type(self):
        from prguard_ai.schemas.agent_output import Issue

        with pytest.raises(TypeError):
            Issue.validate_and_sanitize("not_a_dict_or_issue")


# ---------------------------------------------------------------------------
# AgentOutput schema tests
# ---------------------------------------------------------------------------

class TestAgentOutputSchema:
    """Tests for the AgentOutput Pydantic model."""

    def _make_output(self, **overrides):
        from prguard_ai.schemas.agent_output import AgentOutput

        defaults = {"agent": "style", "confidence": 0.75, "issues": []}
        defaults.update(overrides)
        return AgentOutput(**defaults)

    def test_default_llm_skipped_is_false(self):
        output = self._make_output()
        assert output.llm_skipped is False

    def test_default_error_is_none(self):
        output = self._make_output()
        assert output.error is None

    def test_confidence_must_be_in_range(self):
        with pytest.raises(Exception):
            self._make_output(confidence=1.5)
        with pytest.raises(Exception):
            self._make_output(confidence=-0.1)

    def test_issues_field_accepts_list_of_issues(self):
        from prguard_ai.schemas.agent_output import Issue

        issue = Issue(
            line=1, severity="high", message="test",
            evidence="code", confidence_source="rule_based",
        )
        output = self._make_output(issues=[issue])
        assert len(output.issues) == 1

    def test_error_field_populated(self):
        output = self._make_output(error="LLM timed out", llm_skipped=True)
        assert output.error == "LLM timed out"
        assert output.llm_skipped is True

    def test_model_dump_includes_all_fields(self):
        output = self._make_output()
        data = output.model_dump()
        assert "agent" in data
        assert "confidence" in data
        assert "issues" in data
        assert "llm_skipped" in data
        assert "error" in data


# ---------------------------------------------------------------------------
# PullRequestReport schema tests
# ---------------------------------------------------------------------------

class TestPullRequestReportSchema:
    """Tests for the PullRequestReport Pydantic model."""

    def _make_report(self, **overrides):
        from prguard_ai.schemas.pr_report import PullRequestReport

        defaults = {"overall_confidence": 0.7, "agent_outputs": [], "issues": []}
        defaults.update(overrides)
        return PullRequestReport(**defaults)

    def test_defaults(self):
        report = self._make_report()
        assert report.overall_confidence == pytest.approx(0.7)
        assert report.issues == []
        assert report.disagreements == []

    def test_overall_confidence_bounds(self):
        with pytest.raises(Exception):
            self._make_report(overall_confidence=1.1)
        with pytest.raises(Exception):
            self._make_report(overall_confidence=-0.1)

    def test_to_markdown_no_issues(self):
        report = self._make_report()
        md = report.to_markdown()
        assert "PRGuard AI Review" in md
        assert "No issues detected" in md
        assert "No major disagreements" in md

    def test_to_markdown_with_issues(self):
        from prguard_ai.schemas.agent_output import AgentOutput, Issue

        issue = Issue(
            line=10, severity="high", message="Command injection",
            evidence="subprocess.run(cmd, shell=True)", confidence_source="rule_based",
        )
        agent_out = AgentOutput(agent="security", confidence=0.9, issues=[issue])
        report = self._make_report(
            agent_outputs=[agent_out],
            issues=[issue],
        )
        md = report.to_markdown()
        assert "Command injection" in md
        assert "HIGH" in md

    def test_to_markdown_with_disagreements(self):
        report = self._make_report(disagreements=["logic reports HIGH while style does not."])
        md = report.to_markdown()
        assert "logic reports HIGH" in md

    def test_summary_stats_empty(self):
        report = self._make_report()
        stats = report.summary_stats()
        assert stats == {"high": 0, "medium": 0, "low": 0}

    def test_summary_stats_with_issues(self):
        from prguard_ai.schemas.agent_output import Issue

        issues = [
            Issue(line=1, severity="high", message="h1", evidence="e", confidence_source="rule_based"),
            Issue(line=2, severity="high", message="h2", evidence="e", confidence_source="rule_based"),
            Issue(line=3, severity="medium", message="m1", evidence="e", confidence_source="llm_reasoning"),
            Issue(line=4, severity="low", message="l1", evidence="e", confidence_source="inferred"),
        ]
        report = self._make_report(issues=issues)
        stats = report.summary_stats()
        assert stats["high"] == 2
        assert stats["medium"] == 1
        assert stats["low"] == 1

    def test_to_markdown_confidence_format(self):
        report = self._make_report(overall_confidence=0.856789)
        md = report.to_markdown()
        assert "**Confidence:**" in md


# ---------------------------------------------------------------------------
# ReviewContext schema tests
# ---------------------------------------------------------------------------

class TestReviewContextSchema:
    """Tests for the ReviewContext Pydantic model."""

    def test_defaults(self):
        from prguard_ai.schemas.context import ReviewContext

        ctx = ReviewContext(pr_id="owner/repo#1", diff_text="--- a\n+++ b\n")
        assert ctx.round == 0
        assert ctx.agent_outputs == {}
        assert ctx.dialogue == []

    def test_agent_outputs_populated(self):
        from prguard_ai.schemas.context import ReviewContext
        from prguard_ai.schemas.agent_output import AgentOutput

        agent_out = AgentOutput(agent="style", confidence=0.5, issues=[])
        ctx = ReviewContext(
            pr_id="owner/repo#1",
            diff_text="diff text",
            agent_outputs={"style": agent_out},
        )
        assert "style" in ctx.agent_outputs

    def test_dialogue_turn_appended(self):
        from prguard_ai.schemas.context import ReviewContext, DialogueTurn

        ctx = ReviewContext(pr_id="owner/repo#1", diff_text="diff")
        ctx.dialogue.append(DialogueTurn(speaker="logic", message="I found a null dereference."))
        assert len(ctx.dialogue) == 1
        assert ctx.dialogue[0].speaker == "logic"
