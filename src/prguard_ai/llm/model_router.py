"""Model routing, fallback selection, and lightweight semantic caching."""

from __future__ import annotations

import hashlib
import json
import re
import time
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List

import redis

from prguard_ai.config.settings import settings


DEFAULT_MODEL_CONFIG = {
    "style": {"simple": "gpt-4o-mini", "complex": "gpt-4o", "max_tokens": 768},
    "logic": {"simple": "gpt-4o-mini", "complex": "gpt-4o", "max_tokens": 1536},
    "security": {"simple": "gpt-4o", "complex": "gpt-4o", "max_tokens": 2048},
}


@dataclass(frozen=True)
class RouteDecision:
    agent: str
    complexity: str
    model: str
    max_tokens: int


def _tokenize(text: str) -> set[str]:
    return {token for token in re.findall(r"[a-z0-9_]+", text.lower()) if len(token) > 2}


class SemanticCache:
    """Redis-backed semantic cache with TTL, versioning, and bounded fallback."""

    def __init__(
        self,
        threshold: float = 0.82,
        *,
        ttl_seconds: int = 24 * 60 * 60,
        max_entries: int = 10_000,
        namespace: str = "prguard:semantic-cache",
        prompt_version: str = "v1",
        redis_client: object | None = None,
    ) -> None:
        self.threshold = threshold
        self.ttl_seconds = ttl_seconds
        self.max_entries = max_entries
        self.namespace = namespace
        self.prompt_version = prompt_version
        self._redis = redis_client
        self._entries: OrderedDict[str, dict] = OrderedDict()

    def _client(self) -> object | None:
        if self._redis is not None:
            return self._redis
        try:
            self._redis = redis.Redis.from_url(settings.redis_url, decode_responses=True)
            self._redis.ping()
            return self._redis
        except Exception:
            self._redis = None
            return None

    def _fingerprint(self, prompt: str) -> str:
        return hashlib.sha256(prompt.encode("utf-8")).hexdigest()

    def _redis_key(self, prompt: str) -> str:
        return f"{self.namespace}:{self.prompt_version}:{self._fingerprint(prompt)}"

    def _index_key(self) -> str:
        return f"{self.namespace}:{self.prompt_version}:index"

    def _embed(self, prompt: str) -> dict[str, float]:
        tokens = _tokenize(prompt)
        if not tokens:
            return {}
        weight = 1.0 / len(tokens)
        return {token: weight for token in tokens}

    def _similarity(self, left: dict[str, float], right: dict[str, float]) -> float:
        if not left or not right:
            return 0.0
        shared = set(left) & set(right)
        dot = sum(left[token] * right[token] for token in shared)
        left_norm = sum(value * value for value in left.values()) ** 0.5
        right_norm = sum(value * value for value in right.values()) ** 0.5
        return dot / max(left_norm * right_norm, 1e-9)

    def _pack(self, prompt: str, response: str, meta: dict) -> str:
        stored_meta = dict(meta)
        stored_meta["cache_key"] = self._fingerprint(prompt)[:16]
        stored_meta["prompt_version"] = self.prompt_version
        return json.dumps({"embedding": self._embed(prompt), "response": response, "meta": stored_meta})

    def _unpack(self, payload: str | bytes | None) -> dict | None:
        if payload is None:
            return None
        if isinstance(payload, bytes):
            payload = payload.decode("utf-8")
        try:
            data = json.loads(payload)
        except json.JSONDecodeError:
            return None
        if not isinstance(data, dict):
            return None
        return data

    def get(self, prompt: str) -> tuple[str, dict] | None:
        embedding = self._embed(prompt)
        client = self._client()
        if client is not None:
            try:
                keys = list(client.zrevrange(self._index_key(), 0, self.max_entries - 1))
                for key in keys:
                    data = self._unpack(client.get(key))
                    if not data:
                        continue
                    similarity = self._similarity(embedding, data.get("embedding", {}))
                    if similarity >= self.threshold:
                        meta = dict(data.get("meta", {}))
                        meta["cache_hit"] = True
                        meta["cache_similarity"] = round(similarity, 4)
                        return str(data.get("response", "")), meta
            except Exception:
                self._redis = None

        now = time.time()
        expired = [key for key, value in self._entries.items() if value["expires_at"] <= now]
        for key in expired:
            self._entries.pop(key, None)
        for key, data in list(self._entries.items()):
            similarity = self._similarity(embedding, data["embedding"])
            if similarity >= self.threshold:
                self._entries.move_to_end(key)
                hit_meta = dict(data["meta"])
                hit_meta["cache_hit"] = True
                hit_meta["cache_similarity"] = round(similarity, 4)
                return data["response"], hit_meta
        return None

    def set(self, prompt: str, response: str, meta: dict) -> None:
        key = self._redis_key(prompt)
        payload = self._pack(prompt, response, meta)
        client = self._client()
        if client is not None:
            try:
                client.setex(key, self.ttl_seconds, payload)
                client.zadd(self._index_key(), {key: time.time()})
                stale = client.zrange(self._index_key(), 0, -(self.max_entries + 1))
                if stale:
                    client.delete(*stale)
                    client.zrem(self._index_key(), *stale)
                client.expire(self._index_key(), self.ttl_seconds)
                return
            except Exception:
                self._redis = None

        data = self._unpack(payload)
        if data is None:
            return
        data["expires_at"] = time.time() + self.ttl_seconds
        self._entries[key] = data
        self._entries.move_to_end(key)
        while len(self._entries) > self.max_entries:
            self._entries.popitem(last=False)

    def clear(self) -> None:
        client = self._client()
        if client is not None:
            try:
                keys = list(client.zrange(self._index_key(), 0, -1))
                if keys:
                    client.delete(*keys)
                client.delete(self._index_key())
            except Exception:
                self._redis = None
        self._entries.clear()

    def invalidate_prompt_version(self, prompt_version: str) -> None:
        self.prompt_version = prompt_version


class ModelRouter:
    """Choose cost-aware models by agent and prompt complexity."""

    def __init__(self, config: dict | None = None) -> None:
        self.config = config or DEFAULT_MODEL_CONFIG

    @classmethod
    def from_file(cls, path: str | Path) -> ModelRouter:
        config = DEFAULT_MODEL_CONFIG.copy()
        current_section: str | None = None
        for raw_line in Path(path).read_text(encoding="utf-8").splitlines():
            line = raw_line.rstrip()
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            if not line.startswith(" ") and line.endswith(":"):
                current_section = line[:-1]
                config.setdefault(current_section, {})
                continue
            if not line.startswith(" ") and ":" in line:
                key, value = [part.strip() for part in line.split(":", 1)]
                if value.startswith("[") and value.endswith("]"):
                    config[key] = [
                        item.strip().strip("'\"") for item in value[1:-1].split(",") if item.strip()
                    ]
                else:
                    config[key] = value.strip("'\"")
                current_section = None
                continue
            if current_section and ":" in line:
                key, value = [part.strip() for part in line.split(":", 1)]
                if value.startswith("[") and value.endswith("]"):
                    config[current_section] = [
                        item.strip().strip("'\"") for item in value[1:-1].split(",") if item.strip()
                    ]
                else:
                    parsed: str | int = int(value) if value.isdigit() else value.strip("'\"")
                    if isinstance(config.get(current_section), dict):
                        config[current_section][key] = parsed
        return cls(config)

    def assess_complexity(self, prompt: str) -> str:
        changed_files = prompt.count("diff --git")
        risky_terms = sum(term in prompt.lower() for term in ["auth", "sql", "token", "payment", "crypto"])
        return "complex" if changed_files > 5 or len(prompt) > 12000 or risky_terms >= 2 else "simple"

    def route(self, agent: str, prompt: str) -> RouteDecision:
        normalized_agent = agent.lower()
        agent_config = self.config.get(normalized_agent, self.config["logic"])
        complexity = self.assess_complexity(prompt)
        model = agent_config.get(complexity, agent_config.get("simple", "gpt-4o-mini"))
        max_tokens = int(agent_config.get("max_tokens", 1024))
        return RouteDecision(normalized_agent, complexity, str(model), max_tokens)


semantic_cache = SemanticCache()
model_router = ModelRouter()

__all__ = ["ModelRouter", "RouteDecision", "SemanticCache", "model_router", "semantic_cache"]
