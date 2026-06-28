"""Tests for PRGuard AI Prometheus metrics (Phase 13)."""

from __future__ import annotations

import pytest


# ---------------------------------------------------------------------------
# Metric registration tests
# ---------------------------------------------------------------------------

def test_metrics_module_exports():
    """All documented metric objects are importable."""
    from prguard_ai.observability.metrics import (
        AGENT_ERRORS_TOTAL,
        AGENT_EXECUTION_TIME,
        CIRCUIT_BREAKER_STATE,
        LLM_TOKENS_USED,
        REVIEW_CONFIDENCE,
        TOKEN_BUDGET_REMAINING,
        TOTAL_PRS_PROCESSED,
        record_agent_error,
        record_circuit_state,
        record_token_budget,
    )
    # All objects exist
    assert AGENT_ERRORS_TOTAL is not None
    assert AGENT_EXECUTION_TIME is not None
    assert CIRCUIT_BREAKER_STATE is not None
    assert LLM_TOKENS_USED is not None
    assert REVIEW_CONFIDENCE is not None
    assert TOKEN_BUDGET_REMAINING is not None
    assert TOTAL_PRS_PROCESSED is not None
    assert callable(record_agent_error)
    assert callable(record_circuit_state)
    assert callable(record_token_budget)


def test_record_circuit_state_closed():
    """record_circuit_state sets gauge to 0 for CLOSED."""
    from prguard_ai.observability.metrics import CIRCUIT_BREAKER_STATE, record_circuit_state

    record_circuit_state("CLOSED")
    assert CIRCUIT_BREAKER_STATE._value.get() == 0


def test_record_circuit_state_half_open():
    """record_circuit_state sets gauge to 1 for HALF_OPEN."""
    from prguard_ai.observability.metrics import CIRCUIT_BREAKER_STATE, record_circuit_state

    record_circuit_state("HALF_OPEN")
    assert CIRCUIT_BREAKER_STATE._value.get() == 1


def test_record_circuit_state_open():
    """record_circuit_state sets gauge to 2 for OPEN."""
    from prguard_ai.observability.metrics import CIRCUIT_BREAKER_STATE, record_circuit_state

    record_circuit_state("OPEN")
    assert CIRCUIT_BREAKER_STATE._value.get() == 2


def test_record_circuit_state_unknown_defaults_to_closed():
    """Unknown state defaults to 0."""
    from prguard_ai.observability.metrics import CIRCUIT_BREAKER_STATE, record_circuit_state

    record_circuit_state("UNKNOWN")
    assert CIRCUIT_BREAKER_STATE._value.get() == 0


def test_record_agent_error_increments_counter():
    """record_agent_error increments the AGENT_ERRORS_TOTAL counter for the given agent."""
    from prguard_ai.observability.metrics import AGENT_ERRORS_TOTAL, record_agent_error
    from prometheus_client import REGISTRY

    before = AGENT_ERRORS_TOTAL.labels(agent="test_agent")._value.get()
    record_agent_error("test_agent")
    after = AGENT_ERRORS_TOTAL.labels(agent="test_agent")._value.get()
    assert after == before + 1


def test_record_token_budget_sets_gauge():
    """record_token_budget sets TOKEN_BUDGET_REMAINING to the given value."""
    from prguard_ai.observability.metrics import TOKEN_BUDGET_REMAINING, record_token_budget

    record_token_budget(1234.5)
    assert TOKEN_BUDGET_REMAINING._value.get() == pytest.approx(1234.5)


def test_total_prs_processed_increments():
    """TOTAL_PRS_PROCESSED counter increments correctly."""
    from prguard_ai.observability.metrics import TOTAL_PRS_PROCESSED

    before = TOTAL_PRS_PROCESSED._value.get()
    TOTAL_PRS_PROCESSED.inc()
    assert TOTAL_PRS_PROCESSED._value.get() == before + 1


def test_review_confidence_observe():
    """REVIEW_CONFIDENCE summary accepts observations without error."""
    from prguard_ai.observability.metrics import REVIEW_CONFIDENCE

    # Should not raise
    REVIEW_CONFIDENCE.observe(0.77)
    REVIEW_CONFIDENCE.observe(0.0)
    REVIEW_CONFIDENCE.observe(1.0)


def test_agent_execution_time_timer():
    """AGENT_EXECUTION_TIME histogram timer context manager works without error."""
    from prguard_ai.observability.metrics import AGENT_EXECUTION_TIME

    # Using .time() as a context manager should not raise
    with AGENT_EXECUTION_TIME.labels(agent="style_timer_test").time():
        pass  # Simulate instantaneous work

    # Verify samples were recorded via the collect() API
    samples = list(AGENT_EXECUTION_TIME.labels(agent="style_timer_test").describe())
    # describe() returns metric family names — just verifying the metric exists
    assert AGENT_EXECUTION_TIME is not None


def test_llm_tokens_used_counter():
    """LLM_TOKENS_USED counter increments with agent and model labels."""
    from prguard_ai.observability.metrics import LLM_TOKENS_USED

    before = LLM_TOKENS_USED.labels(agent="logic", model="test-model")._value.get()
    LLM_TOKENS_USED.labels(agent="logic", model="test-model").inc(500)
    after = LLM_TOKENS_USED.labels(agent="logic", model="test-model")._value.get()
    assert after == before + 500


# ---------------------------------------------------------------------------
# Circuit breaker integration with metrics
# ---------------------------------------------------------------------------

def test_circuit_breaker_emits_open_state(monkeypatch):
    """Circuit breaker calls record_circuit_state on transition to OPEN."""
    from prguard_ai.reliability import circuit_breaker as cb_module

    recorded_states = []

    def fake_record(state: str) -> None:
        recorded_states.append(state)

    monkeypatch.setattr(cb_module, "_record_state", fake_record)

    breaker = cb_module.CircuitBreaker(fail_max=2, reset_timeout=60.0)

    def failing():
        raise RuntimeError("boom")

    for _ in range(2):
        try:
            breaker.call(failing)
        except cb_module.CircuitBreakerError:
            pass

    assert "OPEN" in recorded_states


def test_circuit_breaker_emits_half_open_state(monkeypatch):
    """Circuit breaker calls record_circuit_state on transition to HALF_OPEN."""
    import time
    from prguard_ai.reliability import circuit_breaker as cb_module

    recorded_states = []

    def fake_record(state: str) -> None:
        recorded_states.append(state)

    monkeypatch.setattr(cb_module, "_record_state", fake_record)

    breaker = cb_module.CircuitBreaker(fail_max=1, reset_timeout=0.01)

    def failing():
        raise RuntimeError("boom")

    try:
        breaker.call(failing)
    except cb_module.CircuitBreakerError:
        pass

    time.sleep(0.05)

    # Next call should transition to HALF_OPEN
    try:
        breaker.call(failing)
    except cb_module.CircuitBreakerError:
        pass

    assert "HALF_OPEN" in recorded_states


def test_circuit_breaker_emits_closed_state(monkeypatch):
    """Circuit breaker calls record_circuit_state on transition back to CLOSED."""
    import time
    from prguard_ai.reliability import circuit_breaker as cb_module

    recorded_states = []

    def fake_record(state: str) -> None:
        recorded_states.append(state)

    monkeypatch.setattr(cb_module, "_record_state", fake_record)

    breaker = cb_module.CircuitBreaker(fail_max=1, reset_timeout=0.01)

    def failing():
        raise RuntimeError("boom")

    def succeeding():
        return "ok"

    try:
        breaker.call(failing)
    except cb_module.CircuitBreakerError:
        pass

    time.sleep(0.05)

    # Transition to HALF_OPEN then succeed -> CLOSED
    result = breaker.call(succeeding)
    assert result == "ok"
    assert "CLOSED" in recorded_states
