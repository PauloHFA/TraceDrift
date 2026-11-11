"""Exporters for internal JSONL and canonical OTLP/JSON formats."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import aiofiles
from google.protobuf import json_format
from opentelemetry.proto.logs.v1.logs_pb2 import LogsData
from opentelemetry.proto.trace.v1.trace_pb2 import TracesData

from tracedrift.models import InternalLog, InternalSpan, InternalTrace, SpanKindEnum, StatusCodeEnum


def _to_any_value(val: Any) -> dict[str, Any]:
    """Converts a Python value into an OTLP AnyValue protobuf-compatible dict."""
    if isinstance(val, bool):
        return {"boolValue": val}
    if isinstance(val, int):
        return {"intValue": val}
    if isinstance(val, float):
        return {"doubleValue": val}
    if isinstance(val, (list, tuple)):
        return {"arrayValue": {"values": [_to_any_value(v) for v in val]}}
    if isinstance(val, dict):
        return {
            "kvlistValue": {
                "values": [{"key": k, "value": _to_any_value(v)} for k, v in val.items()]
            }
        }
    return {"stringValue": str(val)}


def _attributes_to_otlp(attrs: dict[str, Any]) -> list[dict[str, Any]]:
    """Converts a dictionary of attributes into OTLP KeyValue list."""
    return [{"key": k, "value": _to_any_value(v)} for k, v in attrs.items()]


def convert_span_to_otlp(span: InternalSpan) -> dict[str, Any]:
    """Converts an InternalSpan into an OTLP Span JSON structure."""
    kind_num = 1
    for k in SpanKindEnum:
        if k.to_otlp_name() == span.kind:
            kind_num = k.to_otlp_number()
            break

    status_code_str = span.status.get("code", "OK")
    status_code_num = 1
    if status_code_str == StatusCodeEnum.ERROR.value:
        status_code_num = 2
    elif status_code_str == StatusCodeEnum.UNSET.value:
        status_code_num = 0

    otlp_status: dict[str, Any] = {"code": status_code_num}
    if span.status.get("message"):
        otlp_status["message"] = span.status["message"]

    otlp_events = []
    for ev in span.events:
        otlp_events.append(
            {
                "timeUnixNano": str(ev.get("time_unix_nano", span.start_time_unix_nano)),
                "name": ev.get("name", "event"),
                "attributes": _attributes_to_otlp(ev.get("attributes", {})),
            }
        )

    otlp_links = []
    for lk in span.links:
        otlp_links.append(
            {
                "traceId": lk.get("trace_id", span.trace_id),
                "spanId": lk.get("span_id", ""),
                "attributes": _attributes_to_otlp(lk.get("attributes", {})),
            }
        )

    span_dict: dict[str, Any] = {
        "traceId": span.trace_id,
        "spanId": span.span_id,
        "name": span.name,
        "kind": kind_num,
        "startTimeUnixNano": str(span.start_time_unix_nano),
        "endTimeUnixNano": str(span.end_time_unix_nano),
        "attributes": _attributes_to_otlp(span.attributes),
        "events": otlp_events,
        "links": otlp_links,
        "status": otlp_status,
    }

    if span.parent_span_id:
        span_dict["parentSpanId"] = span.parent_span_id

    return span_dict


def convert_log_to_otlp(log: InternalLog) -> dict[str, Any]:
    """Converts an InternalLog into an OTLP LogRecord JSON structure."""
    return {
        "timeUnixNano": str(log.timestamp_unix_nano),
        "severityNumber": log.severity_number,
        "severityText": log.severity_text,
        "body": {"stringValue": log.body},
        "attributes": _attributes_to_otlp(log.attributes),
        "traceId": log.trace_id,
        "spanId": log.span_id,
    }


def convert_trace_to_otlp_json(trace: InternalTrace) -> dict[str, Any]:
    """Groups spans by service and converts to an OTLP TracesData JSON structure."""
    spans_by_service: dict[str, list[dict[str, Any]]] = {}
    for span in trace.spans:
        spans_by_service.setdefault(span.service_name, []).append(convert_span_to_otlp(span))

    resource_spans = []
    for service_name, otlp_spans in spans_by_service.items():
        res_attrs = [
            {"key": "service.name", "value": {"stringValue": service_name}},
            {"key": "deployment.environment", "value": {"stringValue": "synthetic"}},
            {"key": "tracedrift.generated", "value": {"boolValue": True}},
        ]
        resource_spans.append(
            {
                "resource": {"attributes": res_attrs},
                "scopeSpans": [
                    {
                        "scope": {"name": "tracedrift", "version": "0.1.0"},
                        "spans": otlp_spans,
                    }
                ],
            }
        )

    return {"resourceSpans": resource_spans}


def convert_logs_to_otlp_json(logs: list[InternalLog]) -> dict[str, Any]:
    """Groups logs by service and converts to an OTLP LogsData JSON structure."""
    logs_by_service: dict[str, list[dict[str, Any]]] = {}
    for log in logs:
        logs_by_service.setdefault(log.service_name, []).append(convert_log_to_otlp(log))

    resource_logs = []
    for service_name, otlp_logs in logs_by_service.items():
        res_attrs = [
            {"key": "service.name", "value": {"stringValue": service_name}},
            {"key": "deployment.environment", "value": {"stringValue": "synthetic"}},
            {"key": "tracedrift.generated", "value": {"boolValue": True}},
        ]
        resource_logs.append(
            {
                "resource": {"attributes": res_attrs},
                "scopeLogs": [
                    {
                        "scope": {"name": "tracedrift", "version": "0.1.0"},
                        "logRecords": otlp_logs,
                    }
                ],
            }
        )

    return {"resourceLogs": resource_logs}


def validate_otlp_conformance(otlp_traces_data: dict[str, Any]) -> bool:
    """Verifies that the generated dictionary can be parsed by official OTLP protobuf parser."""
    json_str = json.dumps(otlp_traces_data)
    message = TracesData()
    json_format.Parse(json_str, message)
    return True


def validate_otlp_logs_conformance(otlp_logs_data: dict[str, Any]) -> bool:
    """Verifies that the generated logs dictionary can be parsed by official OTLP protobuf parser."""
    json_str = json.dumps(otlp_logs_data)
    message = LogsData()
    json_format.Parse(json_str, message)
    return True


class StreamingTraceExporter:
    """Async streaming file exporter for datasets."""

    def __init__(self, output_dir: str | Path) -> None:
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

        self.traces_path = self.output_dir / "traces.jsonl"
        self.labels_path = self.output_dir / "labels.jsonl"
        self.otlp_traces_path = self.output_dir / "otlp_traces.json"
        self.otlp_logs_path = self.output_dir / "otlp_logs.json"

        self._all_resource_spans: list[dict[str, Any]] = []
        self._all_resource_logs: list[dict[str, Any]] = []

    async def write_trace(self, trace: InternalTrace) -> None:
        """Appends a trace to traces.jsonl, labels.jsonl, and accumulates OTLP data."""
        # 1. Internal traces.jsonl
        async with aiofiles.open(self.traces_path, "a", encoding="utf-8") as f:
            await f.write(trace.model_dump_json() + "\n")

        # 2. labels.jsonl
        async with aiofiles.open(self.labels_path, "a", encoding="utf-8") as f:
            await f.write(trace.label.model_dump_json() + "\n")

        # 3. Accumulate OTLP
        otlp_trace_dict = convert_trace_to_otlp_json(trace)
        self._all_resource_spans.extend(otlp_trace_dict.get("resourceSpans", []))

        if trace.logs:
            otlp_logs_dict = convert_logs_to_otlp_json(trace.logs)
            self._all_resource_logs.extend(otlp_logs_dict.get("resourceLogs", []))

    async def finalize(self) -> None:
        """Writes the consolidated OTLP JSON files."""
        # Write otlp_traces.json
        traces_payload = {"resourceSpans": self._all_resource_spans}
        async with aiofiles.open(self.otlp_traces_path, "w", encoding="utf-8") as f:
            await f.write(json.dumps(traces_payload, indent=2))

        # Write otlp_logs.json
        logs_payload = {"resourceLogs": self._all_resource_logs}
        async with aiofiles.open(self.otlp_logs_path, "w", encoding="utf-8") as f:
            await f.write(json.dumps(logs_payload, indent=2))
