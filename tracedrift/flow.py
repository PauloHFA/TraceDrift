"""Parser and validator for flow.yaml definitions."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import networkx as nx
import yaml
from pydantic import ValidationError

from tracedrift.models import FlowDefinition, ProtocolEnum


class FlowValidationError(Exception):
    """Raised when a flow definition fails semantic validation."""


def load_flow_from_dict(raw_data: dict[str, Any]) -> FlowDefinition:
    """Parses and validates a dictionary into a FlowDefinition."""
    if not isinstance(raw_data, dict):
        raise FlowValidationError("O arquivo de fluxo deve ser um mapeamento YAML válido.")

    try:
        flow = FlowDefinition.model_validate(raw_data)
    except ValidationError as err:
        error_details = []
        for e in err.errors():
            loc = " -> ".join(str(item) for item in e.get("loc", []))
            msg = e.get("msg", "")
            error_details.append(f"Campo '{loc}': {msg}")
        raise FlowValidationError(
            "Erro de validação do schema do fluxo:\n" + "\n".join(f" - {d}" for d in error_details)
        ) from err

    # Semantic cross-validation
    service_names = {s.name for s in flow.services}

    if not flow.steps:
        raise FlowValidationError("O fluxo deve conter pelo menos um passo ('steps').")

    for idx, step in enumerate(flow.steps):
        if step.service not in service_names:
            raise FlowValidationError(
                f"Passo #{idx + 1} ('{step.name}') referencia serviço de origem inexistente: '{step.service}'. "
                f"Serviços válidos: {sorted(service_names)}."
            )
        if step.target_service and step.target_service not in service_names:
            raise FlowValidationError(
                f"Passo #{idx + 1} ('{step.name}') referencia serviço de destino inexistente: '{step.target_service}'. "
                f"Serviços válidos: {sorted(service_names)}."
            )

        # Protocol check for async
        if step.is_async and step.protocol not in (
            ProtocolEnum.AMQP,
            ProtocolEnum.HTTP,
            ProtocolEnum.GRPC,
        ):
            raise FlowValidationError(
                f"Passo assíncrono '{step.name}' deve utilizar protocolo de mensageria ou RPC (ex: AMQP, HTTP)."
            )

    return flow


def load_flow_from_file(file_path: str | Path) -> FlowDefinition:
    """Reads a YAML file from disk and parses it into a FlowDefinition."""
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"Arquivo de fluxo não encontrado: {path}")

    try:
        with open(path, encoding="utf-8") as f:
            raw = yaml.safe_load(f)
    except yaml.YAMLError as err:
        raise FlowValidationError(f"Erro ao parsear arquivo YAML '{path}': {err}") from err

    return load_flow_from_dict(raw)


def build_service_graph(flow: FlowDefinition) -> nx.DiGraph:
    """Constructs a NetworkX directed graph representing service interactions."""
    graph = nx.DiGraph()

    for service in flow.services:
        graph.add_node(service.name, technology=service.technology, tier=service.tier)

    for step in flow.steps:
        if step.target_service:
            graph.add_edge(
                step.service,
                step.target_service,
                step_name=step.name,
                operation=step.operation,
                protocol=step.protocol.value,
                is_async=step.is_async,
            )

    return graph
