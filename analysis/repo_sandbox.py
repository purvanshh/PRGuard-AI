"""Repository sandboxing utilities for PRGuard AI.

Each PR analysis is executed inside a dedicated temp directory under:
  /tmp/prguard/{pr_id}/

This module is intentionally focused on isolation, sizing limits, and cleanup.
It does not implement any agent logic.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Tuple


SANDBOX_ROOT = Path("/tmp/prguard")

MAX_REPO_SIZE_BYTES = 200 * 1024 * 1024  # 200MB
MAX_FILE_SIZE_BYTES = 2 * 1024 * 1024  # 2MB
MAX_PYTHON_FILES_INDEXED = 1000


class RepoSandboxError(RuntimeError):
    pass


@dataclass(frozen=True)
class RepoSandboxResult:
    temp_path: Path
    python_files_indexed: int
    repo_size_bytes: int


def _safe_pr_id(repo_full_name: str, pr_number: int) -> str:
    # Prevent path traversal and keep filesystem-friendly.
    safe_repo = repo_full_name.replace("/", "__").replace("..", "_")
    return f"{safe_repo}#{int(pr_number)}"


def _iter_files(root: Path) -> Iterable[Path]:
    for p in root.rglob("*"):
        if p.is_symlink():
            continue
        if p.is_file():
            yield p


def _enforce_limits(repo_path: Path) -> Tuple[int, int]:
    total = 0
    py_count = 0
    for f in _iter_files(repo_path):
        try:
            sz = f.stat().st_size
        except OSError:
            continue
        if sz > MAX_FILE_SIZE_BYTES:
            raise RepoSandboxError(f"File too large for analysis: {f} ({sz} bytes)")
        total += sz
        if total > MAX_REPO_SIZE_BYTES:
            raise RepoSandboxError(f"Repository exceeds max size {MAX_REPO_SIZE_BYTES} bytes")
        if f.suffix == ".py":
            py_count += 1
            if py_count > MAX_PYTHON_FILES_INDEXED:
                raise RepoSandboxError(f"Too many Python files (> {MAX_PYTHON_FILES_INDEXED})")
    return total, py_count


def clone_repository(repo_url: str, pr_number: int, repo_full_name: str | None = None) -> RepoSandboxResult:
    """Clone repository into the PRGuard sandbox (shallow clone).

    Args:
        repo_url: HTTPS clone URL (recommended).
        pr_number: Pull request number.
        repo_full_name: Optional full name like "owner/repo" to stabilize pr_id.

    Returns:
        RepoSandboxResult describing the sandbox path and computed metrics.
    """
    if not repo_url:
        raise RepoSandboxError("Missing repo_url for cloning.")
    repo_full_name = repo_full_name or "repo"
    pr_id = _safe_pr_id(repo_full_name, pr_number)

    temp_path = SANDBOX_ROOT / pr_id
    temp_path.parent.mkdir(parents=True, exist_ok=True)

    # Ensure clean workspace for idempotency.
    if temp_path.exists():
        shutil.rmtree(temp_path, ignore_errors=True)

    env = os.environ.copy()
    env.setdefault("GIT_TERMINAL_PROMPT", "0")

    try:
        subprocess.run(
            ["git", "clone", "--depth", "1", repo_url, str(temp_path)],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env=env,
        )
    except subprocess.CalledProcessError as exc:
        raise RepoSandboxError("Failed to clone repository (shallow).") from exc

    repo_size, py_count = _enforce_limits(temp_path)
    return RepoSandboxResult(temp_path=temp_path, python_files_indexed=py_count, repo_size_bytes=repo_size)


def cleanup_repository(temp_path: str | Path) -> None:
    """Delete sandbox directory after analysis (best-effort)."""
    p = Path(temp_path)
    if not p.exists():
        return
    if SANDBOX_ROOT not in p.resolve().parents and p.resolve() != SANDBOX_ROOT.resolve():
        # Safety: never delete outside sandbox root.
        raise RepoSandboxError(f"Refusing to delete non-sandbox path: {p}")
    shutil.rmtree(p, ignore_errors=True)


__all__ = [
    "clone_repository",
    "cleanup_repository",
    "RepoSandboxError",
    "RepoSandboxResult",
    "SANDBOX_ROOT",
    "MAX_REPO_SIZE_BYTES",
    "MAX_FILE_SIZE_BYTES",
    "MAX_PYTHON_FILES_INDEXED",
]

