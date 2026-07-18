"""Redis-based sliding window rate limiting for PRGuard AI."""

from __future__ import annotations

import time
from typing import Final

from prguard_ai.task_queue.redis_client import RedisClientError, get_redis


_REPO_WINDOW_SECONDS: Final[int] = 60 * 60        # 1 hour
_REPO_MAX_EVENTS: Final[int] = 10

_INSTALL_WINDOW_SECONDS: Final[int] = 24 * 60 * 60  # 1 day
_INSTALL_MAX_EVENTS: Final[int] = 100
_MODEL_WINDOW_SECONDS: Final[int] = 60
_MODEL_MAX_EVENTS: Final[int] = 120


def _check_limit(key: str, window_seconds: int, max_events: int) -> bool:
    """Generic sliding-window limiter using a Redis sorted set.

    If Redis is unavailable, we treat the limit as not exceeded so that
    availability is preferred over strict rate enforcement.
    """
    now = int(time.time())
    try:
        r = get_redis()
        pipe = r.pipeline()
        # Drop entries outside the window, add current, then count.
        pipe.zremrangebyscore(key, 0, now - window_seconds)
        pipe.zadd(key, {str(now): now})
        pipe.zcard(key)
        pipe.expire(key, window_seconds)
        _, _, count, _ = pipe.execute()
        return int(count) <= max_events
    except (RedisClientError, Exception):
        return True


def check_repo_limit(repo_name: str) -> bool:
    """Return True if the repository is within its hourly PR review limit."""
    key = f"prguard:rl:repo:{repo_name}"
    return _check_limit(key, _REPO_WINDOW_SECONDS, _REPO_MAX_EVENTS)


def check_repo_concurrency(repo_name: str, max_inflight: int = 5) -> bool:
    """Return True if this repository has capacity for another in-flight review."""
    key = f"prguard:concurrency:repo:{repo_name}"
    try:
        r = get_redis()
        current = int(r.incr(key))
        r.expire(key, 15 * 60)
        if current > max_inflight:
            r.decr(key)
            return False
        return True
    except (RedisClientError, Exception):
        return True


def release_repo_concurrency(repo_name: str) -> None:
    """Release one in-flight slot for a repository."""
    try:
        get_redis().decr(f"prguard:concurrency:repo:{repo_name}")
    except (RedisClientError, Exception):
        return None


def check_model_limit(model: str, max_events: int = _MODEL_MAX_EVENTS) -> bool:
    """Return True when a model-specific request rate is within limits."""
    safe_model = model.replace("/", "_").replace(":", "_")
    key = f"prguard:rl:model:{safe_model}"
    return _check_limit(key, _MODEL_WINDOW_SECONDS, max_events)


def check_installation_limit(installation_id: int) -> bool:
    """Return True if the installation is within its daily PR review limit."""
    key = f"prguard:rl:inst:{installation_id}"
    return _check_limit(key, _INSTALL_WINDOW_SECONDS, _INSTALL_MAX_EVENTS)


__all__ = [
    "check_installation_limit",
    "check_model_limit",
    "check_repo_concurrency",
    "check_repo_limit",
    "release_repo_concurrency",
]
