"""OpenTelemetry tracing configuration for PRGuard AI."""

from __future__ import annotations

import os
from contextvars import ContextVar

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor


def _is_truthy(value: str | None) -> bool:
    return str(value).lower() in {"1", "true", "yes", "on"}


from prguard_ai.config.settings import settings

_correlation_id: ContextVar[str | None] = ContextVar("correlation_id", default=None)


def set_correlation_id(value: str | None) -> None:
    """Set the current request/task correlation ID."""
    _correlation_id.set(value)


def get_correlation_id() -> str | None:
    """Return the current request/task correlation ID, if any."""
    return _correlation_id.get()


def inject_trace_context(headers: dict[str, str] | None = None) -> dict[str, str]:
    """Inject the current correlation ID into task/message headers."""
    result = dict(headers or {})
    cid = get_correlation_id()
    if cid:
        result["correlation_id"] = cid
    return result


def configure_tracing(service_name: str) -> None:
    """Configure global tracer provider and OTLP exporter."""
    if settings.prguard_offline_mode:
        # In offline/dev mode, skip configuring OTLP to avoid noisy failures.
        return
    if isinstance(trace.get_tracer_provider(), TracerProvider):
        # Already configured.
        return

    resource = Resource.create({"service.name": service_name})
    provider = TracerProvider(resource=resource)
    trace.set_tracer_provider(provider)

    # Default OTLP endpoint (can be overridden via OTEL_EXPORTER_OTLP_ENDPOINT).
    endpoint = settings.otel_exporter_otlp_endpoint

    exporter = OTLPSpanExporter(endpoint=endpoint, insecure=True)
    provider.add_span_processor(BatchSpanProcessor(exporter))


def get_tracer(name: str | None = None):
    """Return a tracer for the given component."""
    return trace.get_tracer(name or "prguard")


__all__ = [
    "configure_tracing",
    "get_correlation_id",
    "get_tracer",
    "inject_trace_context",
    "set_correlation_id",
]
