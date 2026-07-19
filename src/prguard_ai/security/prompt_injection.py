"""Prompt-boundary and injection-defense helpers."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from prguard_ai.observability.metrics import PROMPT_INJECTION_DETECTED

logger = logging.getLogger(__name__)


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
    suspicious = bool(reasons)
    if suspicious:
        PROMPT_INJECTION_DETECTED.inc()
        logger.warning("Prompt injection patterns detected in diff: %s", reasons)
    return PromptInspection(suspicious, reasons)


def response_is_suspicious(raw_response: str, diff_text: str) -> bool:
    """Flag responses that indicate possible prompt injection.

    Returns True when:
    1. Injection patterns are found in the diff itself (regardless of response), or
    2. The LLM returned a completely empty response for a non-empty diff.
    """
    if not diff_text.strip():
        return False
    if inspect_prompt_injection(diff_text).suspicious:
        return True
    return raw_response.strip() in {"", "[]", "{}"}


__all__ = [
    "PromptInspection",
    "inspect_prompt_injection",
    "response_is_suspicious",
    "sanitize_diff",
    "wrap_diff",
]
