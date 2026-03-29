"""OpenTelemetry tracing configuration for PRGuard AI."""

from __future__ import annotations

import os

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor


def _is_truthy(value: str | None) -> bool:
    return str(value).lower() in {"1", "true", "yes", "on"}


def configure_tracing(service_name: str) -> None:
    """Configure global tracer provider and OTLP exporter."""
    if _is_truthy(os.getenv("PRGUARD_OFFLINE_MODE")):
        # In offline/dev mode, skip configuring OTLP to avoid noisy failures.
        return
    if isinstance(trace.get_tracer_provider(), TracerProvider):
        # Already configured.
        return

    resource = Resource.create({"service.name": service_name})
    provider = TracerProvider(resource=resource)
    trace.set_tracer_provider(provider)

    # Default OTLP endpoint (can be overridden via OTEL_EXPORTER_OTLP_ENDPOINT).
    endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4317")

    exporter = OTLPSpanExporter(endpoint=endpoint, insecure=True)
    provider.add_span_processor(BatchSpanProcessor(exporter))


def get_tracer(name: str | None = None):
    """Return a tracer for the given component."""
    return trace.get_tracer(name or "prguard")


__all__ = ["configure_tracing", "get_tracer"]
