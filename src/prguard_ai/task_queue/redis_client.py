"""Centralized Redis client for PRGuard AI.

Supports single-node and Sentinel deployments, with basic connection retries
and sane network timeouts. All code should import Redis via:

    from prguard_ai.task_queue.redis_client import get_redis
"""

from __future__ import annotations

import logging
import threading
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


class RedisClient:
    """Instance-based Redis client. Create a new one per task/request."""

    def __init__(self, url: str = settings.redis_url):
        self._url = url
        self._lock = threading.Lock()
        self._client = self._build()

    def _build(self) -> redis.Redis:
        mode = settings.redis_mode.lower()
        if mode == "memory":
            return self._make_memory_client()
        if mode == "sentinel":
            return self._make_sentinel_client()
        return self._make_singleton_client()

    def _make_singleton_client(self) -> redis.Redis:
        return redis.Redis.from_url(
            self._url,
            socket_timeout=_DEFAULT_TIMEOUT,
            socket_connect_timeout=_DEFAULT_TIMEOUT,
            socket_keepalive=True,
        )

    def _make_memory_client(self) -> redis.Redis:
        if fakeredis is None:
            raise RedisClientError("fakeredis is not installed; cannot use in-memory Redis mode.")
        return fakeredis.FakeRedis()

    def _make_sentinel_client(self) -> redis.Redis:
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

    def get(self, key: str) -> str | None:
        return self._client.get(key)

    def set(self, key: str, value: str, ex: int | None = None) -> None:
        with self._lock:
            self._client.set(key, value, ex=ex)

    def pipeline(self, transaction: bool = True):
        return self._client.pipeline(transaction=transaction)

    def ping(self) -> bool:
        try:
            self._client.ping()
            return True
        except Exception:
            return False

    def lpush(self, key: str, value: str) -> None:
        self._client.lpush(key, value)


_CLIENT: Optional[redis.Redis] = None


def _build_client() -> redis.Redis:
    mode = settings.redis_mode.lower()
    if mode == "memory":
        return _make_memory_client()
    if mode == "sentinel":
        return _make_sentinel_client()
    return _make_singleton_client()


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


def get_redis() -> redis.Redis:
    """Return a shared Redis client instance with basic retry on first use."""
    global _CLIENT
    if _CLIENT is not None:
        return _CLIENT

    last_exc: Exception | None = None
    for _ in range(max(1, _DEFAULT_RETRIES)):
        try:
            client = _build_client()
            client.ping()
            _CLIENT = client
            return _CLIENT
        except Exception as exc:
            last_exc = exc
    if settings.redis_fallback_to_memory:
        try:
            _CLIENT = _make_memory_client()
            _LOGGER.warning("Redis unreachable; falling back to in-memory fakeredis (non-production mode).")
            return _CLIENT
        except Exception as exc:
            last_exc = exc
    raise RedisClientError(f"Failed to connect to Redis after {_DEFAULT_RETRIES} attempts") from last_exc


def ping_ok() -> bool:
    """Return True if Redis is reachable and responsive."""
    try:
        get_redis().ping()
        return True
    except Exception:
        return False


def get_redis_client() -> RedisClient:
    return RedisClient()


def store_agent_output(pr_id: str, agent: str, output_json: str, ex: int = 3600) -> None:
    client = get_redis()
    key = f"prguard:agent:{pr_id}:{agent}"
    client.set(key, output_json, ex=ex)


def get_agent_output_json(pr_id: str, agent: str) -> str | None:
    client = get_redis()
    key = f"prguard:agent:{pr_id}:{agent}"
    return client.get(key)


def get_all_outputs_json(pr_id: str) -> dict[str, str]:
    agents = ["style", "logic", "security"]
    result: dict[str, str] = {}
    for a in agents:
        data = get_agent_output_json(pr_id, a)
        if data:
            result[a] = data
    return result


__all__ = [
    "get_redis",
    "get_redis_client",
    "store_agent_output",
    "get_agent_output_json",
    "get_all_outputs_json",
    "ping_ok",
    "RedisClient",
    "RedisClientError",
]
