"""Per-repository LLM cost budgeting for PRGuard AI."""

from __future__ import annotations

import datetime as dt
from typing import Final

from queue.redis_client import get_redis


_DAILY_LIMIT_USD: Final[float] = 5.0


def _bucket_key(repo_name: str, day: dt.date) -> str:
    return f"prguard:budget:{repo_name}:{day.isoformat()}"


def add_usage(repo_name: str, cost_usd: float) -> None:
    """Increment the daily cost bucket for a repository."""
    if cost_usd <= 0:
        return
    today = dt.date.today()
    key = _bucket_key(repo_name, today)
    r = get_redis()
    r.incrbyfloat(key, float(cost_usd))
    # Ensure the bucket expires at the end of the day.
    expiry = dt.datetime.combine(today, dt.time.max)
    r.expireat(key, int(expiry.timestamp()))


def check_budget(repo_name: str) -> bool:
    """Return True if the repository is still within its daily cost budget."""
    today = dt.date.today()
    key = _bucket_key(repo_name, today)
    r = get_redis()
    raw = r.get(key)
    if raw is None:
        return True
    try:
        current = float(raw)
    except (TypeError, ValueError):
        current = 0.0
    return current <= _DAILY_LIMIT_USD


__all__ = ["add_usage", "check_budget", "_DAILY_LIMIT_USD"]

