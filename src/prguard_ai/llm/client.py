"""LLM client utilities for PRGuard AI."""

from __future__ import annotations

import json
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
from prguard_ai.reliability.circuit_breaker import llm_breaker, CircuitBreakerError
from prguard_ai.schemas.agent_output import AgentOutput, Issue
from prguard_ai.task_queue.redis_client import get_redis, RedisClientError
from prguard_ai.llm.model_router import model_router, semantic_cache
import redis

logger = logging.getLogger(__name__)

class TokenBudgetExceededError(Exception):
    """Exception raised when LLM token or cost budget is exceeded."""
    pass

MAX_RETRIES = 3
RETRY_BACKOFF_SECONDS = 2
DEFAULT_MODEL = "openai/gpt-oss-120b"

MAX_TOKENS_PER_REQUEST = settings.max_tokens_per_request
MAX_TOKENS_PER_PR = settings.max_tokens_per_pr

_PR_TOKEN_USAGE: Dict[str, int] = {}
_LOCK = threading.Lock()
_TRACER = get_tracer("llm")


def _is_truthy(value: str | None) -> bool:
    return str(value).lower() in {"1", "true", "yes", "on"}


def _strip_markdown_fence(raw: str) -> str:
    if not raw or not raw.strip():
        return ""
    stripped = raw.strip()
    if not stripped.startswith("```"):
        return stripped
    first_newline = stripped.find("\n")
    last_fence = stripped.rfind("```")
    if first_newline == -1 or last_fence <= first_newline:
        return stripped
    return stripped[first_newline + 1:last_fence].strip()


def extract_json_from_llm_response(raw: str) -> str:
    """Validate and return a JSON array response."""
    stripped = _strip_markdown_fence(raw)
    if not stripped:
        return "[]"
    data = json.loads(stripped)
    if not isinstance(data, list):
        raise ValueError("Expected LLM JSON array response.")
    return json.dumps(data)


def extract_json_obj_from_llm_response(raw: str) -> str:
    """Validate and return a JSON object response."""
    stripped = _strip_markdown_fence(raw)
    if not stripped:
        return "{}"
    data = json.loads(stripped)
    if not isinstance(data, dict):
        raise ValueError("Expected LLM JSON object response.")
    return json.dumps(data)


def parse_agent_issues(raw: str) -> list[Issue]:
    """Parse and validate an LLM issue array with the public Issue schema."""
    data = json.loads(extract_json_from_llm_response(raw))
    return [Issue.validate_and_sanitize(item) for item in data]


def parse_agent_output(raw: str) -> AgentOutput:
    """Parse and validate a complete structured agent response."""
    data = json.loads(extract_json_obj_from_llm_response(raw))
    return AgentOutput.model_validate(data)


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
    nvidia_key = settings.nvidia_api_key
    if nvidia_key:
        return openai.OpenAI(
            base_url="https://integrate.api.nvidia.com/v1",
            api_key=nvidia_key,
        )
    openai_key = settings.openai_api_key
    if not openai_key:
        raise RuntimeError("NVIDIA_API_KEY or OPENAI_API_KEY is not configured.")
    return openai.OpenAI(
        api_key=openai_key,
    )


def _check_and_update_budget(pr_id: str | None, requested_tokens: int) -> None:
    if pr_id is None:
        return
    try:
        r = get_redis()
        key = f"pr:{pr_id}:token_usage"
        with r.pipeline() as pipe:
            while True:
                try:
                    pipe.watch(key)
                    used_val = pipe.get(key)
                    used = int(used_val) if used_val is not None else 0
                    if used >= settings.max_tokens_per_pr:
                        raise TokenBudgetExceededError("Token budget for this PR has been exhausted.")
                    allowed = min(requested_tokens, settings.max_tokens_per_request)
                    remaining = settings.max_tokens_per_pr - used
                    if allowed > remaining:
                        allowed = remaining
                    pipe.multi()
                    pipe.incrby(key, allowed)
                    pipe.expire(key, 3600)  # 1 hour TTL
                    pipe.execute()
                    break
                except (redis.WatchError, redis.exceptions.WatchError):
                    continue
    except (redis.RedisError, RedisClientError, Exception) as exc:
        if isinstance(exc, TokenBudgetExceededError):
            raise
        logger.warning("Redis is unavailable for token budget tracking; falling back to in-memory: %s", exc)
        with _LOCK:
            used = _PR_TOKEN_USAGE.get(pr_id, 0)
            if used >= settings.max_tokens_per_pr:
                raise TokenBudgetExceededError("Token budget for this PR has been exhausted.")
            allowed = min(requested_tokens, settings.max_tokens_per_request)
            remaining = settings.max_tokens_per_pr - used
            if allowed > remaining:
                allowed = remaining
            _PR_TOKEN_USAGE[pr_id] = used + allowed


def generate_analysis(
    prompt: str,
    model: str = DEFAULT_MODEL,
    max_tokens: int = 512,
    temperature: float = 0.0,
    pr_id: str | None = None,
    agent: str = "unknown",
    use_cache: bool = True,
    expect_json: bool = True,
) -> Tuple[str, Dict[str, Any]]:
    """
    Call the OpenAI API with retry and basic rate-limit handling.

    Enforces per-request and per-PR token budgets. When `OPENAI_API_KEY` is not
    configured (e.g. in local or CI test runs), this returns a deterministic
    stub response instead of calling the external API.
    """
    offline_mode = settings.prguard_offline_mode
    nvidia_key = settings.nvidia_api_key or settings.openai_api_key
    route = model_router.route(agent, prompt)
    if model == DEFAULT_MODEL:
        model = route.model
    max_tokens = min(max_tokens, route.max_tokens)

    if use_cache:
        cached = semantic_cache.get(f"{agent}:{prompt}")
        if cached is not None:
            return cached

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
            "agent": agent,
            "route_complexity": route.complexity,
            "cache_hit": False,
        }
        # Agents expect JSON; an empty list means "no issues".
        semantic_cache.set(f"{agent}:{prompt}", "[]", meta)
        return "[]", meta

    if not settings.nvidia_api_key and settings.openai_api_key:
        if model == DEFAULT_MODEL:
            model = "gpt-4o"

    _get_client()  # validate key early

    requested = min(max_tokens, settings.max_tokens_per_request)
    _check_and_update_budget(pr_id, requested)

    # Repository-level cost budget check (per day).
    repo_name: str | None = None
    if pr_id and "#" in pr_id:
        repo_name = pr_id.split("#", 1)[0]
    if repo_name and not check_budget(repo_name):
        raise TokenBudgetExceededError("LLM cost budget exceeded")

    last_error: Exception | None = None
    with _TRACER.start_as_current_span("llm_call") as span:
        span.set_attribute("llm.model", model)
        if pr_id:
            span.set_attribute("pr.id", pr_id)
        for attempt in range(1, MAX_RETRIES + 1):
            span.set_attribute("llm.attempt", attempt)
            try:
                client = _get_client()
                request_kwargs = {
                    "model": model,
                    "messages": [
                        {"role": "system", "content": "Reasoning: low"},
                        {"role": "user", "content": prompt},
                    ],
                    "max_tokens": requested,
                    "temperature": temperature,
                }
                if expect_json:
                    request_kwargs["response_format"] = {"type": "json_object"}
                response = llm_breaker.call(client.chat.completions.create, **request_kwargs)
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
                    "agent": agent,
                    "route_complexity": route.complexity,
                    "cache_hit": False,
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
                    from prguard_ai.db import run_async
                    try:
                        run_async(
                            log_llm_usage(
                                pr_id=pr_id,
                                agent=agent,
                                model=model,
                                prompt_tokens=prompt_tokens,
                                completion_tokens=completion_tokens,
                                estimated_cost_usd=estimated_cost,
                            )
                        )
                    except Exception as e:
                        logger.warning("Failed to log LLM usage to PostgreSQL: %s", e)
                if repo_name:
                    add_usage(repo_name, estimated_cost)
                LLM_TOKENS_USED.labels(agent=agent, model=model).inc(total_tokens)
                semantic_cache.set(f"{agent}:{prompt}", message, meta)
                return message, meta
            except CircuitBreakerError:
                raise
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
    "extract_json_from_llm_response",
    "extract_json_obj_from_llm_response",
    "parse_agent_issues",
    "parse_agent_output",
    "generate_analysis",
    "check_llm_health",
    "DEFAULT_MODEL",
    "MAX_TOKENS_PER_REQUEST",
    "MAX_TOKENS_PER_PR",
    "TokenBudgetExceededError",
]


_last_llm_health_check = 0.0
_last_llm_health_status = "unknown"

def check_llm_health() -> str:
    """
    Probe the LLM endpoint to verify API availability, caching the status for 30 seconds.
    """
    global _last_llm_health_check, _last_llm_health_status
    now = time.time()
    if now - _last_llm_health_check < 30.0:
        return _last_llm_health_status

    offline_mode = settings.prguard_offline_mode
    nvidia_key = settings.nvidia_api_key or settings.openai_api_key
    if offline_mode:
        _last_llm_health_status = "offline"
        _last_llm_health_check = now
        return _last_llm_health_status
    if not nvidia_key:
        _last_llm_health_status = "missing_api_key"
        _last_llm_health_check = now
        return _last_llm_health_status

    try:
        client = _get_client()
        # Use a very small chat completion request as a ping
        client.chat.completions.create(
            model="gpt-4o" if not settings.nvidia_api_key else "openai/gpt-oss-120b",
            messages=[{"role": "user", "content": "ping"}],
            max_tokens=5,
        )
        _last_llm_health_status = "connected"
    except Exception as exc:
        logger.warning("LLM health check probe failed: %s", exc)
        _last_llm_health_status = f"error: {str(exc)}"

    _last_llm_health_check = now
    return _last_llm_health_status
