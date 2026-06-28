"""Thread-safe circuit breaker for PRGuard AI LLM client calls."""

from __future__ import annotations

import logging
import threading
import time
from typing import Callable, ParamSpec, TypeVar

from prguard_ai.config.settings import settings

try:
    from prguard_ai.observability.metrics import record_circuit_state as _record_state
except Exception:  # pragma: no cover - circular import guard at import time
    _record_state = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)

P = ParamSpec("P")
T = TypeVar("T")


class CircuitBreakerError(Exception):
    """Exception raised when the circuit breaker is open."""
    pass


class CircuitBreaker:
    """
    A simple thread-safe state-machine circuit breaker.
    Exposes CLOSED, OPEN, and HALF_OPEN states.
    """

    def __init__(self, fail_max: int = 5, reset_timeout: float = 60.0) -> None:
        self.fail_max = fail_max
        self.reset_timeout = reset_timeout
        self.state = "CLOSED"  # CLOSED, OPEN, HALF_OPEN
        self.failure_count = 0
        self.last_state_change = 0.0
        self.lock = threading.Lock()

    def call(self, func: Callable[P, T], *args: P.args, **kwargs: P.kwargs) -> T:
        with self.lock:
            now = time.time()
            if self.state == "OPEN":
                # Check if reset timeout has expired to transition to HALF_OPEN
                if now - self.last_state_change > self.reset_timeout:
                    logger.info("Circuit breaker reset timeout expired. Transitioning to HALF_OPEN.")
                    self.state = "HALF_OPEN"
                    if _record_state:
                        _record_state("HALF_OPEN")
                else:
                    raise CircuitBreakerError("Circuit breaker is OPEN. Fast-failing LLM call.")

        try:
            # Execute the actual function call
            result = func(*args, **kwargs)

            # If successful, reset circuit breaker
            with self.lock:
                if self.state == "HALF_OPEN":
                    logger.info("Call succeeded in HALF_OPEN. Transitioning to CLOSED.")
                    self.state = "CLOSED"
                    self.failure_count = 0
                    if _record_state:
                        _record_state("CLOSED")
                elif self.state == "CLOSED":
                    self.failure_count = 0
            return result

        except Exception as exc:
            # Exclude client-side budget/usage errors from tripping the breaker
            exc_msg = str(exc)
            if "budget" in exc_msg.lower() or "exhausted" in exc_msg.lower():
                raise exc

            # Record failure and check thresholds
            with self.lock:
                self.failure_count += 1
                logger.warning(
                    "Circuit breaker recorded failure %d/%d. Exception: %s",
                    self.failure_count,
                    self.fail_max,
                    exc,
                )
                if self.state in ("CLOSED", "HALF_OPEN") and self.failure_count >= self.fail_max:
                    logger.error("Circuit breaker threshold reached. Transitioning to OPEN.")
                    self.state = "OPEN"
                    self.last_state_change = time.time()
                    if _record_state:
                        _record_state("OPEN")
            raise CircuitBreakerError("Circuit breaker is OPEN or tripped due to a call failure.") from exc


# Global singleton instance of the LLM circuit breaker
llm_breaker = CircuitBreaker(
    fail_max=settings.llm_circuit_fail_max,
    reset_timeout=float(settings.llm_circuit_reset_timeout),
)

__all__ = ["CircuitBreaker", "CircuitBreakerError", "llm_breaker"]
