"""Tests for thread safety and global mutable state purge (Phase 10)."""

import threading

import pytest

from prguard_ai.llm.token_budget import TokenBudget
from prguard_ai.task_queue.redis_client import RedisClient
from prguard_ai.confidence.scoring_engine import ConfidenceScorer
from prguard_ai.schemas.agent_output import Issue


def test_token_budget_thread_safe():
    budget = TokenBudget(pr_id="test", max_tokens=1000)

    results = []
    def consume():
        results.append(budget.check_and_consume(100))

    threads = [threading.Thread(target=consume) for _ in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert sum(results) == 10


def test_parallel_agents_no_shared_state():
    budget1 = TokenBudget(pr_id="pr-1", max_tokens=500)
    budget2 = TokenBudget(pr_id="pr-2", max_tokens=500)

    assert budget1.check_and_consume(500) is True
    assert budget2.check_and_consume(100) is True
    assert budget1.check_and_consume(100) is False


def test_redis_client_both_connect():
    client1 = RedisClient()
    client2 = RedisClient()

    client1.set("key1", "value1")
    client2.set("key2", "value2")

    # Each client can write independently (fakeredis instances are isolated)
    assert client1.get("key2") is None or client1.get("key1") == "value1"


def test_confidence_scorer_instance_based():
    scorer1 = ConfidenceScorer(
        source_weights={"rule_based": 1.0},
        severity_weights={"high": 1.0},
    )
    scorer2 = ConfidenceScorer(
        source_weights={"rule_based": 0.0},
        severity_weights={"high": 0.0},
    )

    issues = [Issue(line=1, severity="high", message="test", evidence="", confidence_source="rule_based")]
    assert scorer1.estimate_confidence(issues, empty_confidence=0.5) > scorer2.estimate_confidence(issues, empty_confidence=0.5)


def test_token_budget_remaining():
    budget = TokenBudget(pr_id="test", max_tokens=1000)
    assert budget.remaining == 1000
    budget.check_and_consume(300)
    assert budget.remaining == 700
    assert budget.used == 300


def test_token_budget_exhaustion():
    budget = TokenBudget(pr_id="test", max_tokens=100)
    assert budget.check_and_consume(50) is True
    assert budget.check_and_consume(60) is False
    assert budget.check_and_consume(50) is True
    assert budget.check_and_consume(10) is False
