"""Pydantic v2 domain models for TraceDrift.

Includes models for Flow Definitions, Anomaly Patterns, Blueprints,
Materialized Internal Traces/Logs, Labels, and Generation Metadata.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


# -----------------------------------------------------------------------------
# Enums
# -----------------------------------------------------------------------------
class ProtocolEnum(StrEnum):
    HTTP = "HTTP"
    GRPC = "GRPC"
    AMQP = "AMQP"
    SQL = "SQL"


class SpanKindEnum(StrEnum):
    SERVER = "SERVER"
    CLIENT = "CLIENT"
    PRODUCER = "PRODUCER"
    CONSUMER = "CONSUMER"
    INTERNAL = "INTERNAL"

    def to_otlp_name(self) -> str:
        return f"SPAN_KIND_{self.value}"

    def to_otlp_number(self) -> int:
        mapping = {
            "INTERNAL": 1,
            "SERVER": 2,
            "CLIENT": 3,
            "PRODUCER": 4,
            "CONSUMER": 5,
        }
        return mapping[self.value]


class StatusCodeEnum(StrEnum):
    UNSET = "UNSET"
    OK = "OK"
    ERROR = "ERROR"

    def to_otlp_number(self) -> int:
        mapping = {"UNSET": 0, "OK": 1, "ERROR": 2}
        return mapping[self.value]


# -----------------------------------------------------------------------------
# Flow & Service Topology Models
# -----------------------------------------------------------------------------
class ServiceNode(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., description="Nome único do serviço")
    technology: str = Field(
        ..., description="Tecnologia utilizada (ex: fastapi, postgres, rabbitmq)"
    )
    tier: str | None = Field(None, description="Camada arquitetural (ex: gateway, backend, db)")


class OperationStep(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., description="Identificador do passo")
    service: str = Field(..., description="Serviço que origina o passo")
    operation: str = Field(..., description="Nome da operação (ex: POST /checkout, SELECT users)")
    protocol: ProtocolEnum = Field(..., description="Protocolo da chamada (HTTP, GRPC, AMQP, SQL)")
    target_service: str | None = Field(
        None, description="Serviço de destino caso haja chamada remota"
    )
    target_operation: str | None = Field(None, description="Operação de destino no serviço remoto")
    is_async: bool = Field(False, description="Indica se a comunicação é assíncrona (mensageria)")
    slo_ms: float | None = Field(None, description="SLO de latência em milissegundos")
    baseline_latency_p50_ms: float = Field(
        20.0, description="Latência típica mediana da linha de base"
    )
    baseline_latency_p99_ms: float = Field(
        100.0, description="Latência percentil 99 da linha de base"
    )


class FlowDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., description="Nome do fluxo de negócio")
    description: str | None = Field(None, description="Descrição do fluxo")
    services: list[ServiceNode] = Field(..., min_length=1, description="Lista de microsserviços")
    steps: list[OperationStep] = Field(..., min_length=1, description="Lista ordenada de passos")


# -----------------------------------------------------------------------------
# Anomaly Catalog Models
# -----------------------------------------------------------------------------
class AnomalyPattern(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(..., description="Identificador único (slug) do padrão de anomalia")
    name: str = Field(..., description="Nome legível da anomalia")
    description: str = Field(..., description="Explicação detalhada do mecanismo de falha")
    applicable_technologies: list[str] = Field(
        ..., description="Tecnologias compatíveis (ex: postgres, redis, http, rabbitmq)"
    )
    signature: dict[str, Any] = Field(
        ..., description="Assinatura esperada (latência, erros, retries, etc.)"
    )
    typical_root_cause_span: str = Field(
        ..., description="Tipo ou nome típico do span causador da anomalia"
    )
    default_severity: str = Field(
        "HIGH", description="Severidade padrão (LOW, MEDIUM, HIGH, CRITICAL)"
    )


class AnomalyCatalog(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: str = Field("1.0.0", description="Versão do catálogo")
    anomalies: list[AnomalyPattern] = Field(
        ..., min_length=20, description="Lista de padrões de anomalia"
    )


# -----------------------------------------------------------------------------
# Blueprint Models (LLM Output)
# -----------------------------------------------------------------------------
class BlueprintSpanStatus(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: StatusCodeEnum = Field(
        default=StatusCodeEnum.OK, description="Código de status OTel (OK, ERROR, UNSET)"
    )
    message: str | None = Field(default=None, description="Mensagem de erro (quando code == ERROR)")


class BlueprintEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., description="Nome do evento (ex: exception)")
    offset_ms: float = Field(..., ge=0, description="Deslocamento relativo ao início do span pai")
    attributes: dict[str, Any] = Field(default_factory=dict, description="Atributos do evento")


class BlueprintLink(BaseModel):
    model_config = ConfigDict(extra="forbid")

    span_ref: str = Field(..., description="Rótulo simbólico do span vinculado")
    attributes: dict[str, Any] = Field(default_factory=dict, description="Atributos do link")


def _default_status() -> BlueprintSpanStatus:
    return BlueprintSpanStatus(code=StatusCodeEnum.OK)


class BlueprintSpan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ref: str = Field(..., description="Rótulo simbólico único do span (ex: s1, s2)")
    parent_ref: str | None = Field(
        None, description="Rótulo do pai. Exatamente um span na árvore deve ter parent_ref=None"
    )
    service_name: str = Field(..., description="Serviço executor (deve existir no flow.yaml)")
    name: str = Field(..., description="Nome da operação")
    kind: SpanKindEnum = Field(
        ..., description="Tipo de span (SERVER, CLIENT, PRODUCER, CONSUMER, INTERNAL)"
    )
    offset_ms: float = Field(
        ..., ge=0, description="Deslocamento relativo ao início do pai (0 para o span raiz)"
    )
    duration_ms: float = Field(..., gt=0, description="Duração do span em milissegundos")
    status: BlueprintSpanStatus = Field(default_factory=_default_status)
    attributes: dict[str, Any] = Field(default_factory=dict)
    events: list[BlueprintEvent] = Field(default_factory=list)
    links: list[BlueprintLink] = Field(default_factory=list)


class BlueprintLog(BaseModel):
    model_config = ConfigDict(extra="forbid")

    span_ref: str = Field(..., description="Rótulo simbólico do span correlacionado")
    severity: str = Field("INFO", description="Severidade do log (DEBUG, INFO, WARN, ERROR, FATAL)")
    body: str = Field(..., description="Mensagem do log")
    offset_ms: float = Field(
        ..., ge=0, description="Deslocamento relativo ao início do span correlacionado"
    )
    attributes: dict[str, Any] = Field(default_factory=dict)


class BlueprintTrace(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scenario: str = Field(..., description="Título descritivo do cenário simulado")
    anomaly_type: str = Field(..., description="ID da anomalia sorteada ou 'normal'")
    spans: list[BlueprintSpan] = Field(..., min_length=1, description="Lista de spans do blueprint")
    logs: list[BlueprintLog] = Field(
        default_factory=list, description="Lista de logs correlacionados"
    )
    root_cause_ref: str | None = Field(
        None, description="Rótulo simbólico do span causador (None para normal)"
    )
    root_cause_summary: str | None = Field(None, description="Diagnóstico descritivo da causa-raiz")


# -----------------------------------------------------------------------------
# Materialized Internal Models
# -----------------------------------------------------------------------------
class InternalSpan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    trace_id: str = Field(..., description="ID do trace em 32 caracteres hexadecimais minúsculos")
    span_id: str = Field(..., description="ID do span em 16 caracteres hexadecimais minúsculos")
    parent_span_id: str | None = Field(
        None, description="ID do span pai em 16 caracteres hexadecimais"
    )
    name: str
    service_name: str
    kind: str = Field(..., description="Ex: SPAN_KIND_SERVER")
    start_time_unix_nano: int = Field(..., description="Instante de início em nanossegundos Unix")
    end_time_unix_nano: int = Field(..., description="Instante de término em nanossegundos Unix")
    status: dict[str, Any] = Field(default_factory=dict)
    attributes: dict[str, Any] = Field(default_factory=dict)
    events: list[dict[str, Any]] = Field(default_factory=list)
    links: list[dict[str, Any]] = Field(default_factory=list)


class InternalLog(BaseModel):
    model_config = ConfigDict(extra="forbid")

    trace_id: str
    span_id: str
    timestamp_unix_nano: int
    severity_text: str
    severity_number: int
    body: str
    service_name: str
    attributes: dict[str, Any] = Field(default_factory=dict)


class TraceLabel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    trace_id: str
    anomaly_type: str
    root_cause_span_id: str | None = None
    affected_services: list[str] = Field(default_factory=list)
    is_anomalous: bool
    severity: str | None = None
    root_cause_summary: str | None = None


class GenerationMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model: str
    prompt_version: str
    seed: int
    otel_semconv_version: str = "1.25.0"
    schema_version: str = "1.0.0"
    synthetic: bool = True


class InternalTrace(BaseModel):
    model_config = ConfigDict(extra="forbid")

    trace_id: str
    spans: list[InternalSpan]
    logs: list[InternalLog] = Field(default_factory=list)
    label: TraceLabel
    metadata: GenerationMetadata
