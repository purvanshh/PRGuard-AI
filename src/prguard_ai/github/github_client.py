"""Thin GitHub client wrapper built on top of PyGithub."""

from __future__ import annotations

import logging
from typing import Dict, List, Optional

from github import Github

from prguard_ai.config.settings import settings
from prguard_ai.github.app_auth import get_installation_token

logger = logging.getLogger(__name__)


def _get_github_client(token: Optional[str] = None) -> Github:
    """
    Create a PyGithub client.

    Preference order:
    1. Explicit token argument (for testing/overrides).
    2. GitHub App installation token.
    3. Legacy personal access token from settings.github_token (fallback only).
    """
    effective_token: Optional[str] = token
    if not effective_token:
        try:
            effective_token = get_installation_token()
        except Exception:
            # Fallback to legacy PAT for local/dev environments.
            effective_token = settings.github_token

    if not effective_token:
        raise RuntimeError("No GitHub authentication token available (GitHub App and PAT missing).")

    return Github(effective_token)


def get_pr_diff(
    repo_full_name: str,
    pr_number: int,
    token: Optional[str] = None,
) -> str:
    """
    Fetch the unified diff for a pull request.
    """
    gh = _get_github_client(token)
    repo = gh.get_repo(repo_full_name)
    pr = repo.get_pull(pr_number)
    diff = repo.compare(pr.base.sha, pr.head.sha)
    return diff.diff


def format_pr_review(report: dict) -> str:
    """
    Format a PR review comment in Markdown from a PullRequestReport-like dict.
    """
    lines: List[str] = []
    lines.append("## PRGuard AI Review")
    lines.append("")
    lines.append(f"**Confidence Score:** {report.get('overall_confidence', 0.0):.2f}")
    lines.append("")

    agent_sections: Dict[str, List[dict]] = {"style": [], "logic": [], "security": []}
    for output in report.get("agent_outputs", []):
        agent_name = output.get("agent", "").lower()
        if agent_name in agent_sections:
            agent_sections[agent_name].extend(output.get("issues", []))

    def _render_section(title: str, issues: List[dict]) -> None:
        lines.append(f"### {title}")
        if not issues:
            lines.append("_No issues detected._")
        else:
            for issue in issues:
                lines.append(
                    f"- `{issue.get('severity', '').upper()}` "
                    f"(line {issue.get('line')}): {issue.get('message')}"
                )
        lines.append("")

    _render_section("Style", agent_sections["style"])
    _render_section("Logic", agent_sections["logic"])
    _render_section("Security", agent_sections["security"])

    disagreements = report.get("disagreements") or []
    lines.append("### Disagreement Summary")
    if disagreements:
        for d in disagreements:
            lines.append(f"- {d}")
    else:
        lines.append("_No major disagreements detected between agents._")

    return "\n".join(lines)


def post_pr_comment(
    repo_full_name: str,
    pr_number: int,
    body: str,
    token: Optional[str] = None,
) -> None:
    """
    Post a review-style comment on a pull request.
    """
    gh = _get_github_client(token)
    repo = gh.get_repo(repo_full_name)
    pr = repo.get_pull(pr_number)
    logger.info("Posting PR comment to %s#%s", repo_full_name, pr_number)
    pr.create_issue_comment(body)


def post_inline_comment(
    repo_full_name: str,
    pr_number: int,
    path: str,
    line: int,
    body: str,
    token: Optional[str] = None,
) -> None:
    """
    Post an inline comment on a specific file/line in a pull request.
    """
    gh = _get_github_client(token)
    repo = gh.get_repo(repo_full_name)
    pr = repo.get_pull(pr_number)
    commit_id = pr.head.sha
    logger.info(
        "Posting inline comment to %s#%s at %s:%s",
        repo_full_name,
        pr_number,
        path,
        line,
    )
    pr.create_review_comment(body, commit_id, path, line)


__all__ = ["get_pr_diff", "post_pr_comment", "format_pr_review", "post_inline_comment"]

