"""Redis-based sliding window rate limiting for PRGuard AI."""

from __future__ import annotations

import time
from typing import Final

from queue.redis_client import get_redis


_REPO_WINDOW_SECONDS: Final[int] = 60 * 60        # 1 hour
_REPO_MAX_EVENTS: Final[int] = 10

_INSTALL_WINDOW_SECONDS: Final[int] = 24 * 60 * 60  # 1 day
_INSTALL_MAX_EVENTS: Final[int] = 100


def _check_limit(key: str, window_seconds: int, max_events: int) -> bool:
    """Generic sliding-window limiter using a Redis sorted set."""
    now = int(time.time())
    r = get_redis()
    pipe = r.pipeline()
    # Drop entries outside the window, add current, then count.
    pipe.zremrangebyscore(key, 0, now - window_seconds)
    pipe.zadd(key, {str(now): now})
    pipe.zcard(key)
    pipe.expire(key, window_seconds)
    _, _, count, _ = pipe.execute()
    return int(count) <= max_events


def check_repo_limit(repo_name: str) -> bool:
    """Return True if the repository is within its hourly PR review limit."""
    key = f"prguard:rl:repo:{repo_name}"
    return _check_limit(key, _REPO_WINDOW_SECONDS, _REPO_MAX_EVENTS)


def check_installation_limit(installation_id: int) -> bool:
    """Return True if the installation is within its daily PR review limit."""
    key = f"prguard:rl:inst:{installation_id}"
    return _check_limit(key, _INSTALL_WINDOW_SECONDS, _INSTALL_MAX_EVENTS)


__all__ = ["check_repo_limit", "check_installation_limit"]

