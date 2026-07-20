import pytest
from fastapi.testclient import TestClient
from prguard_ai.gh_client.webhook_server import app
from prguard_ai.config.settings import settings

client = TestClient(app)


def test_settings_validation_and_aliases():
    # Verify defaults/env-loaded values are set correctly
    assert settings.max_files_per_pr == 50
    assert settings.global_concurrency_limit == 5
    assert settings.processing_ttl_seconds == 900
    assert len(settings.admin_token) >= 32


def test_config_endpoint_unauthorized():
    response = client.get("/config")
    assert response.status_code == 401

    response = client.get("/config", headers={"Authorization": "Bearer wrong-token"})
    assert response.status_code == 401


def test_config_endpoint_success():
    response = client.get("/config", headers={"Authorization": f"Bearer {settings.admin_token}"})
    assert response.status_code == 200
    data = response.json()

    # Assert sensitive keys are masked
    assert data["deepseek_api_key"] == "********"
    assert data["github_token"] == "********"
    assert data["github_webhook_secret"] == "********"
    assert data["admin_token"] == "********"

    # Assert database_url password is masked
    assert "postgres:********@" in data["database_url"]

    # Assert non-sensitive keys are exposed
    assert data["max_files_per_pr"] == 50
    assert data["global_concurrency_limit"] == 5
