"""OpenTelemetry tracing configuration for PRGuard AI."""

from __future__ import annotations

import os

from opentelemetry import trace
from opentelemetry.exporter.jaeger.thrift import JaegerExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor


def configure_tracing(service_name: str) -> None:
    """Configure global tracer provider and Jaeger exporter."""
    if isinstance(trace.get_tracer_provider(), TracerProvider):
        # Already configured.
        return

    resource = Resource.create({"service.name": service_name})
    provider = TracerProvider(resource=resource)
    trace.set_tracer_provider(provider)

    jaeger_host = os.getenv("JAEGER_AGENT_HOST", "jaeger")
    jaeger_port = int(os.getenv("JAEGER_AGENT_PORT", "6831"))

    exporter = JaegerExporter(agent_host_name=jaeger_host, agent_port=jaeger_port)
    provider.add_span_processor(BatchSpanProcessor(exporter))


def get_tracer(name: str | None = None):
    """Return a tracer for the given component."""
    return trace.get_tracer(name or "prguard")


__all__ = ["configure_tracing", "get_tracer"]

