import pytest
from fastapi.testclient import TestClient
from unittest.mock import MagicMock, patch
from fastapi import status

from prguard_ai.gh_client.webhook_server import app
from prguard_ai.config.settings import settings


@pytest.fixture
def client():
    return TestClient(app)


def test_webhook_async_success(client, monkeypatch):
    # Mock signature verification
    monkeypatch.setattr("prguard_ai.gh_client.webhook_server.verify_github_signature", lambda *args, **kwargs: None)

    # Mock rate limiting
    monkeypatch.setattr("prguard_ai.gh_client.webhook_server.check_repo_limit", lambda *args: True)
    monkeypatch.setattr("prguard_ai.gh_client.webhook_server.check_installation_limit", lambda *args: True)

    # Mock idempotency check
    monkeypatch.setattr("prguard_ai.gh_client.webhook_server.is_pr_processing", lambda *args: False)
    monkeypatch.setattr("prguard_ai.gh_client.webhook_server.register_pr_processing", lambda *args: True)

    # Mock Celery chain and apply_async
    mock_apply_async = MagicMock()
    with patch("celery.chain") as mock_chain:
        mock_chain.return_value.apply_async = mock_apply_async

        # Make request to webhook
        headers = {
            "X-GitHub-Event": "pull_request",
            "X-GitHub-Delivery": "12345678-abcd-1234-abcd-1234567890ab",
            "X-GitHub-Timestamp": "1234567890",
        }
        # Disable timestamp checking for test since X-GitHub-Timestamp is old
        monkeypatch.setattr("time.time", lambda: 1234567890.0)

        payload = {
            "action": "opened",
            "number": 12,
            "repository": {
                "full_name": "owner/repo",
                "clone_url": "https://github.com/owner/repo.git",
            },
            "installation": {"id": 123},
        }

        response = client.post("/webhook", json=payload, headers=headers)

        assert response.status_code == status.HTTP_202_ACCEPTED
        assert response.json() == {"status": "accepted", "pr_id": "owner/repo#12"}
        assert mock_apply_async.called
