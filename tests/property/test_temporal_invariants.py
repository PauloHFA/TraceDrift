"""Property-based tests with Hypothesis verifying temporal invariants (RNF01)."""

import hypothesis.strategies as st
from hypothesis import given, settings

from tracedrift.models import (
    BlueprintSpan,
    BlueprintTrace,
    SpanKindEnum,
)
from tracedrift.normalizer import TraceNormalizer
from tracedrift.validator import TraceValidator


@st.composite
def random_blueprint_tree(draw: st.DrawFn) -> BlueprintTrace:
    """Hypothesis strategy generating arbitrary valid blueprint hierarchies."""
    num_spans = draw(st.integers(min_value=2, max_value=8))

    root_duration = draw(st.floats(min_value=50.0, max_value=1000.0))
    spans: list[BlueprintSpan] = [
        BlueprintSpan(
            ref="s0",
            parent_ref=None,
            service_name="root-service",
            name="root-op",
            kind=SpanKindEnum.SERVER,
            offset_ms=0,
            duration_ms=root_duration,
        )
    ]

    for i in range(1, num_spans):
        # Pick parent from already created spans
        parent_idx = draw(st.integers(min_value=0, max_value=i - 1))
        parent = spans[parent_idx]

        # Select child kind
        kind = draw(st.sampled_from(list(SpanKindEnum)))

        if kind in (SpanKindEnum.CONSUMER, SpanKindEnum.PRODUCER):
            # Async consumer/producer
            offset = draw(st.floats(min_value=0.0, max_value=parent.duration_ms + 20.0))
            duration = draw(st.floats(min_value=5.0, max_value=50.0))
        else:
            # Sync child contained in parent (with up to 4% small jitter to test auto-fix)
            offset_pct = draw(st.floats(min_value=0.0, max_value=0.5))
            offset = parent.duration_ms * offset_pct
            max_dur_pct = 1.04 - offset_pct
            dur_pct = draw(st.floats(min_value=0.05, max_value=max_dur_pct))
            duration = max(0.001, parent.duration_ms * dur_pct)

        spans.append(
            BlueprintSpan(
                ref=f"s{i}",
                parent_ref=parent.ref,
                service_name=f"svc-{i}",
                name=f"op-{i}",
                kind=kind,
                offset_ms=offset,
                duration_ms=duration,
            )
        )

    return BlueprintTrace(
        scenario="Hypothesis Fuzzing Scenario",
        anomaly_type="normal",
        spans=spans,
    )


@given(blueprint=random_blueprint_tree(), seed=st.integers(min_value=1, max_value=10000))
@settings(max_examples=50, deadline=None)
def test_temporal_invariants_hold_after_normalization(blueprint: BlueprintTrace, seed: int) -> None:
    normalizer = TraceNormalizer(seed=seed, auto_fix=True)
    validator = TraceValidator()

    base_time_nano = 1700000000000000000
    internal, _ = normalizer.normalize(
        blueprint=blueprint,
        trace_index=0,
        base_time_unix_nano=base_time_nano,
    )

    report = validator.validate_materialized_trace(internal)
    # Temporal invariants (Layer 3) must pass 100% of the time (RNF01)
    if not report.is_valid:
        assert report.layer_failed != 3, f"Violação de RNF01 encontrada: {report.errors}"
