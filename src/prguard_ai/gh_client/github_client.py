"""Thin GitHub client wrapper built on top of PyGithub."""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Dict, List, Optional

import requests as _requests

from github import Github

from prguard_ai.config.settings import settings
from prguard_ai.gh_client.app_auth import get_installation_token

logger = logging.getLogger(__name__)


def _is_truthy(value: str | None) -> bool:
    return str(value).lower() in {"1", "true", "yes", "on"}


def _offline_mode_enabled() -> bool:
    return _is_truthy(os.getenv("PRGUARD_OFFLINE_MODE", "0"))


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
        if _offline_mode_enabled():
            raise RuntimeError("Offline mode enabled; GitHub client is not available.")
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
    if _offline_mode_enabled():
        fake_path = os.getenv("PRGUARD_FAKE_DIFF_PATH")
        if not fake_path:
            fake_path = Path(__file__).resolve().parents[3] / "fixtures" / "sample_diff.txt"
        diff_path = Path(fake_path)
        if not diff_path.exists():
            raise RuntimeError(f"Offline mode enabled but fake diff not found at {diff_path}")
        logger.info("Offline mode: returning diff from %s", diff_path)
        return diff_path.read_text(encoding="utf-8")

    headers = {
        "Authorization": f"token {token or settings.github_token}",
        "Accept": "application/vnd.github.v3.diff",
    }
    url = f"https://api.github.com/repos/{repo_full_name}/pulls/{pr_number}"
    response = _requests.get(url, headers=headers)
    response.raise_for_status()
    return response.text


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
    if _offline_mode_enabled():
        logger.info("Offline mode: skipping PR comment post for %s#%s", repo_full_name, pr_number)
        return
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
    if _offline_mode_enabled():
        logger.info("Offline mode: skipping inline comment for %s#%s at %s:%s", repo_full_name, pr_number, path, line)
        return
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
