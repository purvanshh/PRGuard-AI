"""Tests for task_queue.task_registry using fakeredis (Phase 15 coverage lift)."""

from __future__ import annotations

import pytest
import fakeredis


# ---------------------------------------------------------------------------
# Fixture: patch get_redis to use fakeredis
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _fake_redis(monkeypatch):
    """Inject fakeredis into task_registry so no real Redis is needed."""
    fake = fakeredis.FakeRedis()
    import prguard_ai.task_queue.task_registry as reg

    monkeypatch.setattr(reg, "get_redis", lambda: fake)
    # Reset cached values
    monkeypatch.setattr(reg, "_PROCESSING_TTL_SECONDS", 900)
    monkeypatch.setattr(reg, "_GLOBAL_CONCURRENCY_LIMIT", 5)
    yield fake


# ---------------------------------------------------------------------------
# register_pr_processing / is_pr_processing / complete_pr_processing
# ---------------------------------------------------------------------------

class TestPrProcessingRegistry:
    def test_register_new_pr_returns_true(self, _fake_redis):
        from prguard_ai.task_queue.task_registry import register_pr_processing

        assert register_pr_processing("owner/repo#1") is True

    def test_register_duplicate_pr_returns_false(self, _fake_redis):
        from prguard_ai.task_queue.task_registry import register_pr_processing

        register_pr_processing("owner/repo#2")
        assert register_pr_processing("owner/repo#2") is False

    def test_is_pr_processing_false_before_registration(self, _fake_redis):
        from prguard_ai.task_queue.task_registry import is_pr_processing

        assert is_pr_processing("owner/repo#99") is False

    def test_is_pr_processing_true_after_registration(self, _fake_redis):
        from prguard_ai.task_queue.task_registry import register_pr_processing, is_pr_processing

        register_pr_processing("owner/repo#3")
        assert is_pr_processing("owner/repo#3") is True

    def test_complete_pr_processing_removes_key(self, _fake_redis):
        from prguard_ai.task_queue.task_registry import (
            register_pr_processing,
            complete_pr_processing,
            is_pr_processing,
        )

        register_pr_processing("owner/repo#4")
        complete_pr_processing("owner/repo#4")
        assert is_pr_processing("owner/repo#4") is False


# ---------------------------------------------------------------------------
# acquire_global_slot / release_global_slot
# ---------------------------------------------------------------------------

class TestGlobalSlots:
    def test_acquire_slot_returns_true_when_space_available(self, _fake_redis):
        from prguard_ai.task_queue.task_registry import acquire_global_slot

        assert acquire_global_slot() is True

    def test_acquire_fills_up_to_limit(self, _fake_redis):
        from prguard_ai.task_queue.task_registry import acquire_global_slot
        import prguard_ai.task_queue.task_registry as reg

        reg._GLOBAL_CONCURRENCY_LIMIT = 3
        assert acquire_global_slot() is True
        assert acquire_global_slot() is True
        assert acquire_global_slot() is True
        assert acquire_global_slot() is False

    def test_release_decrements_count(self, _fake_redis):
        from prguard_ai.task_queue.task_registry import (
            acquire_global_slot,
            release_global_slot,
        )
        import prguard_ai.task_queue.task_registry as reg

        reg._GLOBAL_CONCURRENCY_LIMIT = 1
        acquire_global_slot()
        assert acquire_global_slot() is False
        release_global_slot()
        assert acquire_global_slot() is True

    def test_release_on_empty_does_not_crash(self, _fake_redis):
        from prguard_ai.task_queue.task_registry import release_global_slot

        # Should not raise even when slot count is 0
        release_global_slot()
