import os

import pytest

# Configure environment variables for testing before importing settings
os.environ["PRGUARD_TESTING"] = "true"
os.environ["REDIS_MODE"] = "memory"
os.environ["REDIS_FALLBACK_TO_MEMORY"] = "true"

# Fallback dummy credentials to pass settings validation during test collection
os.environ.setdefault("GITHUB_TOKEN", "dummy-github-token")
os.environ.setdefault("GITHUB_WEBHOOK_SECRET", "dummy-webhook-secret")
os.environ.setdefault("OPENAI_API_KEY", "dummy-openai-key")


@pytest.fixture
def mock_settings():
    from prguard_ai.config.settings import Settings
    return Settings(
        redis_url="redis://localhost:6379/15",
    )


@pytest.fixture
def mock_redis():
    from prguard_ai.task_queue.redis_client import RedisClient
    return RedisClient()


@pytest.fixture
def mock_token_budget():
    from prguard_ai.llm.token_budget import TokenBudget
    return TokenBudget(pr_id="test", max_tokens=10000)
