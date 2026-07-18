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
        import traceback
        from opentelemetry import trace
        from prguard_ai.observability.tracing import get_correlation_id

        # Dynamically fetch OpenTelemetry trace context
        trace_id = None
        span_id = None
        try:
            span = trace.get_current_span()
            if span and span.get_span_context() and span.get_span_context().is_valid:
                trace_id = trace.format_trace_id(span.get_span_context().trace_id)
                span_id = trace.format_span_id(span.get_span_context().span_id)
        except Exception:
            pass

        payload: Dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "service": "prguard",
            "pr_id": getattr(record, "pr_id", None),
            "agent": getattr(record, "agent", record.name),
            "agent_name": getattr(record, "agent_name", None),
            "event_type": getattr(record, "event_type", None),
            "message": record.getMessage(),
            "trace_id": trace_id,
            "span_id": span_id,
            "correlation_id": getattr(record, "correlation_id", None) or get_correlation_id(),
            "extra": {},
        }

        if record.exc_info:
            payload["stack_trace"] = "".join(traceback.format_exception(*record.exc_info))

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
            if key not in standard_attrs and key not in {
                "pr_id",
                "agent",
                "agent_name",
                "event_type",
                "trace_id",
                "span_id",
                "correlation_id",
            }:
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
