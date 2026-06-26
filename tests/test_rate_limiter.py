from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch
from prguard_ai.security.rate_limiter import check_repo_limit, check_installation_limit


def test_rate_limiter_under_limit():
    """Verify that rate limiter returns True when events are within limits."""
    mock_redis = MagicMock()
    mock_pipe = MagicMock()
    mock_pipe.execute.return_value = (None, None, 5, None)  # event count = 5
    mock_redis.pipeline.return_value = mock_pipe

    with patch("prguard_ai.security.rate_limiter.get_redis", return_value=mock_redis):
        assert check_repo_limit("owner/repo") is True
        assert check_installation_limit(12345) is True


def test_rate_limiter_over_limit():
    """Verify that rate limiter returns False when event count exceeds limits."""
    mock_redis = MagicMock()
    mock_pipe = MagicMock()
    mock_pipe.execute.return_value = (None, None, 150, None)  # count exceeds limits
    mock_redis.pipeline.return_value = mock_pipe

    with patch("prguard_ai.security.rate_limiter.get_redis", return_value=mock_redis):
        assert check_repo_limit("owner/repo") is False
        assert check_installation_limit(12345) is False


def test_rate_limiter_redis_error_fallback():
    """Verify rate limiter fails open (returns True) if Redis raises an error."""
    with patch("prguard_ai.security.rate_limiter.get_redis", side_effect=Exception("Redis error")):
        assert check_repo_limit("owner/repo") is True
        assert check_installation_limit(12345) is True
