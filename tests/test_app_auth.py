from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch
from prguard_ai.gh_client.app_auth import load_app_private_key, generate_jwt, get_installation_token


def test_load_app_private_key_empty():
    with patch("prguard_ai.gh_client.app_auth.settings") as mock_settings:
        mock_settings.github_app_private_key = ""
        with pytest.raises(RuntimeError, match="GITHUB_APP_PRIVATE_KEY is not configured"):
            load_app_private_key()


def test_load_app_private_key_direct_pem():
    with patch("prguard_ai.gh_client.app_auth.settings") as mock_settings:
        mock_settings.github_app_private_key = "---BEGIN PRIVATE KEY---"
        assert load_app_private_key() == "---BEGIN PRIVATE KEY---"


def test_load_app_private_key_path(tmp_path):
    pem_file = tmp_path / "key.pem"
    pem_file.write_text("file-pem-content", encoding="utf-8")
    
    with patch("prguard_ai.gh_client.app_auth.settings") as mock_settings:
        mock_settings.github_app_private_key = str(pem_file)
        assert load_app_private_key() == "file-pem-content"


def test_generate_jwt_missing_app_id():
    with patch("prguard_ai.gh_client.app_auth.settings") as mock_settings:
        mock_settings.github_app_id = ""
        with pytest.raises(RuntimeError, match="GITHUB_APP_ID is not configured"):
            generate_jwt()


@patch("jwt.encode")
def test_generate_jwt_success(mock_jwt_encode):
    mock_jwt_encode.return_value = "mocked-jwt-token"
    with patch("prguard_ai.gh_client.app_auth.settings") as mock_settings:
        mock_settings.github_app_id = "12345"
        mock_settings.github_app_private_key = "---BEGIN PRIVATE KEY---"
        
        jwt_token = generate_jwt(now=1000)
        assert jwt_token == "mocked-jwt-token"
        mock_jwt_encode.assert_called_once()


def test_get_installation_token_missing_id():
    with patch("prguard_ai.gh_client.app_auth.settings") as mock_settings:
        mock_settings.github_app_installation_id = ""
        with pytest.raises(RuntimeError, match="GITHUB_APP_INSTALLATION_ID is not configured"):
            get_installation_token()


@patch("prguard_ai.gh_client.app_auth.generate_jwt")
@patch("requests.post")
def test_get_installation_token_success(mock_post, mock_gen_jwt):
    mock_gen_jwt.return_value = "mocked-jwt"
    mock_resp = MagicMock()
    mock_resp.status_code = 201
    mock_resp.json.return_value = {"token": "installation-token-abc"}
    mock_post.return_value = mock_resp

    with patch("prguard_ai.gh_client.app_auth.settings") as mock_settings:
        mock_settings.github_app_installation_id = "999"
        
        token = get_installation_token()
        assert token == "installation-token-abc"
        mock_post.assert_called_once()


@patch("prguard_ai.gh_client.app_auth.generate_jwt")
@patch("requests.post")
def test_get_installation_token_failures(mock_post, mock_gen_jwt):
    mock_gen_jwt.return_value = "mocked-jwt"
    
    # Failure 1: status code not 201
    mock_resp = MagicMock()
    mock_resp.status_code = 403
    mock_resp.text = "Forbidden"
    mock_post.return_value = mock_resp

    with patch("prguard_ai.gh_client.app_auth.settings") as mock_settings:
        mock_settings.github_app_installation_id = "999"
        
        with pytest.raises(RuntimeError, match="Failed to obtain installation token"):
            get_installation_token()

    # Failure 2: response missing token key
    mock_resp = MagicMock()
    mock_resp.status_code = 201
    mock_resp.json.return_value = {}
    mock_post.return_value = mock_resp

    with patch("prguard_ai.gh_client.app_auth.settings") as mock_settings:
        mock_settings.github_app_installation_id = "999"
        
        with pytest.raises(RuntimeError, match="Installation token response did not include a token"):
            get_installation_token()
