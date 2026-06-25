import pytest
from unittest.mock import MagicMock, patch
import redis

from prguard_ai.llm.client import (
    generate_analysis,
    TokenBudgetExceededError,
    _check_and_update_budget,
    _PR_TOKEN_USAGE,
)
from prguard_ai.config.settings import settings
from prguard_ai.agents.style_agent import analyze_style
from prguard_ai.agents.logic_agent import analyze_logic
from prguard_ai.agents.security_agent import analyze_security
from prguard_ai.schemas.agent_output import AgentOutput
from prguard_ai.analysis.diff_parser import parse_diff
from prguard_ai.task_queue.redis_client import get_redis


def test_token_budget_exceeded():
    # Patch get_redis to return a mock redis client
    mock_redis = MagicMock()
    # Mock pipe.get to return a value that exceeds the limit (e.g. 9000)
    mock_pipe = MagicMock()
    mock_pipe.get.return_value = b"9000"
    mock_redis.pipeline.return_value.__enter__.return_value = mock_pipe

    with patch("prguard_ai.llm.client.get_redis", return_value=mock_redis):
        with pytest.raises(TokenBudgetExceededError):
            _check_and_update_budget("test_pr_1", 100)


def test_redis_token_budget_tracking():
    mock_redis = MagicMock()
    mock_pipe = MagicMock()
    mock_pipe.get.return_value = b"1000"
    mock_redis.pipeline.return_value.__enter__.return_value = mock_pipe

    with patch("prguard_ai.llm.client.get_redis", return_value=mock_redis):
        _check_and_update_budget("test_pr_2", 500)
        # Verify it fetched key
        mock_pipe.get.assert_called_with("pr:test_pr_2:token_usage")
        # Verify incrby and expire were called
        mock_pipe.incrby.assert_called_with("pr:test_pr_2:token_usage", 500)
        mock_pipe.expire.assert_called_with("pr:test_pr_2:token_usage", 3600)


def test_redis_offline_fallback():
    # Force get_redis to raise an error
    with patch("prguard_ai.llm.client.get_redis", side_effect=Exception("Redis connection failed")):
        # Clear local dict for testing
        if "fallback_pr" in _PR_TOKEN_USAGE:
            del _PR_TOKEN_USAGE["fallback_pr"]

        # This should use in-memory fallback and succeed
        _check_and_update_budget("fallback_pr", 1000)
        assert _PR_TOKEN_USAGE["fallback_pr"] == 1000

        # Set usage to max to trigger budget exceeded
        _PR_TOKEN_USAGE["fallback_pr"] = settings.max_tokens_per_pr
        with pytest.raises(TokenBudgetExceededError):
            _check_and_update_budget("fallback_pr", 100)


def test_agents_fallback_on_budget_exceeded():
    diff_text = "diff --git a/file.css b/file.css\nindex 0000000..1111111\n--- a/file.css\n+++ b/file.css\n@@ -1,1 +1,1 @@\n-body { color: red; }\n+body { color: #ff0000; }\n"
    diff_py = "diff --git a/file.py b/file.py\nindex 0000000..1111111\n--- a/file.py\n+++ b/file.py\n@@ -1,1 +1,1 @@\n-def f(): pass\n+def f(): print('hi')\n"
    diff_sec = "diff --git a/file.py b/file.py\nindex 0000000..1111111\n--- a/file.py\n+++ b/file.py\n@@ -1,1 +1,1 @@\n-def f(): pass\n+def f(): eval('input')\n"

    # Mock generate_analysis to raise TokenBudgetExceededError
    with patch("prguard_ai.agents.style_agent.generate_analysis", side_effect=TokenBudgetExceededError("Budget exceeded")):
        out = analyze_style(diff_text, repo_metadata={"pr_id": "style_test_pr"})
        assert isinstance(out, AgentOutput)
        assert out.llm_skipped is True

    with patch("prguard_ai.agents.logic_agent.generate_analysis", side_effect=TokenBudgetExceededError("Budget exceeded")):
        out = analyze_logic(diff_py, repo_metadata={"pr_id": "logic_test_pr"})
        assert isinstance(out, AgentOutput)
        assert out.llm_skipped is True

    with patch("prguard_ai.agents.security_agent.generate_analysis", side_effect=TokenBudgetExceededError("Budget exceeded")):
        out = analyze_security(diff_sec, repo_metadata={"pr_id": "security_test_pr"})
        assert isinstance(out, AgentOutput)
        assert out.llm_skipped is True
