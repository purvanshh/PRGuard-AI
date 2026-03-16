"""Structured JSON logging configuration for PRGuard AI."""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone
from typing import Any, Dict


class JsonLogFormatter(logging.Formatter):
    """Format log records as structured JSON."""

    def format(self, record: logging.LogRecord) -> str:  # type: ignore[override]
        payload: Dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "service": "prguard",
            "pr_id": getattr(record, "pr_id", None),
            "agent": getattr(record, "agent", record.name),
            "message": record.getMessage(),
            "extra": {},
        }

        # Attach any extra attributes that are not part of the standard LogRecord.
        standard_attrs = {
            "name",
            "msg",
            "args",
            "levelname",
            "levelno",
            "pathname",
            "filename",
            "module",
            "exc_info",
            "exc_text",
            "stack_info",
            "lineno",
            "funcName",
            "created",
            "msecs",
            "relativeCreated",
            "thread",
            "threadName",
            "processName",
            "process",
        }
        for key, value in record.__dict__.items():
            if key not in standard_attrs and key not in {"pr_id", "agent"}:
                payload["extra"][key] = value

        return json.dumps(payload, separators=(",", ":"))


def configure_structured_logging(level: int = logging.INFO) -> None:
    """Configure root logger to emit JSON logs to stdout."""
    handler = logging.StreamHandler(stream=sys.stdout)
    handler.setFormatter(JsonLogFormatter())

    root = logging.getLogger()
    root.setLevel(level)
    root.handlers.clear()
    root.addHandler(handler)


__all__ = ["configure_structured_logging", "JsonLogFormatter"]

