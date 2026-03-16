"""Prometheus metrics for PRGuard AI."""

from __future__ import annotations

from prometheus_client import Counter, Histogram, Summary


TOTAL_PRS_PROCESSED = Counter(
    "prguard_prs_processed_total",
    "Total number of pull requests processed",
)

AGENT_EXECUTION_TIME = Histogram(
    "prguard_agent_execution_seconds",
    "Agent execution time in seconds",
    ["agent"],
)

LLM_TOKENS_USED = Counter(
    "prguard_llm_tokens_total",
    "Total LLM tokens used",
    ["agent", "model"],
)

REVIEW_CONFIDENCE = Summary(
    "prguard_review_confidence",
    "Distribution of final review confidence scores",
)


__all__ = [
    "TOTAL_PRS_PROCESSED",
    "AGENT_EXECUTION_TIME",
    "LLM_TOKENS_USED",
    "REVIEW_CONFIDENCE",
]

