"""LLM client utilities for PRGuard AI."""

from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
from typing import Any, Dict, Tuple

import openai

from pydantic import BaseModel

from prguard_ai.config.settings import settings
from prguard_ai.observability.logging import log_llm_usage
from prguard_ai.observability.metrics import LLM_TOKENS_USED
from prguard_ai.observability.tracing import get_tracer
from prguard_ai.cost.budget_manager import add_usage, check_budget
from prguard_ai.reliability.circuit_breaker import llm_breaker, CircuitBreakerError
from prguard_ai.schemas.agent_output import AgentOutput, Issue
from prguard_ai.task_queue.redis_client import get_redis, RedisClientError
from prguard_ai.llm.token_budget import TokenBudget
from prguard_ai.llm.model_router import model_router, semantic_cache
import redis

logger = logging.getLogger(__name__)


class TokenBudgetExceededError(Exception):
    """Exception raised when LLM token or cost budget is exceeded."""
    pass


class LLMOutputError(Exception):
    """Exception raised when LLM output fails Pydantic validation."""
    pass


MAX_RETRIES = 3
RETRY_BACKOFF_SECONDS = 2
DEFAULT_MODEL = settings.llm_model

MAX_TOKENS_PER_REQUEST = settings.max_tokens_per_request
MAX_TOKENS_PER_PR = settings.max_tokens_per_pr

_PR_TOKEN_USAGE: Dict[str, int] = {}
_LOCK = threading.Lock()
_TRACER = get_tracer("llm")


class LLMIssueResponse(BaseModel):
    issues: list[Issue]


class LLMRefineResponse(BaseModel):
    refined_issues: list[Issue]
    new_findings: list[Issue]
    dropped_findings: list[int]


class LLMCoordinatorResponse(BaseModel):
    critiques: dict[str, str]


class LLMClient:
    def __init__(
        self,
        token_budget: TokenBudget | None = None,
        max_tokens: int = 2048,
        temperature: float = 0.1,
    ):
        self.provider = settings.llm_provider
        self.model = settings.llm_model
        self.max_tokens = max_tokens
        self.temperature = temperature
        self.token_budget = token_budget
        self.call_count = 0

        if self.provider == "deepseek":
            self.client = openai.OpenAI(
                api_key=settings.deepseek_api_key,
                base_url=settings.llm_base_url,
            )
        elif self.provider == "openai":
            self.client = openai.OpenAI(api_key=settings.openai_api_key)
            self.model = settings.llm_model
        else:
            raise ValueError(f"Unknown LLM provider: {self.provider}")

    def _get_model(self) -> str:
        return self.model

    def generate(
        self,
        prompt: str,
        max_tokens: int | None = None,
        **kwargs,
    ) -> str:
        if self.token_budget and not self.token_budget.check_and_consume(max_tokens or self.max_tokens):
            raise TokenBudgetExceededError("Budget exhausted")

        try:
            response = self.client.chat.completions.create(
                model=self._get_model(),
                messages=[
                    {"role": "system", "content": "You are a code review agent."},
                    {"role": "user", "content": prompt},
                ],
                max_tokens=max_tokens or self.max_tokens,
                temperature=self.temperature,
                **kwargs,
            )
            self.call_count += 1
            return response.choices[0].message.content or ""
        except openai.RateLimitError:
            logger.warning("DeepSeek rate limit hit")
            raise
        except openai.OpenAIError as e:
            logger.error(f"LLM API error: {type(e).__name__}: {e}")
            logger.error(f"  Provider: {self.provider}")
            logger.error(f"  Model: {self._get_model()}")
            raise

    def generate_analysis(
        self,
        prompt: str,
        response_schema: type[BaseModel] = LLMIssueResponse,
        model: str | None = None,
    ) -> BaseModel:
        model = model or self.model
        try:
            response = self.client.beta.chat.completions.parse(
                model=model,
                messages=[
                    {"role": "system", "content": "You are a code review agent."},
                    {"role": "user", "content": prompt},
                ],
                response_format=response_schema,
                temperature=self.temperature,
                max_tokens=self.max_tokens,
            )
            self.call_count += 1
            return response.choices[0].message.parsed
        except Exception as e:
            logger.error(f"Structured output failed: {e}")
            try:
                return self._fallback_json_mode(prompt, response_schema)
            except Exception as fallback_err:
                raise LLMOutputError(
                    f"Both structured output and JSON fallback failed: {e}, {fallback_err}"
                ) from fallback_err

    def _fallback_json_mode(
        self,
        prompt: str,
        response_schema: type[BaseModel],
    ) -> BaseModel:
        schema_json = response_schema.model_json_schema()
        augmented_prompt = (
            f"{prompt}\n\nRespond with JSON matching this schema:\n{schema_json}"
        )
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[{"role": "user", "content": augmented_prompt}],
            response_format={"type": "json_object"},
            temperature=self.temperature,
        )
        raw = response.choices[0].message.content
        return response_schema.model_validate_json(raw)


class LLMOutputValidator:
    def validate(self, raw_response: str, expected_schema: type[BaseModel]) -> bool:
        from prguard_ai.security.prompt_injection import PromptInjectionDetector

        if not raw_response.strip():
            return False
        detector = PromptInjectionDetector()
        check = detector.detect(raw_response)
        if not check.clean:
            logger.warning(
                "LLM output contains injection patterns: %s", check.matched_patterns
            )
            return False
        try:
            expected_schema.model_validate_json(raw_response)
            return True
        except Exception:
            return False

    def sanitize_for_github(self, text: str) -> str:
        patterns = [
            (r'ghp_[a-zA-Z0-9]{36}', '[REDACTED_GH_TOKEN]'),
            (r'sk-[a-zA-Z0-9]{20,}', '[REDACTED_API_KEY]'),
            (r'[a-zA-Z0-9]{32,}', '[REDACTED_KEY]'),
        ]
        sanitized = text
        for pattern, replacement in patterns:
            sanitized = re.sub(pattern, replacement, sanitized)
        return sanitized


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
    return stripped[first_newline + 1 : last_fence].strip()


def parse_agent_issues(raw: str) -> list[Issue]:
    """Parse and validate an LLM issue array with the public Issue schema."""
    stripped = _strip_markdown_fence(raw)
    if not stripped:
        return []
    data = json.loads(stripped)
    if not isinstance(data, list):
        raise ValueError("Expected LLM JSON array response.")
    return [Issue.validate_and_sanitize(item) for item in data]


def parse_agent_output(raw: str) -> AgentOutput:
    """Parse and validate a complete structured agent response."""
    stripped = _strip_markdown_fence(raw)
    if not stripped:
        return AgentOutput(agent="unknown", confidence=0.0)
    data = json.loads(stripped)
    if not isinstance(data, dict):
        raise ValueError("Expected LLM JSON object response.")
    return AgentOutput.model_validate(data)


def calculate_llm_cost(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    prompt_rate = 0.5 / 1_000_000
    completion_rate = 2.0 / 1_000_000

    m = model.lower()
    if "deepseek" in m:
        prompt_rate = 0.5 / 1_000_000
        completion_rate = 2.0 / 1_000_000

    cost = prompt_tokens * prompt_rate + completion_tokens * completion_rate
    return float(round(cost, 6))


def _get_client() -> openai.OpenAI:
    provider = settings.llm_provider
    if provider == "deepseek":
        api_key = settings.deepseek_api_key
        if not api_key:
            raise RuntimeError("DEEPSEEK_API_KEY is not configured.")
        return openai.OpenAI(
            base_url=settings.llm_base_url,
            api_key=api_key,
        )
    elif provider == "openai":
        api_key = settings.openai_api_key
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY is not configured.")
        return openai.OpenAI(api_key=api_key)
    else:
        raise RuntimeError(f"Unknown LLM provider: {provider}")


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
                    pipe.expire(key, 3600)
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
    offline_mode = settings.prguard_offline_mode
    provider = settings.llm_provider
    api_key = settings.deepseek_api_key if provider == "deepseek" else settings.openai_api_key
    route = model_router.route(agent, prompt)
    if model == DEFAULT_MODEL:
        model = route.model
    max_tokens = min(max_tokens, route.max_tokens)

    if use_cache:
        cached = semantic_cache.get(f"{agent}:{prompt}")
        if cached is not None:
            return cached

    if offline_mode or not api_key or "PYTEST_CURRENT_TEST" in os.environ:
        if offline_mode:
            logger.info("Offline mode enabled; returning stub response from generate_analysis.")
        elif not api_key:
            logger.warning(f"API key not set for provider {provider}; returning offline stub response.")
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
        semantic_cache.set(f"{agent}:{prompt}", "[]", meta)
        return "[]", meta

    _get_client()

    requested = min(max_tokens, settings.max_tokens_per_request)
    _check_and_update_budget(pr_id, requested)

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

                total_tokens = int(meta["total_tokens"])
                prompt_tokens = int(meta["prompt_tokens"])
                completion_tokens = int(meta["completion_tokens"])
                span.set_attribute("llm.prompt_tokens", prompt_tokens)
                span.set_attribute("llm.completion_tokens", completion_tokens)
                span.set_attribute("llm.total_tokens", total_tokens)

                estimated_cost = calculate_llm_cost(model, prompt_tokens, completion_tokens)
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
                logger.error("LLM API error: %s", exc)
                if attempt == MAX_RETRIES:
                    raise
                time.sleep(RETRY_BACKOFF_SECONDS * attempt)
            except Exception as exc:
                last_error = exc
                span.record_exception(exc)
                logger.exception("Unexpected error calling LLM API.")
                if attempt == MAX_RETRIES:
                    raise
                time.sleep(RETRY_BACKOFF_SECONDS * attempt)

    assert last_error is not None
    raise last_error


__all__ = [
    "LLMClient",
    "LLMIssueResponse",
    "LLMRefineResponse",
    "LLMCoordinatorResponse",
    "LLMOutputError",
    "LLMOutputValidator",
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
    global _last_llm_health_check, _last_llm_health_status
    now = time.time()
    if now - _last_llm_health_check < 30.0:
        return _last_llm_health_status

    offline_mode = settings.prguard_offline_mode
    provider = settings.llm_provider
    api_key = settings.deepseek_api_key if provider == "deepseek" else settings.openai_api_key
    if offline_mode:
        _last_llm_health_status = "offline"
        _last_llm_health_check = now
        return _last_llm_health_status
    if not api_key:
        _last_llm_health_status = "missing_api_key"
        _last_llm_health_check = now
        return _last_llm_health_status

    try:
        client = _get_client()
        client.chat.completions.create(
            model=DEFAULT_MODEL,
            messages=[{"role": "user", "content": "ping"}],
            max_tokens=5,
        )
        _last_llm_health_status = "connected"
    except Exception as exc:
        logger.warning("LLM health check probe failed: %s", exc)
        _last_llm_health_status = f"error: {str(exc)}"

    _last_llm_health_check = now
    return _last_llm_health_status
