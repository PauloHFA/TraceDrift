"""Dogfooding observability: Self-tracing for TraceDrift execution."""

from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager
from typing import Any

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

_TRACER_INITIALIZED = False


def setup_self_tracing(
    enabled: bool = False, service_name: str = "tracedrift"
) -> trace.Tracer | None:
    """Initializes OpenTelemetry tracer for dogfooding self-trace."""
    global _TRACER_INITIALIZED
    if not enabled:
        return None

    if not _TRACER_INITIALIZED:
        resource = Resource.create(
            {
                "service.name": service_name,
                "service.version": "0.1.0",
                "deployment.environment": "cli-dogfooding",
            }
        )
        provider = TracerProvider(resource=resource)
        provider.add_span_processor(SimpleSpanProcessor(InMemorySpanExporter()))
        trace.set_tracer_provider(provider)
        _TRACER_INITIALIZED = True

    return trace.get_tracer("tracedrift.self_trace", "0.1.0")


@contextmanager
def self_span(
    name: str,
    tracer: trace.Tracer | None = None,
    attributes: dict[str, Any] | None = None,
) -> Generator[trace.Span | None, None, None]:
    """Context manager for tracing internal TraceDrift execution blocks."""
    if tracer is None:
        yield None
        return

    with tracer.start_as_current_span(name) as span:
        if attributes:
            for k, v in attributes.items():
                span.set_attribute(k, v)
        yield span
