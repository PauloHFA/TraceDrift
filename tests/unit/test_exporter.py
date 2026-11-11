"""Unit tests for exporter in tracedrift.exporter."""

import json
from pathlib import Path

import pytest
from google.protobuf import json_format
from opentelemetry.proto.logs.v1.logs_pb2 import LogsData
from opentelemetry.proto.trace.v1.trace_pb2 import TracesData

from tracedrift.exporter import (
    StreamingTraceExporter,
    convert_logs_to_otlp_json,
    convert_trace_to_otlp_json,
    validate_otlp_conformance,
    validate_otlp_logs_conformance,
)
from tracedrift.models import (
    GenerationMetadata,
    InternalLog,
    InternalSpan,
    InternalTrace,
    TraceLabel,
)


@pytest.fixture
def sample_internal_trace() -> InternalTrace:
    return InternalTrace(
        trace_id="4bf92f3577b34da6a3ce929d0e0e4736",
        spans=[
            InternalSpan(
                trace_id="4bf92f3577b34da6a3ce929d0e0e4736",
                span_id="0000000000000001",
                parent_span_id=None,
                name="POST /checkout",
                service_name="api-gateway",
                kind="SPAN_KIND_SERVER",
                start_time_unix_nano=1700000000000000000,
                end_time_unix_nano=1700000000200000000,
                status={"code": "OK"},
                attributes={
                    "http.request.method": "POST",
                    "http.response.status_code": 200,
                    "retry.count": 0,
                    "is_cached": False,
                },
                events=[
                    {
                        "name": "cache_lookup",
                        "time_unix_nano": 1700000000050000000,
                        "attributes": {"cache.hit": False},
                    }
                ],
                links=[
                    {
                        "trace_id": "4bf92f3577b34da6a3ce929d0e0e4736",
                        "span_id": "0000000000000002",
                        "attributes": {},
                    }
                ],
            )
        ],
        logs=[
            InternalLog(
                trace_id="4bf92f3577b34da6a3ce929d0e0e4736",
                span_id="0000000000000001",
                timestamp_unix_nano=1700000000100000000,
                severity_text="INFO",
                severity_number=9,
                body="Order started",
                service_name="api-gateway",
                attributes={"user_id": "usr_123"},
            )
        ],
        label=TraceLabel(
            trace_id="4bf92f3577b34da6a3ce929d0e0e4736",
            anomaly_type="normal",
            is_anomalous=False,
        ),
        metadata=GenerationMetadata(model="test-model", prompt_version="v1", seed=42),
    )


def test_otlp_json_protobuf_conformance(sample_internal_trace: InternalTrace) -> None:
    otlp_dict = convert_trace_to_otlp_json(sample_internal_trace)
    assert validate_otlp_conformance(otlp_dict) is True

    # Check direct google protobuf Parse
    json_str = json.dumps(otlp_dict)
    proto_msg = TracesData()
    json_format.Parse(json_str, proto_msg)
    assert len(proto_msg.resource_spans) == 1
    assert proto_msg.resource_spans[0].scope_spans[0].spans[0].name == "POST /checkout"


def test_otlp_logs_protobuf_conformance(sample_internal_trace: InternalTrace) -> None:
    otlp_logs = convert_logs_to_otlp_json(sample_internal_trace.logs)
    assert validate_otlp_logs_conformance(otlp_logs) is True

    json_str = json.dumps(otlp_logs)
    proto_msg = LogsData()
    json_format.Parse(json_str, proto_msg)
    assert len(proto_msg.resource_logs) == 1
    assert proto_msg.resource_logs[0].scope_logs[0].log_records[0].severity_text == "INFO"


@pytest.mark.asyncio
async def test_streaming_exporter_writes_files(
    sample_internal_trace: InternalTrace, tmp_path: Path
) -> None:
    exporter = StreamingTraceExporter(output_dir=tmp_path)
    await exporter.write_trace(sample_internal_trace)
    await exporter.finalize()

    assert (tmp_path / "traces.jsonl").exists()
    assert (tmp_path / "labels.jsonl").exists()
    assert (tmp_path / "otlp_traces.json").exists()
    assert (tmp_path / "otlp_logs.json").exists()

    with open(tmp_path / "traces.jsonl", encoding="utf-8") as f:
        lines = f.readlines()
        assert len(lines) == 1
        data = json.loads(lines[0])
        assert data["trace_id"] == sample_internal_trace.trace_id

    with open(tmp_path / "otlp_traces.json", encoding="utf-8") as f:
        otlp_data = json.load(f)
        assert validate_otlp_conformance(otlp_data) is True
