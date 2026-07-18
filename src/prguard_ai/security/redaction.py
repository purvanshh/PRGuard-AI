"""Secret redaction helpers for user-visible output."""

from __future__ import annotations

import re


SECRET_PATTERNS = [
    re.compile(r"(?i)(api[_-]?key|token|secret|password)\s*[:=]\s*['\"]?([A-Za-z0-9_\-./+=]{8,})['\"]?"),
    re.compile(r"gh[pousr]_[A-Za-z0-9_]{20,}"),
    re.compile(r"sk-[A-Za-z0-9]{20,}"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
]


def redact_secrets(text: str) -> str:
    """Mask common token/key formats in text destined for PR comments."""
    redacted = text
    for pattern in SECRET_PATTERNS:
        if pattern.groups >= 2:
            redacted = pattern.sub(lambda match: f"{match.group(1)}=***", redacted)
        else:
            redacted = pattern.sub("***", redacted)
    return redacted


def public_error_code(exc: Exception) -> str:
    """Return a stable generic error code without leaking exception details."""
    return f"PRGUARD_{exc.__class__.__name__.upper()}"


__all__ = ["public_error_code", "redact_secrets"]
