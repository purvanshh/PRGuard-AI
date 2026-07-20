"""Prompt-boundary and injection-defense helpers."""

from __future__ import annotations

import logging
import re
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


@dataclass
class InjectionCheck:
    clean: bool
    risk_score: float
    matched_patterns: list[str]


class PromptInjectionDetector:
    BLOCKLIST_PATTERNS = [
        r"ignore\s+(all\s+)?(previous|prior|earlier)\s+(instructions?|commands?|directions?)",
        r"system\s*prompt",
        r"you\s+are\s+now\s+",
        r"disregard\s+(all\s+)?(previous|prior)",
        r"new\s+instructions?:",
        r"<\s*/\s*diff\s*>",
        r"<\s*diff\s+[^>]*>",
    ]

    def check_structure(self, diff_text: str) -> InjectionCheck:
        issues: list[str] = []
        open_tags = diff_text.count("<diff")
        close_tags = diff_text.count("</diff>")
        if open_tags != close_tags:
            issues.append("MISMATCHED_DIFF_TAGS")
        if re.search(r'<diff[^>]*>.*<diff', diff_text, re.DOTALL):
            issues.append("NESTED_DIFF_TAGS")
        if any(ord(c) < 32 and c not in '\n\r\t' for c in diff_text):
            issues.append("CONTROL_CHARACTERS")
        risk = min(1.0, len(issues) * 0.3)
        return InjectionCheck(
            clean=len(issues) == 0,
            risk_score=risk,
            matched_patterns=issues,
        )

    def detect(self, diff_text: str) -> InjectionCheck:
        pattern_hits: list[str] = []
        for pattern in self.BLOCKLIST_PATTERNS:
            if re.search(pattern, diff_text, re.IGNORECASE):
                pattern_hits.append(pattern[:50])
        if pattern_hits:
            return InjectionCheck(
                clean=False,
                risk_score=min(1.0, len(pattern_hits) * 0.25),
                matched_patterns=pattern_hits,
            )
        structural = self.check_structure(diff_text)
        if not structural.clean:
            return structural
        return InjectionCheck(clean=True, risk_score=0.0, matched_patterns=[])


def sanitize_diff_for_prompt(diff_text: str) -> str:
    escaped = diff_text.replace("</diff>", "<\\/diff>")
    return f'<diff user_content="true" length="{len(escaped)}">\n{escaped}\n</diff>'


def sanitize_diff(diff_text: str) -> str:
    return diff_text.replace("</diff>", "&lt;/diff&gt;").replace("<diff>", "&lt;diff&gt;")


def wrap_diff(diff_text: str) -> str:
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
    if not diff_text.strip():
        return False
    if inspect_prompt_injection(diff_text).suspicious:
        return True
    return raw_response.strip() in {"", "[]", "{}"}


__all__ = [
    "PromptInspection",
    "InjectionCheck",
    "PromptInjectionDetector",
    "inspect_prompt_injection",
    "response_is_suspicious",
    "sanitize_diff",
    "sanitize_diff_for_prompt",
    "wrap_diff",
]
