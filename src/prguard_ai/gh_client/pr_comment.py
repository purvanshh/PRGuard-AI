"""PR comment formatting for PRGuard AI (wrapper around github_client)."""

from __future__ import annotations

from prguard_ai.gh_client.github_client import format_pr_review, post_pr_comment, post_inline_comment
from prguard_ai.llm.client import LLMOutputValidator


def format_review_comment(report: dict) -> str:
    validator = LLMOutputValidator()

    if "issues" in report:
        for issue in report["issues"]:
            issue["message"] = validator.sanitize_for_github(str(issue.get("message", "")))
            if "evidence" in issue:
                issue["evidence"] = validator.sanitize_for_github(str(issue.get("evidence", "")))

    if "agent_outputs" in report:
        for output in report["agent_outputs"]:
            for issue in output.get("issues", []):
                issue["message"] = validator.sanitize_for_github(str(issue.get("message", "")))
                if "evidence" in issue:
                    issue["evidence"] = validator.sanitize_for_github(str(issue.get("evidence", "")))

    return format_pr_review(report)


__all__ = [
    "format_review_comment",
    "format_pr_review",
    "post_pr_comment",
    "post_inline_comment",
]
