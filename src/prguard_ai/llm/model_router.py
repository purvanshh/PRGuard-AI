"""Model routing, fallback selection, and lightweight semantic caching."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List


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
    """Small process-local semantic cache using token Jaccard similarity."""

    def __init__(self, threshold: float = 0.82) -> None:
        self.threshold = threshold
        self._entries: List[tuple[set[str], str, dict]] = []

    def get(self, prompt: str) -> tuple[str, dict] | None:
        tokens = _tokenize(prompt)
        for cached_tokens, response, meta in self._entries:
            union = max(len(tokens | cached_tokens), 1)
            similarity = len(tokens & cached_tokens) / union
            if similarity >= self.threshold:
                hit_meta = dict(meta)
                hit_meta["cache_hit"] = True
                hit_meta["cache_similarity"] = round(similarity, 4)
                return response, hit_meta
        return None

    def set(self, prompt: str, response: str, meta: dict) -> None:
        stored_meta = dict(meta)
        stored_meta["cache_key"] = hashlib.sha256(prompt.encode("utf-8")).hexdigest()[:16]
        self._entries.append((_tokenize(prompt), response, stored_meta))

    def clear(self) -> None:
        self._entries.clear()


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
