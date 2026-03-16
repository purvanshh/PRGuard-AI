"""LLM client utilities for PRGuard AI."""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, Tuple

import openai

from config.settings import settings

logger = logging.getLogger(__name__)


MAX_RETRIES = 3
RETRY_BACKOFF_SECONDS = 2
DEFAULT_MODEL = "gpt-4o"


def _configure_openai() -> None:
    if getattr(openai, "api_key", None):
        return
    if not settings.openai_api_key:
        raise RuntimeError("OPENAI_API_KEY is not configured.")
    openai.api_key = settings.openai_api_key


def generate_analysis(
    prompt: str,
    model: str = DEFAULT_MODEL,
    max_tokens: int = 512,
    temperature: float = 0.0,
) -> Tuple[str, Dict[str, Any]]:
    """
    Call the OpenAI API with retry and basic rate-limit handling.

    Returns (text, metadata) where metadata contains token usage.
    """
    _configure_openai()

    last_error: Exception | None = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = openai.ChatCompletion.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=max_tokens,
                temperature=temperature,
            )
            message = response["choices"][0]["message"]["content"]
            usage = response.get("usage", {}) or {}
            return message, {
                "model": model,
                "prompt_tokens": usage.get("prompt_tokens", 0),
                "completion_tokens": usage.get("completion_tokens", 0),
                "total_tokens": usage.get("total_tokens", 0),
            }
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
        except Exception as exc:  # pragma: no cover - safety net
            last_error = exc
            logger.exception("Unexpected error calling OpenAI.")
            if attempt == MAX_RETRIES:
                raise
            time.sleep(RETRY_BACKOFF_SECONDS * attempt)

    assert last_error is not None
    raise last_error


__all__ = ["generate_analysis", "DEFAULT_MODEL"]

