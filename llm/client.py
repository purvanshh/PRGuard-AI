"""LLM client utilities for PRGuard AI."""

from __future__ import annotations

import logging
import threading
import time
from typing import Any, Dict, Tuple

import openai

from config.settings import settings

logger = logging.getLogger(__name__)

MAX_RETRIES = 3
RETRY_BACKOFF_SECONDS = 2
DEFAULT_MODEL = "gpt-4o"

MAX_TOKENS_PER_REQUEST = 2048
MAX_TOKENS_PER_PR = 8000

_PR_TOKEN_USAGE: Dict[str, int] = {}
_LOCK = threading.Lock()


def _configure_openai() -> None:
    if getattr(openai, "api_key", None):
        return
    if not settings.openai_api_key:
        raise RuntimeError("OPENAI_API_KEY is not configured.")
    openai.api_key = settings.openai_api_key


def _check_and_update_budget(pr_id: str | None, requested_tokens: int) -> None:
    if pr_id is None:
        return
    with _LOCK:
        used = _PR_TOKEN_USAGE.get(pr_id, 0)
        if used >= MAX_TOKENS_PER_PR:
            raise RuntimeError("Token budget for this PR has been exhausted.")
        allowed = min(requested_tokens, MAX_TOKENS_PER_REQUEST)
        remaining = MAX_TOKENS_PER_PR - used
        if allowed > remaining:
            allowed = remaining
        _PR_TOKEN_USAGE[pr_id] = used + allowed


def generate_analysis(
    prompt: str,
    model: str = DEFAULT_MODEL,
    max_tokens: int = 512,
    temperature: float = 0.0,
    pr_id: str | None = None,
) -> Tuple[str, Dict[str, Any]]:
    """
    Call the OpenAI API with retry and basic rate-limit handling.

    Enforces per-request and per-PR token budgets. When `OPENAI_API_KEY` is not
    configured (e.g. in local or CI test runs), this returns a deterministic
    stub response instead of calling the external API.
    """
    if not settings.openai_api_key:
        logger.warning("OPENAI_API_KEY not set; returning offline stub response from generate_analysis.")
        meta: Dict[str, Any] = {
            "model": "offline-stub",
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "pr_id": pr_id,
        }
        # Agents expect JSON; an empty list means "no issues".
        return "[]", meta

    _configure_openai()

    requested = min(max_tokens, MAX_TOKENS_PER_REQUEST)
    _check_and_update_budget(pr_id, requested)

    last_error: Exception | None = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = openai.ChatCompletion.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=requested,
                temperature=temperature,
            )
            message = response["choices"][0]["message"]["content"]

            usage = response.get("usage", {}) or {}
            meta = {
                "model": model,
                "prompt_tokens": usage.get("prompt_tokens", 0),
                "completion_tokens": usage.get("completion_tokens", 0),
                "total_tokens": usage.get("total_tokens", 0),
                "pr_id": pr_id,
            }
            return message, meta
        except openai.error.RateLimitError as exc:  # type: ignore[attr-defined]
            last_error = exc
            logger.warning("OpenAI rate limit hit (attempt %s/%s). Backing off.", attempt, MAX_RETRIES)
            time.sleep(RETRY_BACKOFF_SECONDS * attempt)
        except openai.error.OpenAIError as exc:  # type: ignore[attr-defined]
            last_error = exc
            logger.error("OpenAI API error: %s", exc)
            if attempt == MAX_RETRIES:
                raise
            time.sleep(RETRY_BACKOFF_SECONDS * attempt)
        except Exception as exc:  # pragma: no cover
            last_error = exc
            logger.exception("Unexpected error calling OpenAI.")
            if attempt == MAX_RETRIES:
                raise
            time.sleep(RETRY_BACKOFF_SECONDS * attempt)

    assert last_error is not None
    raise last_error


__all__ = [
    "generate_analysis",
    "DEFAULT_MODEL",
    "MAX_TOKENS_PER_REQUEST",
    "MAX_TOKENS_PER_PR",
]


