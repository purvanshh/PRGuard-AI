"""Prompt registry with versioned runtime selection."""

from __future__ import annotations

import os
from pathlib import Path

PROMPTS_ROOT = Path(__file__).resolve().parents[2] / "prompts"


def selected_prompt_version(agent: str, repo_metadata: dict | None = None) -> str:
    metadata = repo_metadata or {}
    overrides = metadata.get("prompt_versions") or {}
    if agent in overrides:
        return str(overrides[agent])
    return os.getenv(f"PRGUARD_PROMPT_VERSION_{agent.upper()}", os.getenv("PRGUARD_PROMPT_VERSION", "legacy"))


def prompt_path(agent: str, version: str) -> Path:
    if version == "legacy":
        return PROMPTS_ROOT / f"{agent}_prompt.txt"
    return PROMPTS_ROOT / version / f"{agent}.txt"


def load_prompt(agent: str, repo_metadata: dict | None = None, fallback: str = "") -> tuple[str, str]:
    version = selected_prompt_version(agent, repo_metadata)
    path = prompt_path(agent, version)
    if path.exists():
        return path.read_text(encoding="utf-8"), version
    legacy = prompt_path(agent, "legacy")
    if legacy.exists():
        return legacy.read_text(encoding="utf-8"), "legacy"
    return fallback, version


__all__ = ["PROMPTS_ROOT", "load_prompt", "prompt_path", "selected_prompt_version"]
