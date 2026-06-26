from __future__ import annotations

import json
import logging
from unittest.mock import MagicMock, patch
from opentelemetry import trace
from prguard_ai.observability.structured_logging import JsonLogFormatter, configure_structured_logging
from prguard_ai.observability.health import check_logging


def test_json_log_formatter_basic():
    formatter = JsonLogFormatter()
    record = logging.LogRecord(
        name="test_logger",
        level=logging.INFO,
        pathname="test.py",
        lineno=10,
        msg="Hello world",
        args=(),
        exc_info=None
    )
    
    # Set extra fields on record
    record.pr_id = "owner/repo#42"
    record.agent_name = "security"
    record.event_type = "analysis_start"
    
    # Active span mock
    mock_span = MagicMock()
    mock_span.get_span_context().is_valid = True
    mock_span.get_span_context().trace_id = 12345678901234567890123456789012
    mock_span.get_span_context().span_id = 9876543210987654
    
    with patch("opentelemetry.trace.get_current_span", return_value=mock_span):
        formatted = formatter.format(record)
        data = json.loads(formatted)
        
        assert data["level"] == "INFO"
        assert data["service"] == "prguard"
        assert data["message"] == "Hello world"
        assert data["pr_id"] == "owner/repo#42"
        assert data["agent_name"] == "security"
        assert data["event_type"] == "analysis_start"
        assert data["trace_id"] is not None
        assert data["span_id"] is not None


def test_json_log_formatter_exception():
    formatter = JsonLogFormatter()
    try:
        raise ValueError("Sample crash")
    except ValueError as e:
        import sys
        exc_info = sys.exc_info()
        
    record = logging.LogRecord(
        name="test_logger",
        level=logging.ERROR,
        pathname="test.py",
        lineno=10,
        msg="Something crashed",
        args=(),
        exc_info=exc_info
    )
    
    formatted = formatter.format(record)
    data = json.loads(formatted)
    assert "stack_trace" in data
    assert "ValueError: Sample crash" in data["stack_trace"]


def test_check_logging_probe():
    # Configure structured logging temporarily
    configure_structured_logging()
    
    # The health probe check_logging() should now return configured
    assert check_logging() == "configured"
    
    # Clear handlers
    logging.getLogger().handlers.clear()
    assert check_logging() == "not_configured"
