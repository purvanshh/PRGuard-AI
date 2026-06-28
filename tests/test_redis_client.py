"""Tests for task_queue.redis_client (Phase 15 coverage lift)."""

from __future__ import annotations

import pytest
import fakeredis


class TestRedisClientMemoryMode:
    """Test Redis client in memory mode (via fakeredis)."""

    def test_get_redis_returns_client_in_memory_mode(self, monkeypatch):
        """get_redis() returns a client when REDIS_MODE=memory."""
        import prguard_ai.task_queue.redis_client as rc

        # Reset the singleton
        monkeypatch.setattr(rc, "_CLIENT", None)
        monkeypatch.setattr(rc.settings, "redis_mode", "memory")

        client = rc.get_redis()
        assert client is not None

    def test_get_redis_singleton_reused(self, monkeypatch):
        """get_redis() returns the same instance on repeated calls."""
        import prguard_ai.task_queue.redis_client as rc

        monkeypatch.setattr(rc, "_CLIENT", None)
        monkeypatch.setattr(rc.settings, "redis_mode", "memory")

        client1 = rc.get_redis()
        client2 = rc.get_redis()
        assert client1 is client2

    def test_ping_ok_true_in_memory_mode(self, monkeypatch):
        """ping_ok() returns True when using fakeredis."""
        import prguard_ai.task_queue.redis_client as rc

        monkeypatch.setattr(rc, "_CLIENT", None)
        monkeypatch.setattr(rc.settings, "redis_mode", "memory")
        rc.get_redis()  # ensure client is set

        assert rc.ping_ok() is True

    def test_ping_ok_false_when_client_raises(self, monkeypatch):
        """ping_ok() returns False when redis.ping() raises."""
        import prguard_ai.task_queue.redis_client as rc

        bad_client = fakeredis.FakeRedis()

        def bad_ping():
            raise RuntimeError("connection refused")

        bad_client.ping = bad_ping
        monkeypatch.setattr(rc, "_CLIENT", bad_client)

        assert rc.ping_ok() is False


class TestRedisClientSentinelParsing:
    """Test Sentinel host parsing logic."""

    def test_make_sentinel_raises_when_hosts_empty(self, monkeypatch):
        """_make_sentinel_client raises RedisClientError if REDIS_SENTINEL_HOSTS is empty."""
        import prguard_ai.task_queue.redis_client as rc

        monkeypatch.setattr(rc.settings, "redis_sentinel_hosts", "")
        with pytest.raises(rc.RedisClientError, match="REDIS_SENTINEL_HOSTS"):
            rc._make_sentinel_client()

    def test_make_memory_client_raises_if_fakeredis_missing(self, monkeypatch):
        """_make_memory_client raises RedisClientError when fakeredis is None."""
        import prguard_ai.task_queue.redis_client as rc

        monkeypatch.setattr(rc, "fakeredis", None)
        with pytest.raises(rc.RedisClientError, match="fakeredis is not installed"):
            rc._make_memory_client()


class TestRedisClientFallback:
    """Test fallback-to-memory behaviour."""

    def test_get_redis_raises_when_fallback_disabled_and_real_redis_unavailable(self, monkeypatch):
        """get_redis() raises RedisClientError when fallback=False and real Redis is down."""
        import prguard_ai.task_queue.redis_client as rc

        monkeypatch.setattr(rc, "_CLIENT", None)
        monkeypatch.setattr(rc.settings, "redis_mode", "single")
        monkeypatch.setattr(rc.settings, "redis_url", "redis://127.0.0.1:19999/0")  # non-existent port
        monkeypatch.setattr(rc.settings, "redis_fallback_to_memory", False)
        monkeypatch.setattr(rc.settings, "redis_connect_retries", 1)

        with pytest.raises(rc.RedisClientError):
            rc.get_redis()

    def test_get_redis_falls_back_to_memory_when_enabled(self, monkeypatch):
        """get_redis() falls back to fakeredis when fallback=True and real Redis is down."""
        import prguard_ai.task_queue.redis_client as rc

        monkeypatch.setattr(rc, "_CLIENT", None)
        monkeypatch.setattr(rc.settings, "redis_mode", "single")
        monkeypatch.setattr(rc.settings, "redis_url", "redis://127.0.0.1:19999/0")
        monkeypatch.setattr(rc.settings, "redis_fallback_to_memory", True)
        monkeypatch.setattr(rc.settings, "redis_connect_retries", 1)

        client = rc.get_redis()
        assert client is not None
        # Cleanup singleton so other tests don't see a broken client
        monkeypatch.setattr(rc, "_CLIENT", None)
