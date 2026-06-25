import pytest
import time
from unittest.mock import MagicMock, patch

from prguard_ai.reliability.circuit_breaker import CircuitBreaker, CircuitBreakerError
from prguard_ai.llm.client import generate_analysis
from prguard_ai.agents.style_agent import analyze_style
from prguard_ai.agents.logic_agent import analyze_logic
from prguard_ai.agents.security_agent import analyze_security


def test_circuit_breaker_transitions():
    cb = CircuitBreaker(fail_max=3, reset_timeout=1.0)
    assert cb.state == "CLOSED"

    # Define a failing function
    def failing_call():
        raise ValueError("API error")

    # 1. First two failures
    with pytest.raises(CircuitBreakerError):
        cb.call(failing_call)
    assert cb.state == "CLOSED"
    assert cb.failure_count == 1

    with pytest.raises(CircuitBreakerError):
        cb.call(failing_call)
    assert cb.state == "CLOSED"
    assert cb.failure_count == 2

    # 2. Third failure trips the breaker to OPEN
    with pytest.raises(CircuitBreakerError):
        cb.call(failing_call)
    assert cb.state == "OPEN"
    assert cb.failure_count == 3

    # 3. Subsequent calls fail immediately without executing the function
    mock_func = MagicMock()
    with pytest.raises(CircuitBreakerError) as exc_info:
        cb.call(mock_func)
    assert "Circuit breaker is OPEN" in str(exc_info.value)
    assert not mock_func.called

    # 4. Wait for reset timeout and transition to HALF_OPEN
    time.sleep(1.1)
    
    # Define a successful function
    def success_call():
        return "success"

    # Call success in HALF_OPEN -> transitions to CLOSED
    res = cb.call(success_call)
    assert res == "success"
    assert cb.state == "CLOSED"
    assert cb.failure_count == 0


def test_circuit_breaker_budget_exclusion():
    cb = CircuitBreaker(fail_max=3, reset_timeout=60.0)

    # A budget exception should propagate but NOT increment failure count
    def budget_call():
        raise RuntimeError("Token budget for this PR has been exhausted.")

    with pytest.raises(RuntimeError) as exc_info:
        cb.call(budget_call)
    assert "Token budget" in str(exc_info.value)
    assert cb.state == "CLOSED"
    assert cb.failure_count == 0


def test_agents_fallback_on_circuit_breaker_error(monkeypatch):
    # Mock generate_analysis to raise CircuitBreakerError
    def mock_generate_analysis(*args, **kwargs):
        raise CircuitBreakerError("Circuit breaker is OPEN")

    monkeypatch.setattr("prguard_ai.agents.style_agent.generate_analysis", mock_generate_analysis)
    monkeypatch.setattr("prguard_ai.agents.logic_agent.generate_analysis", mock_generate_analysis)
    monkeypatch.setattr("prguard_ai.agents.security_agent.generate_analysis", mock_generate_analysis)

    diff = "diff --git a/foo.py b/foo.py\n+new line"

    # Test Style Agent
    style_out = analyze_style(diff)
    assert style_out.agent == "style"
    assert style_out.llm_skipped is True
    # Rule checks might still run or return findings, but LLM findings are skipped

    # Test Logic Agent
    logic_out = analyze_logic(diff)
    assert logic_out.agent == "logic"
    assert logic_out.llm_skipped is True

    # Test Security Agent
    security_out = analyze_security(diff)
    assert security_out.agent == "security"
    assert security_out.llm_skipped is True
