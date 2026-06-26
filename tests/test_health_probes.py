from __future__ import annotations

import shutil
import pytest
from unittest.mock import MagicMock, patch, AsyncMock
from prguard_ai.observability.health import (
    check_redis,
    check_postgres,
    check_llm,
    check_github,
    check_celery,
    check_chromadb,
    check_disk_space,
)


def test_check_redis_success():
    mock_redis = MagicMock()
    with patch("prguard_ai.observability.health.get_redis", return_value=mock_redis):
        assert check_redis() == "connected"
        mock_redis.ping.assert_called_once()


def test_check_redis_failure():
    with patch("prguard_ai.observability.health.get_redis", side_effect=Exception("Connection refused")):
        assert check_redis() == "disconnected"


@pytest.mark.anyio
async def test_check_postgres_success():
    mock_session = AsyncMock()
    mock_session.execute.return_value = None
    
    # We need to mock the context manager of async_session
    mock_session_maker = MagicMock()
    mock_session_maker.return_value.__aenter__.return_value = mock_session
    
    with patch("prguard_ai.observability.health.async_session", mock_session_maker):
        res = await check_postgres()
        assert res == "connected"


@pytest.mark.anyio
async def test_check_postgres_failure():
    mock_session_maker = MagicMock()
    mock_session_maker.return_value.__aenter__.side_effect = Exception("DB error")
    
    with patch("prguard_ai.observability.health.async_session", mock_session_maker):
        res = await check_postgres()
        assert res == "disconnected"


def test_check_llm():
    with patch("prguard_ai.llm.client.check_llm_health", return_value="healthy"):
        assert check_llm() == "healthy"


def test_check_github_success():
    mock_gh = MagicMock()
    mock_gh.get_rate_limit.return_value = None
    with patch("prguard_ai.gh_client.github_client._get_github_client", return_value=mock_gh):
        assert check_github() == "connected"


def test_check_github_failure():
    with patch("prguard_ai.gh_client.github_client._get_github_client", side_effect=Exception("Auth error")):
        assert check_github() == "disconnected"


def test_check_celery_eager():
    mock_celery = MagicMock()
    mock_celery.conf.task_always_eager = True
    with patch("prguard_ai.task_queue.celery_app.celery_app", mock_celery):
        assert check_celery() == "eager_mode"


def test_check_celery_active():
    mock_celery = MagicMock()
    mock_celery.conf.task_always_eager = False
    mock_inspector = MagicMock()
    mock_inspector.active.return_value = {"worker1": []}
    mock_celery.control.inspect.return_value = mock_inspector
    
    with patch("prguard_ai.task_queue.celery_app.celery_app", mock_celery):
        assert check_celery() == "active"


def test_check_celery_no_workers():
    mock_celery = MagicMock()
    mock_celery.conf.task_always_eager = False
    mock_inspector = MagicMock()
    mock_inspector.active.return_value = None
    mock_celery.control.inspect.return_value = mock_inspector
    
    with patch("prguard_ai.task_queue.celery_app.celery_app", mock_celery):
        assert check_celery() == "no_active_workers"


def test_check_celery_error():
    mock_celery = MagicMock()
    mock_celery.conf.task_always_eager = False
    mock_celery.control.inspect.side_effect = Exception("Celery unreachable")
    
    with patch("prguard_ai.task_queue.celery_app.celery_app", mock_celery):
        assert check_celery() == "disconnected"


def test_check_chromadb_success():
    with patch("prguard_ai.analysis.repo_indexer.retrieve_similar_code", return_value=["result"]):
        assert check_chromadb() == "healthy"


def test_check_chromadb_failure():
    with patch("prguard_ai.analysis.repo_indexer.retrieve_similar_code", side_effect=Exception("Chroma error")):
        assert check_chromadb() == "disconnected"


def test_check_disk_space_healthy():
    # Return (total, used, free)
    mock_usage = (100 * 1024**3, 90 * 1024**3, 10 * 1024**3)
    with patch("shutil.disk_usage", return_value=mock_usage):
        assert check_disk_space() == "healthy"


def test_check_disk_space_low():
    # Return (total, used, free) with <1 GB free
    mock_usage = (100 * 1024**3, 99.5 * 1024**3, 0.5 * 1024**3)
    with patch("shutil.disk_usage", return_value=mock_usage):
        assert check_disk_space().startswith("low_space")


def test_check_disk_space_error():
    with patch("shutil.disk_usage", side_effect=Exception("OS error")):
        assert check_disk_space() == "error"
