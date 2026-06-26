"""Persistent repository caching utilities for PRGuard AI.

Helps avoid full git clones on repeated PR reviews.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any, Dict

from prguard_ai.config.settings import settings

logger = logging.getLogger(__name__)


def _get_dir_size(path: Path) -> int:
    """Calculate total size of a directory in bytes."""
    total = 0
    try:
        for entry in os.scandir(path):
            if entry.is_symlink():
                continue
            if entry.is_file():
                total += entry.stat().st_size
            elif entry.is_dir():
                total += _get_dir_size(Path(entry.path))
    except OSError:
        pass
    return total


def _touch_last_accessed(repo_dir: Path) -> None:
    """Update last accessed timestamp for a repository cache."""
    try:
        last_accessed_file = repo_dir / ".last_accessed"
        last_accessed_file.write_text(str(time.time()), encoding="utf-8")
    except Exception as e:
        logger.warning("Failed to update access time for %s: %s", repo_dir, e)


def _get_last_accessed(repo_dir: Path) -> float:
    """Get last accessed timestamp for a repository cache."""
    try:
        last_accessed_file = repo_dir / ".last_accessed"
        if last_accessed_file.exists():
            return float(last_accessed_file.read_text(encoding="utf-8").strip())
    except Exception:
        pass
    # Fallback to directory mtime
    try:
        return repo_dir.stat().st_mtime
    except Exception:
        return 0.0


def evict_lru_cache() -> None:
    """Evict least recently used repository caches if overall size limit is exceeded."""
    cache_dir = Path(settings.repo_cache_dir).resolve()
    if not cache_dir.exists():
        return

    max_bytes = settings.repo_cache_max_size_gb * 1024 * 1024 * 1024
    total_bytes = _get_dir_size(cache_dir)
    if total_bytes <= max_bytes:
        return

    logger.info("Repo cache limit exceeded (%s bytes > %s bytes). Evicting...", total_bytes, max_bytes)

    # Gather all cached repos and their stats
    repos = []
    for p in cache_dir.iterdir():
        if p.is_dir():
            repos.append({
                "path": p,
                "size": _get_dir_size(p),
                "last_accessed": _get_last_accessed(p)
            })

    # Sort by last accessed timestamp (oldest first)
    repos.sort(key=lambda x: x["last_accessed"])

    for r in repos:
        if total_bytes <= max_bytes:
            break
        logger.info("Evicting cached repository: %s (Size: %s bytes)", r["path"].name, r["size"])
        try:
            shutil.rmtree(r["path"], ignore_errors=True)
            total_bytes -= r["size"]
        except Exception as e:
            logger.error("Failed to delete cache path %s: %s", r["path"], e)


def get_cached_repo(repo_full_name: str, repo_url: str) -> Path:
    """Get persistent shallow clone of a repository, keeping it up to date.

    Evicts old entries if cache size limits are exceeded.
    """
    cache_dir = Path(settings.repo_cache_dir).resolve()
    cache_dir.mkdir(parents=True, exist_ok=True)

    safe_repo_name = repo_full_name.replace("/", "__").replace("..", "_")
    repo_dir = cache_dir / safe_repo_name

    env = os.environ.copy()
    env.setdefault("GIT_TERMINAL_PROMPT", "0")

    if repo_dir.exists() and (repo_dir / ".git").exists():
        # Update existing cache
        logger.info("Updating cached repository: %s", repo_full_name)
        try:
            subprocess.run(
                ["git", "fetch", "--depth", "1", "origin"],
                cwd=str(repo_dir),
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                env=env,
            )
            # Find default branch to reset to
            subprocess.run(
                ["git", "reset", "--hard", "origin/HEAD"],
                cwd=str(repo_dir),
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                env=env,
            )
        except subprocess.CalledProcessError as exc:
            logger.warning("Failed to fetch updates, resetting cache: %s", exc)
            shutil.rmtree(repo_dir, ignore_errors=True)
            # Re-clone
            subprocess.run(
                ["git", "clone", "--depth", "1", repo_url, str(repo_dir)],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                env=env,
            )
    else:
        # Clone fresh cache
        logger.info("Cloning fresh repository into cache: %s", repo_full_name)
        shutil.rmtree(repo_dir, ignore_errors=True)
        try:
            subprocess.run(
                ["git", "clone", "--depth", "1", repo_url, str(repo_dir)],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                env=env,
            )
        except subprocess.CalledProcessError as exc:
            raise RuntimeError(f"Failed to clone repository: {repo_full_name}") from exc

    _touch_last_accessed(repo_dir)
    evict_lru_cache()
    return repo_dir


def get_cache_stats() -> Dict[str, Any]:
    """Return dictionary summarizing cache stats."""
    cache_dir = Path(settings.repo_cache_dir).resolve()
    if not cache_dir.exists():
        return {"path": str(cache_dir), "size_bytes": 0, "repos_count": 0}

    total_size = _get_dir_size(cache_dir)
    count = sum(1 for p in cache_dir.iterdir() if p.is_dir())
    return {
        "path": str(cache_dir),
        "size_bytes": total_size,
        "repos_count": count
    }


__all__ = ["get_cached_repo", "evict_lru_cache", "get_cache_stats"]
