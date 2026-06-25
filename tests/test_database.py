import pytest
import json
from unittest.mock import AsyncMock, patch, MagicMock

from prguard_ai.observability.logging import log_agent_execution, log_llm_usage, fetch_pr_logs
from prguard_ai.db.models import AgentLog, LLMUsage


@pytest.mark.anyio
async def test_log_agent_execution():
    mock_session = AsyncMock()
    mock_session_context = MagicMock()
    # async_session() returns the context manager, whose __aenter__ returns mock_session
    mock_session_context.return_value.__aenter__.return_value = mock_session
    
    with patch("prguard_ai.observability.logging.async_session", mock_session_context):
        mock_begin = MagicMock()
        mock_begin.__aenter__ = AsyncMock()
        mock_begin.__aexit__ = AsyncMock()
        mock_session.begin = MagicMock(return_value=mock_begin)
        
        await log_agent_execution(
            pr_id="owner/repo#1",
            agent="style",
            started_at=100.0,
            finished_at=102.5,
            output={"confidence": 0.85, "issues": []},
            token_usage=150,
            agent_order=1,
        )
        
        # Verify that session.add was called
        assert mock_session.add.called
        added_log = mock_session.add.call_args[0][0]
        assert isinstance(added_log, AgentLog)
        assert added_log.pr_id == "owner/repo#1"
        assert added_log.agent == "style"
        assert added_log.started_at == 100.0
        assert added_log.finished_at == 102.5
        assert added_log.confidence == 0.85
        assert added_log.token_usage == 150
        assert added_log.execution_duration == 2.5
        assert added_log.agent_order == 1


@pytest.mark.anyio
async def test_log_llm_usage():
    mock_session = AsyncMock()
    mock_session_context = MagicMock()
    mock_session_context.return_value.__aenter__.return_value = mock_session
    
    with patch("prguard_ai.observability.logging.async_session", mock_session_context):
        mock_begin = MagicMock()
        mock_begin.__aenter__ = AsyncMock()
        mock_begin.__aexit__ = AsyncMock()
        mock_session.begin = MagicMock(return_value=mock_begin)

        await log_llm_usage(
            pr_id="owner/repo#1",
            agent="security",
            model="gpt-4o",
            prompt_tokens=100,
            completion_tokens=50,
            estimated_cost_usd=0.00125,
        )
        
        # Verify that session.add was called
        assert mock_session.add.called
        added_usage = mock_session.add.call_args[0][0]
        assert isinstance(added_usage, LLMUsage)
        assert added_usage.pr_id == "owner/repo#1"
        assert added_usage.agent == "security"
        assert added_usage.model == "gpt-4o"
        assert added_usage.prompt_tokens == 100
        assert added_usage.completion_tokens == 50
        assert added_usage.estimated_cost_usd == 0.00125


@pytest.mark.anyio
async def test_fetch_pr_logs():
    mock_session = AsyncMock()
    mock_session_context = MagicMock()
    mock_session_context.return_value.__aenter__.return_value = mock_session
    
    # Mocking rows returned by execution
    mock_log = AgentLog(
        pr_id="owner/repo#1",
        agent="style",
        started_at=100.0,
        finished_at=102.5,
        confidence=0.85,
        token_usage=150,
        execution_duration=2.5,
        agent_order=1,
        payload='{"confidence": 0.85, "issues": []}',
    )
    
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = [mock_log]
    mock_session.execute = AsyncMock(return_value=mock_result)
    
    with patch("prguard_ai.observability.logging.async_session", mock_session_context):
        logs = await fetch_pr_logs("owner/repo#1")
        
        assert len(logs) == 1
        assert logs[0]["agent"] == "style"
        assert logs[0]["started_at"] == 100.0
        assert logs[0]["finished_at"] == 102.5
        assert logs[0]["confidence"] == 0.85
        assert logs[0]["token_usage"] == 150
        assert logs[0]["execution_duration"] == 2.5
        assert logs[0]["agent_order"] == 1
        assert logs[0]["output"] == {"confidence": 0.85, "issues": []}
