import pytest
from fastapi.testclient import TestClient
from unittest.mock import MagicMock, patch, AsyncMock
from fastapi import status

from prguard_ai.gh_client.webhook_server import app


@pytest.fixture
def client():
    return TestClient(app)


@pytest.mark.anyio
@patch("prguard_ai.analysis.repo_cache.get_cache_stats")
@patch("prguard_ai.observability.health.check_redis")
@patch("prguard_ai.observability.health.check_postgres")
@patch("prguard_ai.observability.health.check_llm")
@patch("prguard_ai.observability.health.check_github")
@patch("prguard_ai.observability.health.check_celery")
@patch("prguard_ai.observability.health.check_chromadb")
@patch("prguard_ai.observability.health.check_disk_space")
async def test_get_health_status_ok(
    mock_disk, mock_chroma, mock_celery, mock_github, mock_llm, mock_postgres, mock_redis, mock_cache_stats
):
    mock_redis.return_value = "connected"
    mock_postgres.return_value = "connected"
    mock_llm.return_value = "connected"
    mock_github.return_value = "connected"
    mock_celery.return_value = "active"
    mock_chroma.return_value = "healthy"
    mock_disk.return_value = "healthy"
    mock_cache_stats.return_value = {"path": ".repo_cache", "size_bytes": 100, "repos_count": 1}

    from prguard_ai.observability.health import get_health_status

    status_data = await get_health_status()
    assert status_data["status"] == "ok"
    assert status_data["critical"]["redis"] == "connected"
    assert status_data["critical"]["database"] == "connected"
    assert status_data["critical"]["llm"] == "connected"
    assert status_data["non_critical"]["celery"] == "active"
    assert status_data["cache_stats"] == {"path": ".repo_cache", "size_bytes": 100, "repos_count": 1}


@pytest.mark.anyio
@patch("prguard_ai.analysis.repo_cache.get_cache_stats")
@patch("prguard_ai.observability.health.check_redis")
@patch("prguard_ai.observability.health.check_postgres")
@patch("prguard_ai.observability.health.check_llm")
@patch("prguard_ai.observability.health.check_github")
@patch("prguard_ai.observability.health.check_celery")
@patch("prguard_ai.observability.health.check_chromadb")
@patch("prguard_ai.observability.health.check_disk_space")
async def test_get_health_status_unhealthy_critical(
    mock_disk, mock_chroma, mock_celery, mock_github, mock_llm, mock_postgres, mock_redis, mock_cache_stats
):
    mock_redis.return_value = "disconnected"  # Critical component down
    mock_postgres.return_value = "connected"
    mock_llm.return_value = "connected"
    mock_github.return_value = "connected"
    mock_celery.return_value = "active"
    mock_chroma.return_value = "healthy"
    mock_disk.return_value = "healthy"
    mock_cache_stats.return_value = {"path": ".repo_cache", "size_bytes": 0, "repos_count": 0}

    from prguard_ai.observability.health import get_health_status

    status_data = await get_health_status()
    assert status_data["status"] == "unhealthy"


@pytest.mark.anyio
@patch("prguard_ai.analysis.repo_cache.get_cache_stats")
@patch("prguard_ai.observability.health.check_redis")
@patch("prguard_ai.observability.health.check_postgres")
@patch("prguard_ai.observability.health.check_llm")
@patch("prguard_ai.observability.health.check_github")
@patch("prguard_ai.observability.health.check_celery")
@patch("prguard_ai.observability.health.check_chromadb")
@patch("prguard_ai.observability.health.check_disk_space")
async def test_get_health_status_degraded_non_critical(
    mock_disk, mock_chroma, mock_celery, mock_github, mock_llm, mock_postgres, mock_redis, mock_cache_stats
):
    mock_redis.return_value = "connected"
    mock_postgres.return_value = "connected"
    mock_llm.return_value = "connected"
    mock_github.return_value = "connected"
    mock_celery.return_value = "no_active_workers"  # Non-critical issue
    mock_chroma.return_value = "healthy"
    mock_disk.return_value = "healthy"
    mock_cache_stats.return_value = {"path": ".repo_cache", "size_bytes": 0, "repos_count": 0}

    from prguard_ai.observability.health import get_health_status

    status_data = await get_health_status()
    assert status_data["status"] == "degraded"


def test_health_endpoints_responses(client):
    # Test Liveness endpoint
    response = client.get("/health/live")
    assert response.status_code == status.HTTP_200_OK
    assert response.json() == {"status": "ok"}

    # Test Health and Readiness under healthy status
    with patch("prguard_ai.observability.health.get_health_status", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = {
            "status": "ok",
            "critical": {"redis": "connected", "database": "connected", "llm": "connected"},
            "non_critical": {"github": "connected", "celery": "active", "chromadb": "healthy", "disk": "healthy"}
        }

        response = client.get("/health")
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["status"] == "ok"

        response = client.get("/health/ready")
        assert response.status_code == status.HTTP_200_OK
        assert response.json() == {"status": "ok"}

    # Test Health and Readiness under unhealthy status (503 response)
    with patch("prguard_ai.observability.health.get_health_status", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = {
            "status": "unhealthy",
            "critical": {"redis": "disconnected", "database": "connected", "llm": "connected"},
            "non_critical": {"github": "connected", "celery": "active", "chromadb": "healthy", "disk": "healthy"}
        }

        response = client.get("/health")
        assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
        assert response.json()["status"] == "unhealthy"

        response = client.get("/health/ready")
        assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
        assert response.json() == {"status": "unhealthy"}
