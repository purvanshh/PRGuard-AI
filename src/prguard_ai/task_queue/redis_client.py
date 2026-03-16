"""Centralized Redis client for PRGuard AI.

Supports single-node and Sentinel deployments, with basic connection retries
and sane network timeouts. All code should import Redis via:

    from task_queue.redis_client import get_redis
"""

from __future__ import annotations

import os
from typing import Optional

import redis
from redis.sentinel import Sentinel


class RedisClientError(RuntimeError):
    """Wrapper error type for Redis client failures."""


_DEFAULT_TIMEOUT = float(os.getenv("REDIS_SOCKET_TIMEOUT", "2.0"))
_DEFAULT_RETRIES = int(os.getenv("REDIS_CONNECT_RETRIES", "3"))


def _make_singleton_client() -> redis.Redis:
    url = os.getenv("REDIS_URL", "redis://redis:6379/0")
    return redis.Redis.from_url(
        url,
        socket_timeout=_DEFAULT_TIMEOUT,
        socket_connect_timeout=_DEFAULT_TIMEOUT,
        socket_keepalive=True,
    )


def _make_sentinel_client() -> redis.Redis:
    hosts_raw = os.getenv("REDIS_SENTINEL_HOSTS", "")
    service_name = os.getenv("REDIS_SENTINEL_SERVICE_NAME", "mymaster")
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
    mode = os.getenv("REDIS_MODE", "single").lower()
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
    raise RedisClientError(f"Failed to connect to Redis after {_DEFAULT_RETRIES} attempts") from last_exc  # type: ignore[arg-type]


def ping_ok() -> bool:
    """Return True if Redis is reachable and responsive."""
    try:
        get_redis().ping()
        return True
    except Exception:
        return False


__all__ = ["get_redis", "ping_ok", "RedisClientError"]

