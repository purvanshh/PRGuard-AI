"""Apply Semgrep autofix patches back to the PR branch (stretch, gated).

Semgrep can emit suggested fixes (``--autofix`` / ``extra.fix``) for certain
rules. This module applies those patches inside the repository sandbox, creates
a local commit, and pushes it to the PR branch using an authenticated remote.
The whole flow is gated behind ``PRGUARD_FLAG_SEMGREP_AUTOFIX``.
"""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional

from prguard_ai.config.feature_flags import is_enabled

logger = logging.getLogger(__name__)


def _git(repo_path: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(repo_path), *args],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )


def _patch_lines(autofix_patch: str) -> List[str]:
    return autofix_patch.splitlines() if autofix_patch else []


def _get_push_token() -> Optional[str]:
    """Resolve a token usable for `git push`: GitHub App installation token
    preferred, legacy personal access token as fallback."""
    try:
        from prguard_ai.gh_client.app_auth import get_installation_token

        return get_installation_token()
    except Exception:
        logger.debug("Installation token unavailable; falling back to PAT", exc_info=True)
    return _get_pat_token()


def _get_pat_token() -> Optional[str]:
    from prguard_ai.config.settings import settings

    token = getattr(settings, "github_token", "") or ""
    return token or None


def _build_authed_remote(token: str, repo_full_name: str) -> str:
    """Build an authenticated HTTPS push URL for a GitHub repository."""
    return f"https://x-access-token:{token}@github.com/{repo_full_name}.git"


def push_autofix_commit(
    repo_path: str | Path,
    branch: str,
    repo_full_name: str,
    commit_message: str = "fix: apply semgrep autofix",
) -> Dict[str, Any]:
    """Create a commit from uncommitted changes and push it to the PR branch.

    Returns a result dict. Gated by ``PRGUARD_FLAG_SEMGREP_AUTOFIX``; fails
    cleanly when no token is configured or the push is rejected (e.g. the
    branch moved on).
    """
    if not is_enabled("semgrep_autofix"):
        return {"pushed": False, "detail": "autofix disabled"}

    repo_path = Path(repo_path)
    if not repo_path.is_dir() or not (repo_path / ".git").exists():
        return {"pushed": False, "detail": "not a git repository"}

    token = _get_push_token()
    if not token:
        logger.warning("Autofix push skipped: no GitHub token available")
        return {"pushed": False, "detail": "no GitHub token configured"}

    commit = _git(repo_path, "commit", "-am", commit_message)
    if commit.returncode != 0 and "nothing to commit" not in commit.stdout:
        return {"pushed": False, "detail": f"commit failed: {commit.stderr.strip()[:200]}"}

    remote = _build_authed_remote(token, repo_full_name)
    pushed = _git(repo_path, "push", remote, f"HEAD:{branch}")
    if pushed.returncode != 0:
        logger.error("Autofix push failed for %s: %s", repo_full_name, pushed.stderr[:300])
        return {"pushed": False, "detail": f"push rejected: {pushed.stderr.strip()[:300]}"}

    logger.info("Autofix committed and pushed to %s:%s", repo_full_name, branch)
    return {"pushed": True, "detail": f"committed and pushed to {branch}"}


def apply_semgrep_autofix(
    repo_path: str | Path,
    autofix_patch: str,
    commit_message: str = "fix: apply semgrep autofix",
    branch: Optional[str] = None,
    repo_full_name: Optional[str] = None,
) -> Dict[str, Any]:
    """Apply a Semgrep autofix patch, commit, and optionally push.

    When ``branch`` and ``repo_full_name`` are provided the commit is pushed
    to the PR branch via ``push_autofix_commit``. Returns a result dict with
    ``applied`` set to True only when the patch applies cleanly.
    """
    if not is_enabled("semgrep_autofix"):
        logger.info("Semgrep autofix disabled (PRGUARD_FLAG_SEMGREP_AUTOFIX unset)")
        return {"applied": False, "detail": "autofix disabled"}

    repo_path = Path(repo_path)
    if not repo_path.is_dir() or not (repo_path / ".git").exists():
        logger.warning("Autofix target %s is not a git repository", repo_path)
        return {"applied": False, "detail": "not a git repository"}

    patch = _patch_lines(autofix_patch)
    if not patch:
        return {"applied": False, "detail": "empty patch"}

    # Write the patch into the sandbox and validate with --check first.
    patch_file = repo_path / ".semgrep-autofix.patch"
    try:
        patch_file.write_text(autofix_patch, encoding="utf-8")
        check = _git(repo_path, "apply", "--check", str(patch_file.name))
        if check.returncode != 0:
            return {"applied": False, "detail": f"patch rejected: {check.stderr.strip()[:300]}"}
        applied = _git(repo_path, "apply", str(patch_file.name))
        if applied.returncode != 0:
            return {"applied": False, "detail": f"patch apply failed: {applied.stderr.strip()[:300]}"}
    finally:
        patch_file.unlink(missing_ok=True)

    # Stage the applied changes before pushing (push_autofix_commit commits -am).
    _git(repo_path, "add", "-A")

    if branch and repo_full_name:
        push = push_autofix_commit(repo_path, branch, repo_full_name, commit_message=commit_message)
        return {"applied": True, **push}

    commit = _git(repo_path, "commit", "-am", commit_message)
    if commit.returncode != 0 and "nothing to commit" not in commit.stdout:
        return {"applied": True, "detail": f"patch applied but commit failed: {commit.stderr.strip()[:200]}"}

    return {"applied": True, "detail": "patch applied and committed locally"}


__all__ = ["apply_semgrep_autofix", "push_autofix_commit"]
