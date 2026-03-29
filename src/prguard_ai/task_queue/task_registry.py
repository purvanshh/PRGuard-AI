"""Redis-backed idempotency and concurrency control for PRGuard AI."""

from __future__ import annotations

from typing import Final

from prguard_ai.task_queue.redis_client import get_redis


_PROCESSING_TTL_SECONDS: Final[int] = 15 * 60  # 15 minutes
_GLOBAL_CONCURRENCY_KEY: Final[str] = "prguard:processing:active"
_GLOBAL_CONCURRENCY_LIMIT: Final[int] = 5


def register_pr_processing(pr_id: str) -> bool:
    """Mark a PR as being processed. Returns False if it was already registered."""
    r = get_redis()
    key = f"prguard:processing:{pr_id}"
    if not r.setnx(key, "1"):
        return False
    r.expire(key, _PROCESSING_TTL_SECONDS)
    return True


def is_pr_processing(pr_id: str) -> bool:
    """Return True if the given PR is currently registered as in-flight."""
    r = get_redis()
    key = f"prguard:processing:{pr_id}"
    return bool(r.exists(key))


def complete_pr_processing(pr_id: str) -> None:
    """Clear the in-flight marker for a PR."""
    r = get_redis()
    key = f"prguard:processing:{pr_id}"
    r.delete(key)


def acquire_global_slot() -> bool:
    """Try to reserve one of the global PR processing slots."""
    r = get_redis()
    key = _GLOBAL_CONCURRENCY_KEY
    with r.pipeline() as pipe:
        while True:
            try:
                pipe.watch(key)
                current = int(pipe.get(key) or 0)
                if current >= _GLOBAL_CONCURRENCY_LIMIT:
                    pipe.unwatch()
                    return False
                pipe.multi()
                pipe.set(key, current + 1, ex=_PROCESSING_TTL_SECONDS)
                pipe.execute()
                return True
            except Exception:
                # Retry on concurrent modification (WatchError or transient issues).
                continue


def release_global_slot() -> None:
    """Release one global PR processing slot."""
    r = get_redis()
    key = _GLOBAL_CONCURRENCY_KEY
    try:
        r.decr(key)
    except Exception:
        # Best-effort; if this fails we don't want to break request handling.
        return


__all__ = [
    "register_pr_processing",
    "is_pr_processing",
    "complete_pr_processing",
    "acquire_global_slot",
    "release_global_slot",
]
