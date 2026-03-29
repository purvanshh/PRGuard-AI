"""LLM client utilities for PRGuard AI."""

from __future__ import annotations

import logging
import os
import threading
import time
from typing import Any, Dict, Tuple

import openai

from prguard_ai.config.settings import settings
from prguard_ai.observability.logging import log_llm_usage
from prguard_ai.observability.metrics import LLM_TOKENS_USED
from prguard_ai.observability.tracing import get_tracer
from prguard_ai.cost.budget_manager import add_usage, check_budget

logger = logging.getLogger(__name__)

MAX_RETRIES = 3
RETRY_BACKOFF_SECONDS = 2
DEFAULT_MODEL = "openai/gpt-oss-120b"

MAX_TOKENS_PER_REQUEST = 2048
MAX_TOKENS_PER_PR = 8000

_PR_TOKEN_USAGE: Dict[str, int] = {}
_LOCK = threading.Lock()
_TRACER = get_tracer("llm")


def _is_truthy(value: str | None) -> bool:
    return str(value).lower() in {"1", "true", "yes", "on"}


def calculate_openai_cost(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    """
    Rough cost estimation in USD for OpenAI chat models.

    Prices are approximate and can be adjusted as needed. This helper is
    intentionally simple and only meant for relative reporting.
    """
    # Default to GPT-4o-style pricing.
    prompt_rate = 5.0 / 1_000_000  # $5 / 1M tokens
    completion_rate = 15.0 / 1_000_000  # $15 / 1M tokens

    m = model.lower()
    if "gpt-4o" in m:
        prompt_rate = 5.0 / 1_000_000
        completion_rate = 15.0 / 1_000_000
    elif "gpt-4" in m:
        prompt_rate = 10.0 / 1_000_000
        completion_rate = 30.0 / 1_000_000
    elif "gpt-3.5" in m:
        prompt_rate = 0.5 / 1_000_000
        completion_rate = 1.5 / 1_000_000
    elif "gpt-oss-120b" in m:
        prompt_rate = 1.2 / 1_000_000
        completion_rate = 1.2 / 1_000_000

    cost = prompt_tokens * prompt_rate + completion_tokens * completion_rate
    return float(round(cost, 6))

def _get_client() -> openai.OpenAI:
    api_key = os.getenv("NVIDIA_API_KEY") or settings.openai_api_key
    if not api_key:
        raise RuntimeError("NVIDIA_API_KEY is not configured.")
    return openai.OpenAI(
        base_url="https://integrate.api.nvidia.com/v1",
        api_key=api_key,
    )


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
    offline_mode = _is_truthy(os.getenv("PRGUARD_OFFLINE_MODE"))
    nvidia_key = os.getenv("NVIDIA_API_KEY") or settings.openai_api_key

    # Offline/test mode: when explicitly disabled or no API key, return a stub response.
    if offline_mode or not nvidia_key or "PYTEST_CURRENT_TEST" in os.environ:
        if offline_mode:
            logger.info("Offline mode enabled; returning stub response from generate_analysis.")
        elif not nvidia_key:
            logger.warning("NVIDIA_API_KEY not set; returning offline stub response from generate_analysis.")
        else:
            logger.info("Detected pytest run; skipping external API call and returning stub response.")
        meta: Dict[str, Any] = {
            "model": "offline-stub",
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "pr_id": pr_id,
        }
        # Agents expect JSON; an empty list means "no issues".
        return "[]", meta

    _get_client()  # validate key early

    requested = min(max_tokens, MAX_TOKENS_PER_REQUEST)
    _check_and_update_budget(pr_id, requested)

    # Repository-level cost budget check (per day).
    repo_name: str | None = None
    if pr_id and "#" in pr_id:
        repo_name = pr_id.split("#", 1)[0]
    if repo_name and not check_budget(repo_name):
        raise RuntimeError("LLM cost budget exceeded")

    last_error: Exception | None = None
    with _TRACER.start_as_current_span("llm_call") as span:
        span.set_attribute("llm.model", model)
        if pr_id:
            span.set_attribute("pr.id", pr_id)
        for attempt in range(1, MAX_RETRIES + 1):
            span.set_attribute("llm.attempt", attempt)
            try:
                client = _get_client()
                response = client.chat.completions.create(
                    model=model,
                    messages=[
                        {"role": "system", "content": "Reasoning: low"},
                        {"role": "user", "content": prompt},
                    ],
                    max_tokens=requested,
                    temperature=temperature,
                )
                message = response.choices[0].message.content or ""
                usage_obj = response.usage
                usage = {
                    "prompt_tokens": usage_obj.prompt_tokens if usage_obj else 0,
                    "completion_tokens": usage_obj.completion_tokens if usage_obj else 0,
                    "total_tokens": usage_obj.total_tokens if usage_obj else 0,
                }
                meta = {
                    "model": model,
                    "prompt_tokens": usage.get("prompt_tokens", 0),
                    "completion_tokens": usage.get("completion_tokens", 0),
                    "total_tokens": usage.get("total_tokens", 0),
                    "pr_id": pr_id,
                }

                # Metrics and cost tracking.
                total_tokens = int(meta["total_tokens"])
                prompt_tokens = int(meta["prompt_tokens"])
                completion_tokens = int(meta["completion_tokens"])
                span.set_attribute("llm.prompt_tokens", prompt_tokens)
                span.set_attribute("llm.completion_tokens", completion_tokens)
                span.set_attribute("llm.total_tokens", total_tokens)

                estimated_cost = calculate_openai_cost(model, prompt_tokens, completion_tokens)
                if pr_id:
                    log_llm_usage(
                        pr_id=pr_id,
                        agent="unknown",
                        model=model,
                        prompt_tokens=prompt_tokens,
                        completion_tokens=completion_tokens,
                        estimated_cost_usd=estimated_cost,
                    )
                if repo_name:
                    add_usage(repo_name, estimated_cost)
                LLM_TOKENS_USED.labels(agent="unknown", model=model).inc(total_tokens)
                return message, meta
            except openai.RateLimitError as exc:
                last_error = exc
                span.record_exception(exc)
                logger.warning("Rate limit hit (attempt %s/%s). Backing off.", attempt, MAX_RETRIES)
                time.sleep(RETRY_BACKOFF_SECONDS * attempt)
            except openai.OpenAIError as exc:
                last_error = exc
                span.record_exception(exc)
                logger.error("OpenAI API error: %s", exc)
                if attempt == MAX_RETRIES:
                    raise
                time.sleep(RETRY_BACKOFF_SECONDS * attempt)
            except Exception as exc:  # pragma: no cover
                last_error = exc
                span.record_exception(exc)
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

