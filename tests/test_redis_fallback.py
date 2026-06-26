from __future__ import annotations

import pytest
from unittest.mock import patch, MagicMock
from prguard_ai.config.settings import Settings
from prguard_ai.task_queue.redis_client import get_redis, RedisClientError


def test_redis_fallback_disabled_by_default():
    """Verify that settings default for redis_fallback_to_memory is False."""
    assert Settings.model_fields["redis_fallback_to_memory"].default is False


def test_redis_fallback_fails_fast_when_false():
    """Verify get_redis raises RedisClientError when connection fails and fallback_to_memory is False."""
    # Force settings.redis_fallback_to_memory to be False for this test
    with patch("prguard_ai.task_queue.redis_client.settings") as mock_settings:
        mock_settings.redis_fallback_to_memory = False
        mock_settings.redis_connect_retries = 1
        mock_settings.redis_mode = "single"
        mock_settings.redis_url = "redis://nonexistent:6379"

        # Force a fresh client build by patching the cached client singleton to None
        with patch("prguard_ai.task_queue.redis_client._CLIENT", None):
            with pytest.raises(RedisClientError, match="Failed to connect to Redis"):
                get_redis()
