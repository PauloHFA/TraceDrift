"""Direct OTLP dispatcher supporting both HTTP (4318) and native gRPC (4317)."""

from __future__ import annotations

import json
from typing import Any

import grpc
import httpx
from google.protobuf import json_format
from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest
from opentelemetry.proto.collector.trace.v1.trace_service_pb2_grpc import TraceServiceStub
from opentelemetry.proto.trace.v1.trace_pb2 import TracesData


class OTLPSendError(Exception):
    """Raised when sending traces to a collector fails."""


def send_otlp_http(endpoint: str, payload: dict[str, Any], timeout: float = 30.0) -> int:
    """Dispatches traces JSON payload via OTLP/HTTP."""
    try:
        with httpx.Client(timeout=timeout) as client:
            resp = client.post(
                endpoint,
                json=payload,
                headers={"Content-Type": "application/json"},
            )
        if resp.status_code not in (200, 202):
            raise OTLPSendError(f"O coletor OTLP HTTP retornou código {resp.status_code}: {resp.text}")
        return resp.status_code
    except httpx.HTTPError as err:
        raise OTLPSendError(f"Falha de conexão OTLP HTTP com '{endpoint}': {err}") from err


def send_otlp_grpc(endpoint: str, payload: dict[str, Any], timeout: float = 30.0) -> None:
    """Dispatches traces via native OTLP/gRPC using protobuf stubs."""
    # Strip protocol prefix if provided
    clean_endpoint = endpoint.replace("grpc://", "").replace("http://", "").replace("https://", "")
    if "/" in clean_endpoint:
        clean_endpoint = clean_endpoint.split("/")[0]

    json_str = json.dumps(payload)
    traces_data = TracesData()
    try:
        json_format.Parse(json_str, traces_data)
    except Exception as err:
        raise OTLPSendError(f"Erro ao converter JSON para Protobuf OTLP: {err}") from err

    request = ExportTraceServiceRequest(resource_spans=traces_data.resource_spans)

    try:
        with grpc.insecure_channel(clean_endpoint) as channel:
            stub = TraceServiceStub(channel)  # type: ignore[no-untyped-call]
            stub.Export(request, timeout=timeout)
    except grpc.RpcError as err:
        raise OTLPSendError(f"Falha na chamada gRPC para '{clean_endpoint}': {err.details() if hasattr(err, 'details') else err}") from err
