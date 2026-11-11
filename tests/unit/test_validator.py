"""Unit tests for validator in tracedrift.validator."""

from tracedrift.models import (
    GenerationMetadata,
    InternalLog,
    InternalSpan,
    InternalTrace,
    TraceLabel,
)
from tracedrift.validator import TraceValidator


def test_validator_layer1_and_2_blueprint() -> None:
    validator = TraceValidator()

    # Valid blueprint dictionary
    valid_raw = {
        "scenario": "Valid Flow",
        "anomaly_type": "normal",
        "spans": [
            {
                "ref": "s1",
                "parent_ref": None,
                "service_name": "srv1",
                "name": "op1",
                "kind": "SERVER",
                "offset_ms": 0,
                "duration_ms": 100,
            },
            {
                "ref": "s2",
                "parent_ref": "s1",
                "service_name": "srv2",
                "name": "op2",
                "kind": "CLIENT",
                "offset_ms": 10,
                "duration_ms": 50,
            },
        ],
    }
    bp, report = validator.validate_blueprint(valid_raw)
    assert report.is_valid is True
    assert bp is not None

    # Invalid: missing parent
    missing_parent_raw = dict(valid_raw)
    missing_parent_raw["spans"] = [
        {
            "ref": "s2",
            "parent_ref": "nonexistent",
            "service_name": "srv2",
            "name": "op2",
            "kind": "CLIENT",
            "offset_ms": 10,
            "duration_ms": 50,
        }
    ]
    _, report_err = validator.validate_blueprint(missing_parent_raw)
    assert report_err.is_valid is False
    assert report_err.layer_failed in (1, 2)


def test_validator_layer3_temporal_violation() -> None:
    validator = TraceValidator()

    # Synchronous child ends after parent
    invalid_trace = InternalTrace(
        trace_id="4bf92f3577b34da6a3ce929d0e0e4736",
        spans=[
            InternalSpan(
                trace_id="4bf92f3577b34da6a3ce929d0e0e4736",
                span_id="0000000000000001",
                parent_span_id=None,
                name="root",
                service_name="srv-root",
                kind="SPAN_KIND_SERVER",
                start_time_unix_nano=1000,
                end_time_unix_nano=2000,
            ),
            InternalSpan(
                trace_id="4bf92f3577b34da6a3ce929d0e0e4736",
                span_id="0000000000000002",
                parent_span_id="0000000000000001",
                name="child_sync",
                service_name="srv-child",
                kind="SPAN_KIND_CLIENT",
                start_time_unix_nano=1500,
                end_time_unix_nano=2500,  # 2500 > 2000! Violation
            ),
        ],
        label=TraceLabel(
            trace_id="4bf92f3577b34da6a3ce929d0e0e4736",
            anomaly_type="normal",
            is_anomalous=False,
        ),
        metadata=GenerationMetadata(model="test", prompt_version="v1", seed=42),
    )

    report = validator.validate_materialized_trace(invalid_trace)
    assert report.is_valid is False
    assert report.layer_failed == 3
    assert any("Violação temporal" in e for e in report.errors)


def test_validator_layer3_async_consumer_allowed_after_producer_ends() -> None:
    validator = TraceValidator()

    # Async consumer ends after producer ends (allowed by RNF01 exception!)
    async_trace = InternalTrace(
        trace_id="4bf92f3577b34da6a3ce929d0e0e4736",
        spans=[
            InternalSpan(
                trace_id="4bf92f3577b34da6a3ce929d0e0e4736",
                span_id="0000000000000001",
                parent_span_id=None,
                name="publish_event",
                service_name="producer",
                kind="SPAN_KIND_PRODUCER",
                start_time_unix_nano=1000,
                end_time_unix_nano=2000,
            ),
            InternalSpan(
                trace_id="4bf92f3577b34da6a3ce929d0e0e4736",
                span_id="0000000000000002",
                parent_span_id="0000000000000001",
                name="consume_event",
                service_name="consumer",
                kind="SPAN_KIND_CONSUMER",
                start_time_unix_nano=2100,  # Starts after producer ends
                end_time_unix_nano=3500,  # Ends well after producer
                links=[
                    {"trace_id": "4bf92f3577b34da6a3ce929d0e0e4736", "span_id": "0000000000000001"}
                ],
            ),
        ],
        label=TraceLabel(
            trace_id="4bf92f3577b34da6a3ce929d0e0e4736",
            anomaly_type="normal",
            is_anomalous=False,
        ),
        metadata=GenerationMetadata(model="test", prompt_version="v1", seed=42),
    )

    report = validator.validate_materialized_trace(async_trace)
    assert report.is_valid is True


def test_validator_layer4_detects_real_public_ip() -> None:
    validator = TraceValidator()

    # Trace containing real public IP (e.g. 8.8.8.8)
    trace = InternalTrace(
        trace_id="4bf92f3577b34da6a3ce929d0e0e4736",
        spans=[
            InternalSpan(
                trace_id="4bf92f3577b34da6a3ce929d0e0e4736",
                span_id="0000000000000001",
                parent_span_id=None,
                name="root",
                service_name="gateway",
                kind="SPAN_KIND_SERVER",
                start_time_unix_nano=1000,
                end_time_unix_nano=2000,
                attributes={"client.address": "8.8.8.8"},  # Real public IP!
            )
        ],
        label=TraceLabel(
            trace_id="4bf92f3577b34da6a3ce929d0e0e4736",
            anomaly_type="normal",
            is_anomalous=False,
        ),
        metadata=GenerationMetadata(model="test", prompt_version="v1", seed=42),
    )

    report = validator.validate_materialized_trace(trace)
    assert report.is_valid is False
    assert report.layer_failed == 4
    assert any("IP público real detectado" in e for e in report.errors)


def test_validator_layer2_detects_cycle() -> None:
    validator = TraceValidator()
    cyclic_raw = {
        "scenario": "Cycle Scenario",
        "anomaly_type": "normal",
        "spans": [
            {
                "ref": "s1",
                "parent_ref": "s2",  # Cycle s1 -> s2 -> s1
                "service_name": "srv",
                "name": "op1",
                "kind": "SERVER",
                "offset_ms": 0,
                "duration_ms": 100,
            },
            {
                "ref": "s2",
                "parent_ref": "s1",
                "service_name": "srv",
                "name": "op2",
                "kind": "CLIENT",
                "offset_ms": 10,
                "duration_ms": 50,
            },
        ],
    }
    _, report = validator.validate_blueprint(cyclic_raw)
    assert report.is_valid is False
    assert report.layer_failed == 1 or report.layer_failed == 2


def test_validator_layer4_detects_real_email_and_secrets() -> None:
    validator = TraceValidator()
    # Trace containing AWS Secret Key and a real corporate email
    trace = InternalTrace(
        trace_id="4bf92f3577b34da6a3ce929d0e0e4736",
        spans=[
            InternalSpan(
                trace_id="4bf92f3577b34da6a3ce929d0e0e4736",
                span_id="0000000000000001",
                parent_span_id=None,
                name="root",
                service_name="auth",
                kind="SPAN_KIND_SERVER",
                start_time_unix_nano=1000,
                end_time_unix_nano=2000,
                attributes={"user.email": "john.doe@corporate-bank.com.br"},
            )
        ],
        logs=[
            InternalLog(
                trace_id="4bf92f3577b34da6a3ce929d0e0e4736",
                span_id="0000000000000001",
                timestamp_unix_nano=1500,
                severity_text="INFO",
                severity_number=9,
                body="Using access key AKIAIOSFODNN7EXAMPLE for S3",
                service_name="auth",
            )
        ],
        label=TraceLabel(
            trace_id="4bf92f3577b34da6a3ce929d0e0e4736",
            anomaly_type="normal",
            is_anomalous=False,
        ),
        metadata=GenerationMetadata(model="test", prompt_version="v1", seed=42),
    )

    report = validator.validate_materialized_trace(trace)
    assert report.is_valid is False
    assert report.layer_failed == 4
    assert any("E-mail com domínio real" in e for e in report.errors)
    assert any("credencial/token sensível" in e for e in report.errors)
