import subprocess

import pytest
from fastapi import HTTPException

from prguard_ai.analysis import repo_cache
from prguard_ai.config.settings import Settings
from prguard_ai.gh_client.github_client import format_pr_review
from prguard_ai.gh_client.webhook_server import validate_webhook_payload
from prguard_ai.security.redaction import public_error_code, redact_secrets


def test_repo_full_name_rejects_path_traversal():
    with pytest.raises(ValueError):
        repo_cache.validate_repo_full_name("../owner/repo")


def test_clone_disables_git_hooks(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(repo_cache.settings, "repo_cache_dir", str(tmp_path))
    monkeypatch.setattr(repo_cache, "evict_lru_cache", lambda: None)

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        target = tmp_path / "owner__repo"
        (target / ".git").mkdir(parents=True, exist_ok=True)
        return None

    monkeypatch.setattr(subprocess, "run", fake_run)

    repo_cache.get_cached_repo("owner/repo", "https://github.com/owner/repo.git")

    assert any("--config" in cmd and "core.hooksPath=/dev/null" in cmd for cmd in calls)


def test_secret_redaction_masks_user_visible_text():
    assert "secret=***" in redact_secrets("secret=supersecretvalue123")
    review = format_pr_review(
        {
            "agent_outputs": [
                {
                    "agent": "security",
                    "issues": [
                        {
                            "severity": "high",
                            "line": 1,
                            "message": "leaked token=supersecretvalue123",
                        }
                    ],
                }
            ]
        }
    )
    assert "supersecretvalue123" not in review


def test_public_error_code_omits_exception_message():
    code = public_error_code(RuntimeError("database password leaked"))

    assert code == "PRGUARD_RUNTIMEERROR"
    assert "password" not in code.lower()


def test_admin_token_default_is_randomized():
    first = Settings(_env_file=None, PRGUARD_OFFLINE_MODE=True)
    second = Settings(_env_file=None, PRGUARD_OFFLINE_MODE=True)

    assert first.admin_token != second.admin_token
    assert len(first.admin_token) >= 32


def test_webhook_payload_validation_rejects_malformed_repo():
    with pytest.raises(HTTPException) as exc:
        validate_webhook_payload({"action": "opened", "number": 1, "repository": {"full_name": "../bad"}})

    assert exc.value.status_code == 400
