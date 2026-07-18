"""Feature flags and deterministic rollout helpers."""

from __future__ import annotations

import hashlib
import os


def _env_key(flag: str) -> str:
    return "PRGUARD_FLAG_" + flag.upper().replace("-", "_")


def is_enabled(flag: str, *, default: bool = False) -> bool:
    raw = os.getenv(_env_key(flag))
    if raw is None:
        return default
    return raw.lower() in {"1", "true", "yes", "on", "enabled"}


def rollout_enabled(flag: str, subject: str, *, default_percent: float = 0.0) -> bool:
    raw = os.getenv(_env_key(f"{flag}_ROLLOUT_PERCENT"))
    try:
        percent = float(raw) if raw is not None else default_percent
    except ValueError:
        percent = default_percent
    percent = max(0.0, min(100.0, percent))
    digest = hashlib.sha256(f"{flag}:{subject}".encode("utf-8")).hexdigest()
    bucket = int(digest[:8], 16) / 0xFFFFFFFF * 100.0
    return bucket < percent


def canary_stage(flag: str, subject: str, stages: tuple[float, ...] = (5.0, 25.0, 50.0, 100.0)) -> float:
    configured = os.getenv(_env_key(f"{flag}_CANARY_STAGE"))
    if configured:
        try:
            return max(0.0, min(100.0, float(configured)))
        except ValueError:
            pass
    for stage in stages:
        if rollout_enabled(flag, subject, default_percent=stage):
            return stage
    return 0.0


__all__ = ["canary_stage", "is_enabled", "rollout_enabled"]
