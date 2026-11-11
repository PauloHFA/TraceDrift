"""Unit tests for Pydantic domain models in tracedrift.models."""

from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from tracedrift.models import (
    AnomalyCatalog,
    BlueprintSpan,
    BlueprintTrace,
    GenerationMetadata,
    InternalSpan,
    InternalTrace,
    SpanKindEnum,
    StatusCodeEnum,
    TraceLabel,
)


def test_span_kind_enum_mappings() -> None:
    assert SpanKindEnum.SERVER.to_otlp_name() == "SPAN_KIND_SERVER"
    assert SpanKindEnum.CLIENT.to_otlp_name() == "SPAN_KIND_CLIENT"
    assert SpanKindEnum.PRODUCER.to_otlp_name() == "SPAN_KIND_PRODUCER"
    assert SpanKindEnum.CONSUMER.to_otlp_name() == "SPAN_KIND_CONSUMER"
    assert SpanKindEnum.INTERNAL.to_otlp_name() == "SPAN_KIND_INTERNAL"

    assert SpanKindEnum.SERVER.to_otlp_number() == 2
    assert SpanKindEnum.CLIENT.to_otlp_number() == 3
    assert StatusCodeEnum.ERROR.to_otlp_number() == 2


def test_anomaly_catalog_loading_from_yaml() -> None:
    path = Path("configs/anomalies_default.yaml")
    assert path.exists(), "configs/anomalies_default.yaml deve existir"

    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f)

    catalog = AnomalyCatalog.model_validate(data)
    assert len(catalog.anomalies) >= 20, "O catálogo padrão deve ter pelo menos 20 anomalias (RF02)"

    ids = [a.id for a in catalog.anomalies]
    assert "retry_storm" in ids
    assert "database_lock_contention" in ids
    assert "circuit_breaker_tripping" in ids
    assert "cascading_timeout" in ids
    assert "thundering_herd" in ids


def test_blueprint_trace_valid() -> None:
    trace = BlueprintTrace(
        scenario="Checkout com Retry Storm",
        anomaly_type="retry_storm",
        spans=[
            BlueprintSpan(
                ref="s1",
                parent_ref=None,
                service_name="api-gateway",
                name="POST /checkout",
                kind=SpanKindEnum.SERVER,
                offset_ms=0,
                duration_ms=500.0,
            ),
            BlueprintSpan(
                ref="s2",
                parent_ref="s1",
                service_name="order-service",
                name="create_order",
                kind=SpanKindEnum.CLIENT,
                offset_ms=10.0,
                duration_ms=450.0,
            ),
        ],
        root_cause_ref="s2",
        root_cause_summary="Downstream falhou causando retries sucessivos",
    )
    assert trace.scenario == "Checkout com Retry Storm"
    assert len(trace.spans) == 2


def test_blueprint_trace_invalid_negative_duration() -> None:
    with pytest.raises(ValidationError):
        BlueprintSpan(
            ref="s1",
            parent_ref=None,
            service_name="api-gateway",
            name="POST /checkout",
            kind=SpanKindEnum.SERVER,
            offset_ms=0,
            duration_ms=-10.0,  # Invalid
        )


def test_internal_trace_serialization() -> None:
    internal = InternalTrace(
        trace_id="4bf92f3577b34da6a3ce929d0e0e4736",
        spans=[
            InternalSpan(
                trace_id="4bf92f3577b34da6a3ce929d0e0e4736",
                span_id="00f067aa0ba902b7",
                parent_span_id=None,
                name="root",
                service_name="frontend",
                kind="SPAN_KIND_SERVER",
                start_time_unix_nano=1700000000000000000,
                end_time_unix_nano=1700000000100000000,
            )
        ],
        label=TraceLabel(
            trace_id="4bf92f3577b34da6a3ce929d0e0e4736",
            anomaly_type="normal",
            is_anomalous=False,
        ),
        metadata=GenerationMetadata(
            model="test-model",
            prompt_version="v1",
            seed=42,
        ),
    )
    dumped = internal.model_dump()
    assert dumped["trace_id"] == "4bf92f3577b34da6a3ce929d0e0e4736"
    assert dumped["metadata"]["synthetic"] is True
