"""Per-PR token budget. Thread-safe. Instance-based."""

from __future__ import annotations

import threading

from prguard_ai.config.settings import settings


class TokenBudget:
    def __init__(self, pr_id: str, max_tokens: int = settings.max_tokens_per_pr):
        self.pr_id = pr_id
        self.max_tokens = max_tokens
        self._used = 0
        self._lock = threading.Lock()

    def check_and_consume(self, requested: int) -> bool:
        with self._lock:
            if self._used + requested > self.max_tokens:
                return False
            self._used += requested
            return True

    @property
    def remaining(self) -> int:
        with self._lock:
            return self.max_tokens - self._used

    @property
    def used(self) -> int:
        with self._lock:
            return self._used
