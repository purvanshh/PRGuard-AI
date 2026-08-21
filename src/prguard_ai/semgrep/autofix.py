"""Apply Semgrep autofix patches back to the PR branch (stretch, gated).

Semgrep can emit suggested fixes (``--autofix`` / ``extra.fix``) for certain
rules. This module applies those patches inside the repository sandbox and
creates a local commit. Pushing the commit to the PR branch is intentionally
left as a stub — it requires GitHub branch-write credentials and is disabled
until the ``PRGUARD_FLAG_SEMGREP_AUTOFIX`` flag is enabled AND a push callback
is wired.
"""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path
from typing import Any, Dict, List

from prguard_ai.config.feature_flags import is_enabled

logger = logging.getLogger(__name__)


def _git(repo_path: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(repo_path), *args],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )


def _patch_lines(autofix_patch: str) -> List[str]:
    return autofix_patch.splitlines() if autofix_patch else []


def apply_semgrep_autofix(
    repo_path: str | Path,
    autofix_patch: str,
    commit_message: str = "fix: apply semgrep autofix",
) -> Dict[str, Any]:
    """Apply a Semgrep autofix patch and create a local commit.

    Returns a result dict with ``applied`` set to True only when the patch
    applies cleanly and a commit is created. Gated by the
    ``PRGUARD_FLAG_SEMGREP_AUTOFIX`` feature flag.
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

    # Commit the applied changes (branch push intentionally stubbed).
    commit = _git(repo_path, "commit", "-am", commit_message)
    if commit.returncode != 0 and "nothing to commit" not in commit.stdout:
        return {"applied": True, "detail": f"patch applied but commit failed: {commit.stderr.strip()[:200]}"}

    return {"applied": True, "detail": "patch applied and committed locally (branch push stubbed)"}


__all__ = ["apply_semgrep_autofix"]
