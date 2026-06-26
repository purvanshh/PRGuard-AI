"""Repository sandboxing utilities for PRGuard AI.

Each PR analysis is executed inside a dedicated temp directory under:
  /tmp/prguard/{pr_id}/

This module is intentionally focused on isolation, sizing limits, and cleanup.
It does not implement any agent logic.
"""

from __future__ import annotations

import ipaddress
import logging
import os
import shutil
import subprocess
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Tuple
from urllib.parse import urlparse

from prguard_ai.analysis.repo_cache import get_cached_repo

logger = logging.getLogger(__name__)


SANDBOX_ROOT = Path("/tmp/prguard")

MAX_REPO_SIZE_BYTES = 200 * 1024 * 1024  # 200MB
MAX_FILE_SIZE_BYTES = 2 * 1024 * 1024  # 2MB
MAX_PYTHON_FILES_INDEXED = 1000


def _is_truthy(value: str | None) -> bool:
    return str(value).lower() in {"1", "true", "yes", "on"}


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


def _validate_repo_url(repo_url: str) -> str:
    parsed = urlparse(repo_url)
    if parsed.scheme.lower() != "https":
        raise RepoSandboxError("Only https clone URLs are permitted.")
    if not parsed.netloc:
        raise RepoSandboxError("Invalid repository URL: missing host.")

    host = parsed.hostname or ""
    try:
        ip = ipaddress.ip_address(host)
        if ip.is_private or ip.is_loopback or ip.is_reserved or ip.is_link_local or ip.is_unspecified or ip.is_multicast:
            raise RepoSandboxError("Repository host is not allowed (private/loopback IP).")
    except ValueError:
        # Hostname, not an IP. Block obvious localhost-style names.
        lowered = host.lower()
        if lowered in {"localhost", "127.0.0.1"}:
            raise RepoSandboxError("Repository host localhost is not allowed.")

    return repo_url


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

from prguard_ai.config.settings import settings


def clone_repository(repo_url: str, pr_number: int, repo_full_name: str | None = None) -> RepoSandboxResult:
    """Get repository clone into the PRGuard sandbox using caching and link-copying.

    Args:
        repo_url: HTTPS clone URL (recommended).
        pr_number: Pull request number.
        repo_full_name: Optional full name like "owner/repo" to stabilize pr_id.

    Returns:
        RepoSandboxResult describing the sandbox path and computed metrics.
    """
    offline_mode = settings.prguard_offline_mode
    if not repo_url and not offline_mode:
        raise RepoSandboxError("Missing repo_url for cloning.")
    repo_full_name = repo_full_name or "repo"
    pr_id = _safe_pr_id(repo_full_name, pr_number)

    temp_root = SANDBOX_ROOT / pr_id
    temp_path = temp_root / uuid.uuid4().hex
    temp_path.parent.mkdir(parents=True, exist_ok=True)

    # Ensure clean workspace for this request only.
    if temp_path.exists():
        shutil.rmtree(temp_path, ignore_errors=True)

    if offline_mode:
        temp_path.mkdir(parents=True, exist_ok=True)
        return RepoSandboxResult(temp_path=temp_path, python_files_indexed=0, repo_size_bytes=0)

    _validate_repo_url(repo_url)

    # Retrieve from cache
    try:
        cache_dir = get_cached_repo(repo_full_name, repo_url)
    except Exception as exc:
        raise RepoSandboxError(f"Failed to retrieve repository from cache: {exc}") from exc

    # Copy files using hard links recursively to save disk space and clone instantly
    temp_path.mkdir(parents=True, exist_ok=True)
    try:
        if os.name != "nt":
            subprocess.run(
                ["cp", "-al", f"{cache_dir}/.", str(temp_path)],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        else:
            shutil.copytree(cache_dir, temp_path, copy_function=os.link, dirs_exist_ok=True)
    except Exception as exc:
        logger.warning("Failed to link cached repo, copying normally: %s", exc)
        try:
            shutil.copytree(cache_dir, temp_path, dirs_exist_ok=True)
        except Exception as copy_exc:
            raise RepoSandboxError(f"Failed to copy repository to sandbox: {copy_exc}") from copy_exc

    repo_size, py_count = _enforce_limits(temp_path)
    return RepoSandboxResult(temp_path=temp_path, python_files_indexed=py_count, repo_size_bytes=repo_size)


def cleanup_repository(temp_path: str | Path) -> None:
    """Delete sandbox directory after analysis (best-effort)."""
    p_resolved = Path(temp_path).resolve()
    if not p_resolved.exists():
        return
    sandbox_root = SANDBOX_ROOT.resolve()
    if sandbox_root not in p_resolved.parents and p_resolved != sandbox_root:
        # Safety: never delete outside sandbox root.
        raise RepoSandboxError(f"Refusing to delete non-sandbox path: {p_resolved}")
    shutil.rmtree(p_resolved, ignore_errors=True)


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
