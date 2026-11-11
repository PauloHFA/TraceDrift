"""Unit tests for self-tracing in tracedrift.telemetry."""

from tracedrift.telemetry import self_span, setup_self_tracing


def test_self_tracing_disabled_noop() -> None:
    tracer = setup_self_tracing(enabled=False)
    assert tracer is None
    with self_span("test", tracer=tracer) as span:
        assert span is None


def test_self_tracing_enabled() -> None:
    tracer = setup_self_tracing(enabled=True)
    assert tracer is not None
    with self_span("unit.test", tracer=tracer, attributes={"test.key": "val"}) as span:
        assert span is not None
