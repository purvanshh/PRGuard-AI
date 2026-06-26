from __future__ import annotations

import datetime as dt
import pytest
from unittest.mock import MagicMock, patch
from prguard_ai.cost.budget_manager import add_usage, check_budget, _bucket_key


def test_add_usage_success():
    """Verify cost usage is stored and expires correctly in Redis."""
    mock_redis = MagicMock()
    with patch("prguard_ai.cost.budget_manager.get_redis", return_value=mock_redis):
        add_usage("owner/repo", 0.05)
        # Verify incrbyfloat and expireat are called
        today = dt.date.today()
        key = _bucket_key("owner/repo", today)
        mock_redis.incrbyfloat.assert_called_once_with(key, 0.05)
        mock_redis.expireat.assert_called_once()


def test_add_usage_zero_or_negative():
    """Verify zero or negative cost returns immediately without calling Redis."""
    mock_redis = MagicMock()
    with patch("prguard_ai.cost.budget_manager.get_redis", return_value=mock_redis):
        add_usage("owner/repo", 0.0)
        add_usage("owner/repo", -0.1)
        mock_redis.incrbyfloat.assert_not_called()


def test_add_usage_redis_error():
    """Verify add_usage catches Redis errors and degrades gracefully."""
    with patch("prguard_ai.cost.budget_manager.get_redis", side_effect=Exception("Redis dead")):
        # Should not raise exception
        add_usage("owner/repo", 0.1)


def test_check_budget_within():
    """Verify check_budget returns True if usage is under limit."""
    mock_redis = MagicMock()
    mock_redis.get.return_value = b"1.20"
    with patch("prguard_ai.cost.budget_manager.get_redis", return_value=mock_redis):
        assert check_budget("owner/repo") is True


def test_check_budget_exceeded():
    """Verify check_budget returns False if usage exceeds limit."""
    mock_redis = MagicMock()
    # Mock budget usage that exceeds _DAILY_LIMIT_USD (default 5.0)
    mock_redis.get.return_value = b"10.50"
    with patch("prguard_ai.cost.budget_manager.get_redis", return_value=mock_redis):
        assert check_budget("owner/repo") is False


def test_check_budget_none():
    """Verify check_budget returns True if key does not exist (None)."""
    mock_redis = MagicMock()
    mock_redis.get.return_value = None
    with patch("prguard_ai.cost.budget_manager.get_redis", return_value=mock_redis):
        assert check_budget("owner/repo") is True


def test_check_budget_malformed():
    """Verify check_budget handles malformed data gracefully."""
    mock_redis = MagicMock()
    mock_redis.get.return_value = b"not-a-float"
    with patch("prguard_ai.cost.budget_manager.get_redis", return_value=mock_redis):
        assert check_budget("owner/repo") is True


def test_check_budget_redis_error():
    """Verify check_budget returns True if Redis fails."""
    with patch("prguard_ai.cost.budget_manager.get_redis", side_effect=Exception("Redis dead")):
        assert check_budget("owner/repo") is True
