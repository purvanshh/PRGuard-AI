"""Thin GitHub client wrapper built on top of PyGithub."""

from __future__ import annotations

import logging
from typing import Optional

from github import Github

from config.settings import settings

logger = logging.getLogger(__name__)


def _get_github_client(token: Optional[str] = None) -> Github:
    """Create a PyGithub client using the provided or configured token."""
    token = token or settings.github_token
    if not token:
        raise RuntimeError("GitHub token is not configured.")
    return Github(token)


def get_pr_diff(
    repo_full_name: str,
    pr_number: int,
    token: Optional[str] = None,
) -> str:
    """
    Fetch the unified diff for a pull request.

    Args:
        repo_full_name: Repository in owner/name format.
        pr_number: Pull request number.
        token: Optional override for GitHub token.

    Returns:
        Unified diff string.
    """
    gh = _get_github_client(token)
    repo = gh.get_repo(repo_full_name)
    pr = repo.get_pull(pr_number)
    # PyGithub exposes the raw diff via the `raw_data` or `head`/`base` comparison.
    diff = repo.compare(pr.base.sha, pr.head.sha)
    return diff.diff


def post_pr_comment(
    repo_full_name: str,
    pr_number: int,
    body: str,
    token: Optional[str] = None,
) -> None:
    """
    Post a review-style comment on a pull request.

    Args:
        repo_full_name: Repository in owner/name format.
        pr_number: Pull request number.
        body: Comment body text.
        token: Optional override for GitHub token.
    """
    gh = _get_github_client(token)
    repo = gh.get_repo(repo_full_name)
    pr = repo.get_pull(pr_number)
    logger.info("Posting PR comment to %s#%s", repo_full_name, pr_number)
    pr.create_issue_comment(body)


__all__ = ["get_pr_diff", "post_pr_comment"]

