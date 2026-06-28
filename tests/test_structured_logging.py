"""Tests for structured JSON logging (Phase 15 coverage lift)."""

from __future__ import annotations

import json
import logging


def _make_record(msg: str = "test message", level: int = logging.INFO, **extra) -> logging.LogRecord:
    """Helper to create a LogRecord with optional extra attributes."""
    record = logging.LogRecord(
        name="test.logger",
        level=level,
        pathname=__file__,
        lineno=1,
        msg=msg,
        args=(),
        exc_info=None,
    )
    for key, value in extra.items():
        setattr(record, key, value)
    return record


class TestJsonLogFormatter:
    """Tests for JsonLogFormatter."""

    def test_output_is_valid_json(self):
        """format() produces valid JSON."""
        from prguard_ai.observability.structured_logging import JsonLogFormatter

        formatter = JsonLogFormatter()
        record = _make_record("hello")
        output = formatter.format(record)
        data = json.loads(output)
        assert data["message"] == "hello"

    def test_required_fields_present(self):
        """Standard fields are always present in output."""
        from prguard_ai.observability.structured_logging import JsonLogFormatter

        formatter = JsonLogFormatter()
        record = _make_record("check fields")
        data = json.loads(formatter.format(record))

        assert "timestamp" in data
        assert "level" in data
        assert data["level"] == "INFO"
        assert "service" in data
        assert data["service"] == "prguard"
        assert "message" in data
        assert "extra" in data

    def test_pr_id_propagated(self):
        """pr_id extra field appears at top level."""
        from prguard_ai.observability.structured_logging import JsonLogFormatter

        formatter = JsonLogFormatter()
        record = _make_record("msg", pr_id="owner/repo#42")
        data = json.loads(formatter.format(record))
        assert data["pr_id"] == "owner/repo#42"

    def test_agent_name_propagated(self):
        """agent_name extra field appears at top level."""
        from prguard_ai.observability.structured_logging import JsonLogFormatter

        formatter = JsonLogFormatter()
        record = _make_record("msg", agent_name="security")
        data = json.loads(formatter.format(record))
        assert data["agent_name"] == "security"

    def test_event_type_propagated(self):
        """event_type extra field appears at top level."""
        from prguard_ai.observability.structured_logging import JsonLogFormatter

        formatter = JsonLogFormatter()
        record = _make_record("msg", event_type="agent_completed")
        data = json.loads(formatter.format(record))
        assert data["event_type"] == "agent_completed"

    def test_stack_trace_included_on_exception(self):
        """stack_trace field is populated when exc_info is set."""
        from prguard_ai.observability.structured_logging import JsonLogFormatter
        import sys

        formatter = JsonLogFormatter()
        try:
            raise ValueError("test error")
        except ValueError:
            exc_info = sys.exc_info()

        record = logging.LogRecord(
            name="test", level=logging.ERROR,
            pathname=__file__, lineno=1,
            msg="error occurred", args=(), exc_info=exc_info,
        )
        data = json.loads(formatter.format(record))
        assert "stack_trace" in data
        assert "ValueError" in data["stack_trace"]

    def test_extra_attributes_captured(self):
        """Non-standard record attributes appear in the extra dict."""
        from prguard_ai.observability.structured_logging import JsonLogFormatter

        formatter = JsonLogFormatter()
        record = _make_record("msg", custom_field="custom_value")
        data = json.loads(formatter.format(record))
        assert data["extra"].get("custom_field") == "custom_value"

    def test_trace_span_ids_absent_when_no_span(self):
        """trace_id and span_id are None when no active span exists."""
        from prguard_ai.observability.structured_logging import JsonLogFormatter

        formatter = JsonLogFormatter()
        record = _make_record("no span")
        data = json.loads(formatter.format(record))
        # In test env without an active span these should be None
        assert data.get("trace_id") is None
        assert data.get("span_id") is None

    def test_warning_level_recorded(self):
        """WARNING level is correctly captured in output."""
        from prguard_ai.observability.structured_logging import JsonLogFormatter

        formatter = JsonLogFormatter()
        record = _make_record("warn msg", level=logging.WARNING)
        data = json.loads(formatter.format(record))
        assert data["level"] == "WARNING"


class TestConfigureStructuredLogging:
    """Tests for configure_structured_logging()."""

    def test_sets_json_formatter_on_root_logger(self):
        """configure_structured_logging installs a JsonLogFormatter on the root logger."""
        from prguard_ai.observability.structured_logging import (
            configure_structured_logging,
            JsonLogFormatter,
        )
        import logging

        configure_structured_logging(level=logging.DEBUG)
        root = logging.getLogger()
        assert len(root.handlers) >= 1
        assert any(isinstance(h.formatter, JsonLogFormatter) for h in root.handlers)
        assert root.level == logging.DEBUG

    def test_replaces_existing_handlers(self):
        """configure_structured_logging clears prior handlers."""
        from prguard_ai.observability.structured_logging import configure_structured_logging
        import logging

        root = logging.getLogger()
        # Add a sentinel handler
        dummy = logging.NullHandler()
        root.addHandler(dummy)

        configure_structured_logging(level=logging.INFO)
        # The NullHandler should have been removed
        assert dummy not in root.handlers
