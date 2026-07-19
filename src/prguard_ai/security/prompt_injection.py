"""Prompt-boundary and injection-defense helpers."""

from __future__ import annotations

from dataclasses import dataclass


SUSPICIOUS_PROMPT_PATTERNS = (
    "ignore all previous instructions",
    "ignore previous instructions",
    "developer message",
    "system prompt",
    "you are now",
    "</diff>",
)


@dataclass(frozen=True)
class PromptInspection:
    suspicious: bool
    reasons: list[str]


def sanitize_diff(diff_text: str) -> str:
    """Escape boundary markers inside untrusted diff content."""
    return diff_text.replace("</diff>", "&lt;/diff&gt;").replace("<diff>", "&lt;diff&gt;")


def wrap_diff(diff_text: str) -> str:
    """Wrap untrusted diff text in explicit boundaries for LLM prompts."""
    return f"<diff>\n{sanitize_diff(diff_text)}\n</diff>"


def inspect_prompt_injection(diff_text: str) -> PromptInspection:
    lowered = diff_text.lower()
    reasons = [pattern for pattern in SUSPICIOUS_PROMPT_PATTERNS if pattern in lowered]
    return PromptInspection(bool(reasons), reasons)


def response_is_suspicious(raw_response: str, diff_text: str) -> bool:
    """Flag empty issue responses to non-empty suspicious diffs for manual review."""
    if not diff_text.strip():
        return False
    inspection = inspect_prompt_injection(diff_text)
    if not inspection.suspicious:
        return False
    return raw_response.strip() in {"", "[]", "{}"}


__all__ = [
    "PromptInspection",
    "inspect_prompt_injection",
    "response_is_suspicious",
    "sanitize_diff",
    "wrap_diff",
]
