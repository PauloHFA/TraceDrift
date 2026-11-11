"""Unit tests for normalizer in tracedrift.normalizer."""

from tracedrift.models import (
    BlueprintLog,
    BlueprintSpan,
    BlueprintSpanStatus,
    BlueprintTrace,
    SpanKindEnum,
    StatusCodeEnum,
)
from tracedrift.normalizer import (
    TraceNormalizer,
    generate_span_id,
    generate_trace_id,
)


def test_deterministic_id_generation() -> None:
    t_id1 = generate_trace_id(seed=42, trace_index=5)
    t_id2 = generate_trace_id(seed=42, trace_index=5)
    assert t_id1 == t_id2
    assert len(t_id1) == 32
    assert int(t_id1, 16) > 0

    s_id1 = generate_span_id(seed=42, trace_index=5, span_index=2)
    s_id2 = generate_span_id(seed=42, trace_index=5, span_index=2)
    assert s_id1 == s_id2
    assert len(s_id1) == 16
    assert int(s_id1, 16) > 0


def test_normalizer_materializes_blueprint() -> None:
    normalizer = TraceNormalizer(seed=42, auto_fix=True)

    blueprint = BlueprintTrace(
        scenario="E-Commerce Order Test",
        anomaly_type="normal",
        spans=[
            BlueprintSpan(
                ref="s1",
                parent_ref=None,
                service_name="api-gateway",
                name="POST /checkout",
                kind=SpanKindEnum.SERVER,
                offset_ms=0,
                duration_ms=200.0,
                status=BlueprintSpanStatus(code=StatusCodeEnum.OK),
                attributes={"http.method": "POST", "http.status_code": 200},
            ),
            BlueprintSpan(
                ref="s2",
                parent_ref="s1",
                service_name="order-service",
                name="create_order",
                kind=SpanKindEnum.CLIENT,
                offset_ms=10.0,
                duration_ms=100.0,
                status=BlueprintSpanStatus(code=StatusCodeEnum.OK),
            ),
        ],
        logs=[
            BlueprintLog(
                span_ref="s2",
                severity="INFO",
                body="Order created successfully",
                offset_ms=50.0,
            )
        ],
    )

    base_time_nano = 1700000000000000000
    internal, adjustments = normalizer.normalize(blueprint, trace_index=1, base_time_unix_nano=base_time_nano)

    assert internal.trace_id == generate_trace_id(42, 1)
    assert len(internal.spans) == 2
    assert len(internal.logs) == 1

    root_span = next(s for s in internal.spans if s.parent_span_id is None)
    child_span = next(s for s in internal.spans if s.parent_span_id is not None)

    assert root_span.start_time_unix_nano == base_time_nano
    assert root_span.end_time_unix_nano == base_time_nano + int(200.0 * 1_000_000)
    assert child_span.start_time_unix_nano == base_time_nano + int(10.0 * 1_000_000)
    assert child_span.end_time_unix_nano == base_time_nano + int(110.0 * 1_000_000)

    # Check semantic attributes modernization
    assert "http.request.method" in root_span.attributes
    assert root_span.attributes["http.request.method"] == "POST"
    assert "http.response.status_code" in root_span.attributes
    assert root_span.attributes["http.response.status_code"] == 200


def test_normalizer_auto_fix_minor_violation() -> None:
    normalizer = TraceNormalizer(seed=42, auto_fix=True)

    # Parent is 100ms. Child starts at 10ms and lasts 93ms (total 103ms -> 3% overflow <= 5%)
    blueprint = BlueprintTrace(
        scenario="Minor Overflow Test",
        anomaly_type="normal",
        spans=[
            BlueprintSpan(
                ref="s1",
                parent_ref=None,
                service_name="api-gateway",
                name="POST /checkout",
                kind=SpanKindEnum.SERVER,
                offset_ms=0,
                duration_ms=100.0,
            ),
            BlueprintSpan(
                ref="s2",
                parent_ref="s1",
                service_name="order-service",
                name="process",
                kind=SpanKindEnum.INTERNAL,
                offset_ms=10.0,
                duration_ms=93.0,  # 10 + 93 = 103ms > 100ms, but <= 5%
            ),
        ],
    )

    base_time_nano = 1700000000000000000
    internal, adjustments = normalizer.normalize(blueprint, trace_index=0, base_time_unix_nano=base_time_nano)

    root = internal.spans[0]
    child = internal.spans[1]

    # After auto-fix, child should be clamped to parent end
    assert child.end_time_unix_nano <= root.end_time_unix_nano
    assert len(adjustments) > 0
