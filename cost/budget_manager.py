"""Per-repository LLM cost budgeting for PRGuard AI."""

from __future__ import annotations

import datetime as dt
from typing import Final

from task_queue.redis_client import RedisClientError, get_redis


_DAILY_LIMIT_USD: Final[float] = 5.0


def _bucket_key(repo_name: str, day: dt.date) -> str:
    return f"prguard:budget:{repo_name}:{day.isoformat()}"


def add_usage(repo_name: str, cost_usd: float) -> None:
    """Increment the daily cost bucket for a repository."""
    if cost_usd <= 0:
        return
    today = dt.date.today()
    key = _bucket_key(repo_name, today)
    try:
        r = get_redis()
        r.incrbyfloat(key, float(cost_usd))
        # Ensure the bucket expires at the end of the day.
        expiry = dt.datetime.combine(today, dt.time.max)
        r.expireat(key, int(expiry.timestamp()))
    except (RedisClientError, Exception):
        # If Redis is unavailable, skip cost tracking rather than failing the request.
        return


def check_budget(repo_name: str) -> bool:
    """Return True if the repository is still within its daily cost budget.

    If Redis is unavailable, we treat the budget as not exceeded to avoid
    hard-failing reviews due to metering issues.
    """
    today = dt.date.today()
    key = _bucket_key(repo_name, today)
    try:
        r = get_redis()
        raw = r.get(key)
    except (RedisClientError, Exception):
        return True
    if raw is None:
        return True
    try:
        current = float(raw)
    except (TypeError, ValueError):
        current = 0.0
    return current <= _DAILY_LIMIT_USD


__all__ = ["add_usage", "check_budget", "_DAILY_LIMIT_USD"]

