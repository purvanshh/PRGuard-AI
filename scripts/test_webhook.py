"""Local testing tool to simulate a GitHub webhook."""

from __future__ import annotations

import json
from pathlib import Path

import requests


def main() -> None:
    fixtures_dir = Path(__file__).resolve().parent.parent / "fixtures"
    payload_path = fixtures_dir / "sample_pr_payload.json"
    if not payload_path.exists():
        raise SystemExit(f"Sample payload not found at {payload_path}")

    with payload_path.open("r", encoding="utf-8") as f:
        payload = json.load(f)

    url = "http://localhost:8000/webhook"
    headers = {
        "Content-Type": "application/json",
        "X-GitHub-Event": "pull_request",
        # For local testing you can run the server with signature verification disabled,
        # or adjust this script to compute a real HMAC.
        "X-Hub-Signature-256": "sha256=TEST_SIGNATURE",
    }

    resp = requests.post(url, headers=headers, data=json.dumps(payload))
    print("Status:", resp.status_code)
    print("Body:", resp.text)


if __name__ == "__main__":
    main()

