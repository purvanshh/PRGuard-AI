from __future__ import annotations

import os
import shutil
import subprocess
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from prguard_ai.config.settings import settings
from prguard_ai.analysis.repo_cache import get_cached_repo, evict_lru_cache, get_cache_stats, _get_dir_size
from prguard_ai.analysis.repo_sandbox import clone_repository, cleanup_repository, RepoSandboxError


@pytest.fixture
def temp_cache_dir(tmp_path):
    orig_dir = settings.repo_cache_dir
    settings.repo_cache_dir = str(tmp_path / "cache")
    yield tmp_path / "cache"
    settings.repo_cache_dir = orig_dir


def test_get_cache_stats_empty(temp_cache_dir):
    stats = get_cache_stats()
    assert stats["repos_count"] == 0
    assert stats["size_bytes"] == 0
    assert stats["path"] == str(temp_cache_dir)


def test_get_cache_stats_with_repos(temp_cache_dir):
    repo1 = temp_cache_dir / "owner__repo1"
    repo1.mkdir(parents=True)
    (repo1 / "file.txt").write_text("hello", encoding="utf-8")

    repo2 = temp_cache_dir / "owner__repo2"
    repo2.mkdir(parents=True)
    (repo2 / "file2.txt").write_text("world!", encoding="utf-8")

    stats = get_cache_stats()
    assert stats["repos_count"] == 2
    assert stats["size_bytes"] == 11  # "hello" is 5, "world!" is 6
    assert stats["path"] == str(temp_cache_dir)


@patch("subprocess.run")
def test_get_cached_repo_fresh(mock_run, temp_cache_dir):
    def create_dir_side_effect(*args, **kwargs):
        dest = args[0][-1]
        Path(dest).mkdir(parents=True, exist_ok=True)
        return MagicMock(returncode=0)

    mock_run.side_effect = create_dir_side_effect

    repo_dir = get_cached_repo("owner/repo", "https://github.com/owner/repo.git")

    assert repo_dir.exists()
    assert repo_dir.name == "owner__repo"
    assert (repo_dir / ".last_accessed").exists()

    # Check git clone was called
    mock_run.assert_called_once()
    args = mock_run.call_args[0][0]
    assert "clone" in args
    assert "--depth" in args
    assert "https://github.com/owner/repo.git" in args


@patch("subprocess.run")
def test_get_cached_repo_update_success(mock_run, temp_cache_dir):
    # Setup pre-existing repo cache directory with .git
    repo_dir = temp_cache_dir / "owner__repo"
    repo_dir.mkdir(parents=True)
    (repo_dir / ".git").mkdir()

    mock_run.return_value = MagicMock(returncode=0)

    get_cached_repo("owner/repo", "https://github.com/owner/repo.git")

    # Should call git fetch and reset
    assert mock_run.call_count == 2
    calls = [c[0][0] for c in mock_run.call_args_list]
    assert any("fetch" in args for args in calls)
    assert any("reset" in args for args in calls)


@patch("subprocess.run")
def test_get_cached_repo_update_fail_fallback_clone(mock_run, temp_cache_dir):
    # Setup pre-existing repo cache directory with .git
    repo_dir = temp_cache_dir / "owner__repo"
    repo_dir.mkdir(parents=True)
    (repo_dir / ".git").mkdir()
    (repo_dir / "old_file.txt").write_text("old", encoding="utf-8")

    # First fetch fails, then clone succeeds
    mock_run.side_effect = [
        subprocess.CalledProcessError(1, "git fetch"),
        MagicMock(returncode=0)
    ]

    get_cached_repo("owner/repo", "https://github.com/owner/repo.git")

    # Old files should be removed by re-cloning fallback
    assert not (repo_dir / "old_file.txt").exists()
    assert mock_run.call_count == 2


def test_evict_lru_cache(temp_cache_dir):
    # Set limit to something very small (e.g. 0.000001 GB ~ 1000 bytes)
    orig_limit = settings.repo_cache_max_size_gb
    settings.repo_cache_max_size_gb = 0.000001

    try:
        # Create three directories
        repo1 = temp_cache_dir / "repo1"
        repo1.mkdir(parents=True)
        (repo1 / "dummy.txt").write_text("x" * 600, encoding="utf-8") # 600 bytes
        (repo1 / ".last_accessed").write_text(str(time.time() - 100), encoding="utf-8")

        repo2 = temp_cache_dir / "repo2"
        repo2.mkdir(parents=True)
        (repo2 / "dummy.txt").write_text("y" * 600, encoding="utf-8") # 600 bytes
        (repo2 / ".last_accessed").write_text(str(time.time() - 200), encoding="utf-8") # Oldest

        repo3 = temp_cache_dir / "repo3"
        repo3.mkdir(parents=True)
        (repo3 / "dummy.txt").write_text("z" * 100, encoding="utf-8") # 100 bytes
        (repo3 / ".last_accessed").write_text(str(time.time()), encoding="utf-8") # Newest

        # Current total size = ~1300 bytes > 1000 bytes.
        # Calling evict_lru_cache should evict repo2 (oldest) first.
        evict_lru_cache()

        assert repo1.exists()
        assert repo3.exists()
        assert not repo2.exists()

    finally:
        settings.repo_cache_max_size_gb = orig_limit


@patch("prguard_ai.analysis.repo_sandbox.get_cached_repo")
def test_clone_repository_sandbox(mock_get_cached, tmp_path, temp_cache_dir):
    # Mock cached repo directory
    cached_repo = tmp_path / "mock_cached"
    cached_repo.mkdir()
    (cached_repo / "main.py").write_text("print('hello')", encoding="utf-8")
    mock_get_cached.return_value = cached_repo

    with patch("prguard_ai.analysis.repo_sandbox.SANDBOX_ROOT", tmp_path / "sandbox"):
        res = clone_repository("https://github.com/owner/repo", 42, "owner/repo")
        assert res.temp_path.exists()
        assert (res.temp_path / "main.py").read_text(encoding="utf-8") == "print('hello')"
        assert res.python_files_indexed == 1
        assert res.repo_size_bytes > 0

        # Verify hard links if on Unix
        if os.name != "nt":
            # Inodes should be identical for hard links
            assert os.stat(cached_repo / "main.py").st_ino == os.stat(res.temp_path / "main.py").st_ino

        cleanup_repository(res.temp_path)
        assert not res.temp_path.exists()


@patch("prguard_ai.analysis.repo_sandbox.get_cached_repo")
def test_clone_repository_size_limits_exceeded(mock_get_cached, tmp_path):
    cached_repo = tmp_path / "mock_cached"
    cached_repo.mkdir()
    # Write a file exceeding 2MB (limit is 2MB)
    large_file = cached_repo / "large.py"
    large_file.write_text(" " * (3 * 1024 * 1024), encoding="utf-8")
    mock_get_cached.return_value = cached_repo

    with patch("prguard_ai.analysis.repo_sandbox.SANDBOX_ROOT", tmp_path / "sandbox"):
        with pytest.raises(RepoSandboxError, match="File too large"):
            clone_repository("https://github.com/owner/repo", 42, "owner/repo")
