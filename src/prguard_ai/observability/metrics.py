"""Prometheus metrics for PRGuard AI."""

from __future__ import annotations

from prometheus_client import Counter, Gauge, Histogram, Summary


# ---------------------------------------------------------------------------
# Counters
# ---------------------------------------------------------------------------

TOTAL_PRS_PROCESSED = Counter(
    "prguard_prs_processed_total",
    "Total number of pull requests processed",
)

LLM_TOKENS_USED = Counter(
    "prguard_llm_tokens_total",
    "Total LLM tokens consumed",
    ["agent", "model"],
)

AGENT_ERRORS_TOTAL = Counter(
    "prguard_agent_errors_total",
    "Total number of agent task errors",
    ["agent"],
)

DEAD_LETTERED_TASKS = Counter(
    "prguard_dead_lettered_tasks_total",
    "Total number of tasks written to the dead-letter queue",
)

PROMPT_INJECTION_DETECTED = Counter(
    "prguard_prompt_injection_detected_total",
    "Total number of prompt injection attempts detected in diff text",
)

# ---------------------------------------------------------------------------
# Histograms
# ---------------------------------------------------------------------------

AGENT_EXECUTION_TIME = Histogram(
    "prguard_agent_execution_seconds",
    "Agent execution time in seconds",
    ["agent"],
)

END_TO_END_REVIEW_LATENCY = Histogram(
    "prguard_review_latency_seconds",
    "End-to-end latency from webhook receipt to final review",
    buckets=(30, 60, 120, 300, 600, 900, 1800),
)

# ---------------------------------------------------------------------------
# Summaries
# ---------------------------------------------------------------------------

REVIEW_CONFIDENCE = Summary(
    "prguard_review_confidence",
    "Distribution of final review confidence scores",
)

# ---------------------------------------------------------------------------
# Gauges
# ---------------------------------------------------------------------------

CIRCUIT_BREAKER_STATE = Gauge(
    "prguard_circuit_breaker_state",
    "Current state of the LLM circuit breaker: 0=CLOSED, 1=HALF_OPEN, 2=OPEN",
)

TOKEN_BUDGET_REMAINING = Gauge(
    "prguard_token_budget_remaining",
    "Estimated remaining token budget for the current day",
)

QUEUE_DEPTH = Gauge(
    "prguard_queue_depth",
    "Current Celery queue depth by queue name",
    ["queue"],
)


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------

_STATE_MAP = {"CLOSED": 0, "HALF_OPEN": 1, "OPEN": 2}


def record_circuit_state(state: str) -> None:
    """Update the circuit breaker state gauge.

    Args:
        state: One of ``"CLOSED"``, ``"HALF_OPEN"``, or ``"OPEN"``.
    """
    CIRCUIT_BREAKER_STATE.set(_STATE_MAP.get(state.upper(), 0))


def record_agent_error(agent: str) -> None:
    """Increment the agent error counter for *agent*."""
    AGENT_ERRORS_TOTAL.labels(agent=agent).inc()


def record_token_budget(remaining: float) -> None:
    """Set the remaining token budget gauge to *remaining*."""
    TOKEN_BUDGET_REMAINING.set(remaining)


def record_queue_depth(queue: str, depth: int) -> None:
    """Set current queue depth for a Celery queue."""
    QUEUE_DEPTH.labels(queue=queue).set(depth)


def record_review_latency(seconds: float) -> None:
    """Observe end-to-end review latency."""
    END_TO_END_REVIEW_LATENCY.observe(seconds)


__all__ = [
    "AGENT_ERRORS_TOTAL",
    "AGENT_EXECUTION_TIME",
    "CIRCUIT_BREAKER_STATE",
    "DEAD_LETTERED_TASKS",
    "END_TO_END_REVIEW_LATENCY",
    "LLM_TOKENS_USED",
    "QUEUE_DEPTH",
    "REVIEW_CONFIDENCE",
    "TOKEN_BUDGET_REMAINING",
    "TOTAL_PRS_PROCESSED",
    "record_circuit_state",
    "record_agent_error",
    "record_queue_depth",
    "record_review_latency",
    "record_token_budget",
]
