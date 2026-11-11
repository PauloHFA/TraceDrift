"""Layered validation engine for blueprints and materialized traces."""

from __future__ import annotations

import ipaddress
import re
from dataclasses import dataclass, field
from typing import Any

import networkx as nx
from pydantic import ValidationError

from tracedrift.models import (
    BlueprintTrace,
    InternalSpan,
    InternalTrace,
    StatusCodeEnum,
)


@dataclass
class ValidationReport:
    is_valid: bool
    layer_failed: int | None = None  # 1, 2, 3, or 4
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


# RFC 5737 (Documentation IPv4) and RFC 1918 (Private IPv4) + loopback
ALLOWED_IPV4_NETWORKS = [
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("192.0.2.0/24"),  # TEST-NET-1 (RFC 5737)
    ipaddress.ip_network("198.51.100.0/24"),  # TEST-NET-2 (RFC 5737)
    ipaddress.ip_network("203.0.113.0/24"),  # TEST-NET-3 (RFC 5737)
]

IPV4_PATTERN = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
EMAIL_PATTERN = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b")
ALLOWED_EMAIL_DOMAINS = {
    "example.com",
    "example.org",
    "example.net",
    "test.local",
    "tracedrift.internal",
}
SECRET_PATTERNS = [
    re.compile(r"AKIA[0-9A-Z]{16}"),  # AWS Access Key
    re.compile(r"(?:Bearer\s+)[A-Za-z0-9\-_]{20,}"),  # Bearer token
    re.compile(r"(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9_]{36}"),  # GitHub token
]


class TraceValidator:
    def validate_blueprint(
        self, raw_blueprint: dict[str, Any]
    ) -> tuple[BlueprintTrace | None, ValidationReport]:
        """Layer 1 & Layer 2: Validates schema and graph hierarchy of blueprint."""
        # Layer 1: Schema Validation
        try:
            blueprint = BlueprintTrace.model_validate(raw_blueprint)
        except ValidationError as err:
            err_msgs = [f"{e.get('loc')}: {e.get('msg')}" for e in err.errors()]
            return None, ValidationReport(
                is_valid=False,
                layer_failed=1,
                errors=[f"Falha na Camada 1 (Schema Blueprint): {', '.join(err_msgs)}"],
            )

        # Check unique refs
        refs = [s.ref for s in blueprint.spans]
        if len(refs) != len(set(refs)):
            return blueprint, ValidationReport(
                is_valid=False,
                layer_failed=1,
                errors=["Falha na Camada 1: Rótulos simbólicos duplicados encontrados nos spans."],
            )

        # Check single root span
        roots = [s for s in blueprint.spans if s.parent_ref is None]
        if len(roots) != 1:
            return blueprint, ValidationReport(
                is_valid=False,
                layer_failed=1,
                errors=[
                    f"Falha na Camada 1: Esperado exatamente 1 span raiz, encontrados {len(roots)}."
                ],
            )

        # Layer 2: Graph Structure Validation
        graph = nx.DiGraph()
        ref_set = set(refs)

        for span in blueprint.spans:
            graph.add_node(span.ref)

        for span in blueprint.spans:
            if span.parent_ref:
                if span.parent_ref not in ref_set:
                    return blueprint, ValidationReport(
                        is_valid=False,
                        layer_failed=2,
                        errors=[
                            f"Falha na Camada 2 (Grafo): Span '{span.ref}' referencia pai inexistente '{span.parent_ref}'."
                        ],
                    )
                graph.add_edge(span.parent_ref, span.ref)

        # Check DAG acyclicity
        if not nx.is_directed_acyclic_graph(graph):
            return blueprint, ValidationReport(
                is_valid=False,
                layer_failed=2,
                errors=["Falha na Camada 2 (Grafo): Ciclo detectado na hierarquia de spans."],
            )

        # Check all nodes reachable from root
        root_ref = roots[0].ref
        reachable = nx.descendants(graph, root_ref) | {root_ref}
        if len(reachable) != len(blueprint.spans):
            unreachable = ref_set - reachable
            return blueprint, ValidationReport(
                is_valid=False,
                layer_failed=2,
                errors=[
                    f"Falha na Camada 2 (Grafo): Spans isolados/órfãos detectados: {sorted(unreachable)}."
                ],
            )

        return blueprint, ValidationReport(is_valid=True)

    def validate_materialized_trace(
        self,
        trace: InternalTrace,
        expected_anomaly_type: str | None = None,
        slo_timeout_ms: float | None = None,
    ) -> ValidationReport:
        """Layer 3 & Layer 4: Validates temporal consistency, OTel conventions, and security."""
        errors: list[str] = []
        warnings: list[str] = []

        # Layer 3: Temporal & OTel Consistency
        span_map: dict[str, InternalSpan] = {s.span_id: s for s in trace.spans}
        root_spans = [s for s in trace.spans if s.parent_span_id is None]

        if len(root_spans) != 1:
            errors.append(f"Esperado exatamente 1 span raiz, encontrados {len(root_spans)}.")
            return ValidationReport(is_valid=False, layer_failed=3, errors=errors)

        root = root_spans[0]

        # Invariant: end_time > start_time
        for s in trace.spans:
            if s.end_time_unix_nano <= s.start_time_unix_nano:
                errors.append(
                    f"Span '{s.name}' ({s.span_id}): end_time ({s.end_time_unix_nano}) deve ser maior que start_time ({s.start_time_unix_nano})."
                )

        # Invariant: synchronous child must be contained within parent
        for s in trace.spans:
            if s.parent_span_id:
                parent = span_map.get(s.parent_span_id)
                if not parent:
                    errors.append(
                        f"Span '{s.span_id}' referencia pai desconhecido '{s.parent_span_id}'."
                    )
                    continue

                is_async = s.kind in ("SPAN_KIND_CONSUMER", "SPAN_KIND_PRODUCER") or bool(s.links)
                if not is_async:
                    if s.start_time_unix_nano < parent.start_time_unix_nano:
                        errors.append(
                            f"Violação temporal: Span filho síncrono '{s.name}' inicia antes do pai '{parent.name}'."
                        )
                    if s.end_time_unix_nano > parent.end_time_unix_nano:
                        diff_ms = (s.end_time_unix_nano - parent.end_time_unix_nano) / 1_000_000
                        errors.append(
                            f"Violação temporal: Span filho síncrono '{s.name}' termina {diff_ms:.2f}ms após o término do pai '{parent.name}'."
                        )
                else:
                    # Async consumer exception (RNF01)
                    if s.start_time_unix_nano < parent.start_time_unix_nano:
                        errors.append(
                            f"Violação temporal assíncrona: Span '{s.name}' inicia antes do início do produtor '{parent.name}'."
                        )

        # OTel Semantics: status and exception events
        for s in trace.spans:
            status_code = s.status.get("code")
            if status_code == StatusCodeEnum.ERROR.value:
                has_exception = any(e.get("name") == "exception" for e in s.events)
                has_msg = bool(s.status.get("message"))
                if not has_exception and not has_msg:
                    errors.append(
                        f"Span com status ERROR '{s.name}' deve possuir mensagem de erro ou evento 'exception'."
                    )

            # Modern HTTP conventions check
            attrs = s.attributes
            if "http.method" in attrs:
                errors.append(
                    f"Atributo obsoleto 'http.method' no span '{s.name}'; use 'http.request.method'."
                )
            if "http.status_code" in attrs:
                errors.append(
                    f"Atributo obsoleto 'http.status_code' no span '{s.name}'; use 'http.response.status_code'."
                )

        # Correlated Logs Check (RF07)
        for s in trace.spans:
            if s.status.get("code") == StatusCodeEnum.ERROR.value:
                matching_logs = [
                    log_item
                    for log_item in trace.logs
                    if log_item.span_id == s.span_id
                    and log_item.severity_text in ("ERROR", "WARN", "WARNING", "FATAL")
                ]
                if not matching_logs:
                    warnings.append(
                        f"Span com erro '{s.name}' não possui logs correlacionados com severidade ERROR/WARN."
                    )

        # Anomaly Signature Check (RF12)
        anomaly_type = expected_anomaly_type or trace.label.anomaly_type
        if anomaly_type == "retry_storm":
            # Check 3 or more retry spans
            retry_spans = [
                s
                for s in trace.spans
                if "retry" in s.name.lower()
                or "retry.count" in s.attributes
                or "retry" in str(s.attributes)
            ]
            if len(retry_spans) < 3:
                warnings.append(
                    f"Assinatura de Retry Storm fraca: esperados >= 3 spans de tentativa, encontrados {len(retry_spans)}."
                )
        elif anomaly_type == "cascading_timeout":
            root_duration_ms = (root.end_time_unix_nano - root.start_time_unix_nano) / 1_000_000
            if slo_timeout_ms and root_duration_ms < slo_timeout_ms:
                warnings.append(
                    f"Cascading Timeout: duração do span raiz ({root_duration_ms:.1f}ms) é menor que timeout ({slo_timeout_ms:.1f}ms)."
                )

        if errors:
            return ValidationReport(
                is_valid=False, layer_failed=3, errors=errors, warnings=warnings
            )

        # Layer 4: Security and PII Validation
        text_corpus = []
        for s in trace.spans:
            text_corpus.append(s.name)
            for k, v in s.attributes.items():
                text_corpus.append(f"{k}={v}")
        for log_entry in trace.logs:
            text_corpus.append(log_entry.body)
            for k, v in log_entry.attributes.items():
                text_corpus.append(f"{k}={v}")

        full_text = " ".join(text_corpus)

        # Scan IPv4
        found_ips = IPV4_PATTERN.findall(full_text)
        for ip_str in found_ips:
            try:
                ip_obj = ipaddress.ip_address(ip_str)
                is_allowed = any(ip_obj in net for net in ALLOWED_IPV4_NETWORKS)
                if not is_allowed:
                    errors.append(
                        f"Falha na Camada 4 (Segurança): IP público real detectado: '{ip_str}'. Permitidos apenas RFC 5737 e RFC 1918."
                    )
            except ValueError:
                pass

        # Scan Emails
        found_emails = EMAIL_PATTERN.findall(full_text)
        for email in found_emails:
            domain = email.split("@")[-1].lower()
            if domain not in ALLOWED_EMAIL_DOMAINS:
                errors.append(
                    f"Falha na Camada 4 (Privacidade): E-mail com domínio real detectado: '{email}'. Permitidos apenas domínios de documentação (ex: example.com)."
                )

        # Scan Secrets
        for sec_pattern in SECRET_PATTERNS:
            if sec_pattern.search(full_text):
                errors.append(
                    "Falha na Camada 4 (Segurança): Padrão de credencial/token sensível detectado no dataset."
                )

        if errors:
            return ValidationReport(
                is_valid=False, layer_failed=4, errors=errors, warnings=warnings
            )

        return ValidationReport(is_valid=True, warnings=warnings)
