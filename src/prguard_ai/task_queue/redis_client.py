"""Centralized Redis client for PRGuard AI.

Supports single-node and Sentinel deployments, with basic connection retries
and sane network timeouts. All code should import Redis via:

    from prguard_ai.task_queue.redis_client import get_redis
"""

from __future__ import annotations

import logging
from typing import Optional

import redis
from redis.sentinel import Sentinel

from prguard_ai.config.settings import settings

try:  # Optional, used for memory fallback.
    import fakeredis
except Exception:  # pragma: no cover - optional dependency
    fakeredis = None


class RedisClientError(RuntimeError):
    """Wrapper error type for Redis client failures."""


_DEFAULT_TIMEOUT = settings.redis_socket_timeout
_DEFAULT_RETRIES = settings.redis_connect_retries

_LOGGER = logging.getLogger(__name__)


def _make_singleton_client() -> redis.Redis:
    url = settings.redis_url
    return redis.Redis.from_url(
        url,
        socket_timeout=_DEFAULT_TIMEOUT,
        socket_connect_timeout=_DEFAULT_TIMEOUT,
        socket_keepalive=True,
    )


def _make_memory_client() -> redis.Redis:
    if fakeredis is None:
        raise RedisClientError("fakeredis is not installed; cannot use in-memory Redis mode.")
    return fakeredis.FakeRedis()


def _make_sentinel_client() -> redis.Redis:
    hosts_raw = settings.redis_sentinel_hosts
    service_name = settings.redis_sentinel_service_name
    if not hosts_raw:
        raise RedisClientError("REDIS_SENTINEL_HOSTS must be set when REDIS_MODE=sentinel.")

    endpoints = []
    for part in hosts_raw.split(","):
        part = part.strip()
        if not part:
            continue
        host, _, port = part.partition(":")
        endpoints.append((host, int(port or "26379")))

    sentinel = Sentinel(
        endpoints,
        socket_timeout=_DEFAULT_TIMEOUT,
        socket_keepalive=True,
    )
    return sentinel.master_for(
        service_name,
        socket_timeout=_DEFAULT_TIMEOUT,
        socket_keepalive=True,
    )


_CLIENT: Optional[redis.Redis] = None


def _build_client() -> redis.Redis:
    mode = settings.redis_mode.lower()
    if mode == "memory":
        return _make_memory_client()
    if mode == "sentinel":
        return _make_sentinel_client()
    return _make_singleton_client()


def get_redis() -> redis.Redis:
    """Return a shared Redis client instance with basic retry on first use."""
    global _CLIENT
    if _CLIENT is not None:
        return _CLIENT

    last_exc: Exception | None = None
    for _ in range(max(1, _DEFAULT_RETRIES)):
        try:
            client = _build_client()
            # Lightweight connectivity check.
            client.ping()
            _CLIENT = client
            return _CLIENT
        except Exception as exc:  # pragma: no cover - network failures are environment-specific
            last_exc = exc
    # Optional graceful fallback to in-memory Redis for local/dev scenarios.
    if settings.redis_fallback_to_memory:
        try:
            _CLIENT = _make_memory_client()
            _LOGGER.warning("Redis unreachable; falling back to in-memory fakeredis (non-production mode).")
            return _CLIENT
        except Exception as exc:  # pragma: no cover - misconfiguration
            last_exc = exc
    raise RedisClientError(f"Failed to connect to Redis after {_DEFAULT_RETRIES} attempts") from last_exc  # type: ignore[arg-type]


def ping_ok() -> bool:
    """Return True if Redis is reachable and responsive."""
    try:
        get_redis().ping()
        return True
    except Exception:
        return False


__all__ = ["get_redis", "ping_ok", "RedisClientError"]
