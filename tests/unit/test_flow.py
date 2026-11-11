"""Unit tests for flow loading and validation in tracedrift.flow."""

import pytest

from tracedrift.flow import (
    FlowValidationError,
    build_service_graph,
    load_flow_from_dict,
    load_flow_from_file,
)


def test_load_ecommerce_flow() -> None:
    flow = load_flow_from_file("configs/e_commerce_flow.yaml")
    assert flow.name == "E-Commerce Checkout Flow"
    assert len(flow.services) == 6
    assert len(flow.steps) == 5

    graph = build_service_graph(flow)
    assert "api-gateway" in graph.nodes
    assert "order-service" in graph.nodes
    assert graph.has_edge("api-gateway", "order-service")


def test_load_fintech_flow() -> None:
    flow = load_flow_from_file("configs/fintech_flow.yaml")
    assert flow.name == "Fintech Transfer Flow"
    assert len(flow.services) == 6
    assert len(flow.steps) == 5

    # Check async step
    async_step = next(s for s in flow.steps if s.is_async)
    assert async_step.protocol.value == "AMQP"


def test_flow_missing_service_fails() -> None:
    raw = {
        "name": "Invalid Flow",
        "services": [{"name": "srv-a", "technology": "python"}],
        "steps": [
            {
                "name": "step-1",
                "service": "srv-missing",  # Non-existent
                "operation": "op",
                "protocol": "HTTP",
                "target_service": "srv-a",
                "is_async": False,
            }
        ],
    }
    with pytest.raises(FlowValidationError, match="referencia serviço de origem inexistente"):
        load_flow_from_dict(raw)


def test_flow_missing_target_service_fails() -> None:
    raw = {
        "name": "Invalid Target Flow",
        "services": [{"name": "srv-a", "technology": "python"}],
        "steps": [
            {
                "name": "step-1",
                "service": "srv-a",
                "operation": "op",
                "protocol": "HTTP",
                "target_service": "srv-unknown",  # Non-existent
                "is_async": False,
            }
        ],
    }
    with pytest.raises(FlowValidationError, match="referencia serviço de destino inexistente"):
        load_flow_from_dict(raw)


def test_flow_empty_steps_fails() -> None:
    raw = {
        "name": "Empty Steps Flow",
        "services": [{"name": "srv-a", "technology": "python"}],
        "steps": [],
    }
    with pytest.raises(FlowValidationError):
        load_flow_from_dict(raw)
