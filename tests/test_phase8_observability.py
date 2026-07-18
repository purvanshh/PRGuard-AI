import json
import logging

from prguard_ai.observability.metrics import QUEUE_DEPTH, record_queue_depth, record_review_latency
from prguard_ai.observability.structured_logging import JsonLogFormatter
from prguard_ai.observability.tracing import (
    get_correlation_id,
    inject_trace_context,
    set_correlation_id,
)


def test_correlation_id_flows_into_headers_and_logs():
    set_correlation_id("abc123")
    assert get_correlation_id() == "abc123"
    assert inject_trace_context({})["correlation_id"] == "abc123"

    record = logging.LogRecord("test", logging.INFO, __file__, 1, "hello", (), None)
    payload = json.loads(JsonLogFormatter().format(record))

    assert payload["correlation_id"] == "abc123"


def test_sli_metric_helpers_record_values():
    record_queue_depth("logic", 42)
    record_review_latency(3.5)

    sample = QUEUE_DEPTH.labels(queue="logic")._value.get()
    assert sample == 42
