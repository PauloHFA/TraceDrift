"""Unit tests for OTLP sender in tracedrift.sender."""

from unittest.mock import MagicMock, patch

import httpx
import pytest
import respx

from tracedrift.sender import OTLPSendError, send_otlp_grpc, send_otlp_http


@respx.mock
def test_send_otlp_http_success() -> None:
    respx.post("http://localhost:4318/v1/traces").mock(
        return_value=httpx.Response(200, json={"status": "OK"})
    )
    status = send_otlp_http("http://localhost:4318/v1/traces", {"resourceSpans": []})
    assert status == 200


@respx.mock
def test_send_otlp_http_failure_raises() -> None:
    respx.post("http://localhost:4318/v1/traces").mock(
        return_value=httpx.Response(500, text="Internal Collector Error")
    )
    with pytest.raises(OTLPSendError, match="código 500"):
        send_otlp_http("http://localhost:4318/v1/traces", {"resourceSpans": []})


@patch("tracedrift.sender.grpc.insecure_channel")
@patch("tracedrift.sender.TraceServiceStub")
def test_send_otlp_grpc_success(mock_stub_cls: MagicMock, _mock_channel: MagicMock) -> None:
    mock_stub = MagicMock()
    mock_stub_cls.return_value = mock_stub

    send_otlp_grpc("localhost:4317", {"resourceSpans": []})
    mock_stub.Export.assert_called_once()
