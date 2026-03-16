"""GitHub App authentication utilities for PRGuard AI."""

from __future__ import annotations

import os
import time
from typing import Optional

import jwt
import requests


GITHUB_API_URL = "https://api.github.com"


def load_app_private_key() -> str:
    """
    Load the GitHub App private key.

    Supports either a PEM string in the environment or a filesystem path.
    """
    raw = os.getenv("GITHUB_APP_PRIVATE_KEY", "").strip()
    if not raw:
        raise RuntimeError("GITHUB_APP_PRIVATE_KEY is not configured.")

    if "BEGIN" in raw:
        return raw

    # Treat as path.
    with open(raw, "r", encoding="utf-8") as f:
        return f.read()


def generate_jwt(now: Optional[int] = None) -> str:
    """
    Generate a short-lived JWT for GitHub App authentication.
    """
    app_id = os.getenv("GITHUB_APP_ID")
    if not app_id:
        raise RuntimeError("GITHUB_APP_ID is not configured.")

    private_key = load_app_private_key()

    iat = int(now or time.time())
    payload = {
        "iat": iat,
        "exp": iat + 9 * 60,  # 9 minutes
        "iss": app_id,
    }
    encoded = jwt.encode(payload, private_key, algorithm="RS256")
    # PyJWT>=2 returns a string; older versions may return bytes.
    if isinstance(encoded, bytes):
        encoded = encoded.decode("utf-8")
    return encoded


def get_installation_token(installation_id: Optional[str] = None) -> str:
    """
    Exchange the app JWT for an installation access token.
    """
    installation_id = installation_id or os.getenv("GITHUB_APP_INSTALLATION_ID")
    if not installation_id:
        raise RuntimeError("GITHUB_APP_INSTALLATION_ID is not configured.")

    jwt_token = generate_jwt()
    url = f"{GITHUB_API_URL}/app/installations/{installation_id}/access_tokens"
    headers = {
        "Authorization": f"Bearer {jwt_token}",
        "Accept": "application/vnd.github+json",
    }
    resp = requests.post(url, headers=headers, timeout=10)
    if resp.status_code != 201:
        raise RuntimeError(
            f"Failed to obtain installation token (status={resp.status_code}): {resp.text}"
        )
    data = resp.json()
    token = data.get("token")
    if not token:
        raise RuntimeError("Installation token response did not include a token.")
    return token


__all__ = ["load_app_private_key", "generate_jwt", "get_installation_token"]

