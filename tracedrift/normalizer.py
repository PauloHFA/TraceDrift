"""Deterministic normalizer converting symbolic blueprints into concrete OpenTelemetry spans and logs."""

from __future__ import annotations

import hashlib
from typing import Any

from tracedrift.models import (
    BlueprintSpan,
    BlueprintTrace,
    GenerationMetadata,
    InternalLog,
    InternalSpan,
    InternalTrace,
    SpanKindEnum,
    StatusCodeEnum,
    TraceLabel,
)

SEVERITY_TEXT_TO_NUMBER: dict[str, int] = {
    "TRACE": 1,
    "DEBUG": 5,
    "INFO": 9,
    "WARN": 13,
    "WARNING": 13,
    "ERROR": 17,
    "FATAL": 21,
    "CRITICAL": 21,
}


def generate_trace_id(seed: int, trace_index: int) -> str:
    """Generates a deterministic 32-character lowercase hex trace_id."""
    raw = f"tracedrift:trace:{seed}:{trace_index}".encode()
    return hashlib.sha256(raw).hexdigest()[:32]


def generate_span_id(seed: int, trace_index: int, span_index: int) -> str:
    """Generates a deterministic 16-character lowercase hex span_id."""
    raw = f"tracedrift:span:{seed}:{trace_index}:{span_index}".encode()
    return hashlib.sha256(raw).hexdigest()[:16]


class NormalizationError(Exception):
    """Raised when blueprint normalization fails unrecoverably."""


class TraceNormalizer:
    def __init__(self, seed: int = 42, auto_fix: bool = True) -> None:
        self.seed = seed
        self.auto_fix = auto_fix
        self.adjustments: list[str] = []

    def _fix_semantic_attributes(
        self, span: BlueprintSpan, attributes: dict[str, Any]
    ) -> dict[str, Any]:
        """Ensures updated OpenTelemetry semantic conventions are strictly used."""
        attrs = dict(attributes)

        # HTTP Modern conventions
        if "http.method" in attrs and "http.request.method" not in attrs:
            attrs["http.request.method"] = attrs.pop("http.method")
        if "http.status_code" in attrs and "http.response.status_code" not in attrs:
            attrs["http.response.status_code"] = int(attrs.pop("http.status_code"))
        if "user_agent" in attrs and "user_agent.original" not in attrs:
            attrs["user_agent.original"] = attrs.pop("user_agent")

        # Database conventions
        if span.kind == SpanKindEnum.CLIENT and "db" in span.name.lower():
            if "db.system" not in attrs:
                attrs["db.system"] = "postgresql"
            if "db.operation" not in attrs:
                attrs["db.operation"] = span.name.split()[0] if " " in span.name else "QUERY"

        # Standard synthetic resource marker
        attrs["tracedrift.generated"] = True
        return attrs

    def normalize(
        self,
        blueprint: BlueprintTrace,
        trace_index: int,
        base_time_unix_nano: int,
        model_name: str = "synthetic-model",
        prompt_version: str = "v1",
    ) -> tuple[InternalTrace, list[str]]:
        """Materializes a BlueprintTrace into an InternalTrace."""
        self.adjustments.clear()

        trace_id = generate_trace_id(self.seed, trace_index)

        # Map symbolic refs to index and IDs
        ref_to_span_id: dict[str, str] = {}
        for idx, span in enumerate(blueprint.spans):
            if span.ref in ref_to_span_id:
                raise NormalizationError(f"Rótulo de span duplicado no blueprint: '{span.ref}'")
            ref_to_span_id[span.ref] = generate_span_id(self.seed, trace_index, idx)

        # Identify root span
        root_spans = [s for s in blueprint.spans if s.parent_ref is None]
        if len(root_spans) != 1:
            raise NormalizationError(
                f"O blueprint deve ter exatamente um span-raiz com parent_ref=None (encontrados: {len(root_spans)})."
            )
        root_span = root_spans[0]

        # First pass: map start and end times in nanoseconds
        # For tree calculations, build a parent-child hierarchy
        span_by_ref = {s.ref: s for s in blueprint.spans}
        start_nano_by_ref: dict[str, int] = {}
        end_nano_by_ref: dict[str, int] = {}

        # Set root start time
        start_nano_by_ref[root_span.ref] = base_time_unix_nano
        end_nano_by_ref[root_span.ref] = base_time_unix_nano + int(
            root_span.duration_ms * 1_000_000
        )

        # BFS / topological traversal to calculate start/end times
        # Spans can be processed iteratively
        processed = {root_span.ref}
        remaining = [s for s in blueprint.spans if s.ref != root_span.ref]

        max_iterations = len(blueprint.spans) * 2
        iteration = 0
        while remaining and iteration < max_iterations:
            iteration += 1
            deferred: list[BlueprintSpan] = []
            for span in remaining:
                parent_ref = span.parent_ref
                if parent_ref in processed:
                    parent_start_nano = start_nano_by_ref[parent_ref]
                    parent_end_nano = end_nano_by_ref[parent_ref]

                    span_start_nano = parent_start_nano + int(span.offset_ms * 1_000_000)
                    span_end_nano = span_start_nano + int(span.duration_ms * 1_000_000)

                    # Check for sync child bounds violations
                    is_async = span.kind in (SpanKindEnum.CONSUMER, SpanKindEnum.PRODUCER)
                    if not is_async and span_end_nano > parent_end_nano:
                        overflow_ns = span_end_nano - parent_end_nano
                        parent_duration_ns = parent_end_nano - parent_start_nano
                        ratio = overflow_ns / parent_duration_ns if parent_duration_ns > 0 else 1.0

                        if self.auto_fix and ratio <= 0.05:
                            # Adjust child duration to fit parent
                            adjusted_duration_ns = parent_end_nano - span_start_nano
                            if adjusted_duration_ns > 0:
                                span_end_nano = parent_end_nano
                                adj_msg = (
                                    f"Auto-fix: span '{span.ref}' ajustado em {overflow_ns / 1_000_000:.2f}ms "
                                    f"para caber no pai '{parent_ref}'."
                                )
                                self.adjustments.append(adj_msg)
                        elif self.auto_fix and ratio <= 0.05:
                            # Expand parent end time up to 5% if possible
                            parent_end_nano = span_end_nano
                            end_nano_by_ref[parent_ref] = parent_end_nano
                            self.adjustments.append(
                                f"Auto-fix: pai '{parent_ref}' estendido em {overflow_ns / 1_000_000:.2f}ms."
                            )

                    start_nano_by_ref[span.ref] = span_start_nano
                    end_nano_by_ref[span.ref] = span_end_nano
                    processed.add(span.ref)
                else:
                    deferred.append(span)
            remaining = deferred

        if remaining:
            unresolved = [s.ref for s in remaining]
            raise NormalizationError(
                f"Spans órfãos ou com ciclos detectados durante resolução temporal: {unresolved}"
            )

        # Build InternalSpans
        materialized_spans: list[InternalSpan] = []
        for span in blueprint.spans:
            s_id = ref_to_span_id[span.ref]
            p_id = ref_to_span_id[span.parent_ref] if span.parent_ref else None

            s_start = start_nano_by_ref[span.ref]
            s_end = end_nano_by_ref[span.ref]

            # Prepare status
            status_code = span.status.code.value
            status_dict: dict[str, Any] = {"code": status_code}
            if span.status.message:
                status_dict["message"] = span.status.message

            # Prepare attributes
            attrs = self._fix_semantic_attributes(span, span.attributes)

            # Materialize events
            events = []
            for ev in span.events:
                ev_time_nano = s_start + int(ev.offset_ms * 1_000_000)
                events.append(
                    {
                        "name": ev.name,
                        "time_unix_nano": ev_time_nano,
                        "attributes": ev.attributes,
                    }
                )

            # If span is ERROR and has no exception event, ensure one is synthesized
            if span.status.code == StatusCodeEnum.ERROR:
                has_exception = any(e.get("name") == "exception" for e in events)
                if not has_exception:
                    err_msg = span.status.message or "Unknown internal error"
                    events.append(
                        {
                            "name": "exception",
                            "time_unix_nano": s_start + int((s_end - s_start) * 0.8),
                            "attributes": {
                                "exception.type": "RuntimeError",
                                "exception.message": err_msg,
                            },
                        }
                    )

            # Materialize links
            links = []
            for link in span.links:
                target_span_id = ref_to_span_id.get(
                    link.span_ref, generate_span_id(self.seed, trace_index, 99)
                )
                links.append(
                    {
                        "trace_id": trace_id,
                        "span_id": target_span_id,
                        "attributes": link.attributes,
                    }
                )

            materialized_spans.append(
                InternalSpan(
                    trace_id=trace_id,
                    span_id=s_id,
                    parent_span_id=p_id,
                    name=span.name,
                    service_name=span.service_name,
                    kind=span.kind.to_otlp_name(),
                    start_time_unix_nano=s_start,
                    end_time_unix_nano=s_end,
                    status=status_dict,
                    attributes=attrs,
                    events=events,
                    links=links,
                )
            )

        # Build InternalLogs
        materialized_logs: list[InternalLog] = []
        for log in blueprint.logs:
            if log.span_ref not in ref_to_span_id:
                continue
            corr_span_id = ref_to_span_id[log.span_ref]
            corr_span = span_by_ref[log.span_ref]
            s_start = start_nano_by_ref[log.span_ref]
            log_time = s_start + int(log.offset_ms * 1_000_000)

            sev_upper = log.severity.upper()
            sev_num = SEVERITY_TEXT_TO_NUMBER.get(sev_upper, 9)

            materialized_logs.append(
                InternalLog(
                    trace_id=trace_id,
                    span_id=corr_span_id,
                    timestamp_unix_nano=log_time,
                    severity_text=sev_upper,
                    severity_number=sev_num,
                    body=log.body,
                    service_name=corr_span.service_name,
                    attributes=log.attributes,
                )
            )

        # Calculate affected services
        if blueprint.anomaly_type == "normal":
            affected_services: list[str] = []
            is_anomalous = False
            root_cause_span_id = None
        else:
            is_anomalous = True
            affected_services = sorted(
                {s.service_name for s in blueprint.spans if s.status.code == StatusCodeEnum.ERROR}
            )
            if not affected_services and blueprint.root_cause_ref:
                rc_span = span_by_ref.get(blueprint.root_cause_ref)
                if rc_span:
                    affected_services = [rc_span.service_name]

            root_cause_span_id = (
                ref_to_span_id.get(blueprint.root_cause_ref) if blueprint.root_cause_ref else None
            )

        label = TraceLabel(
            trace_id=trace_id,
            anomaly_type=blueprint.anomaly_type,
            root_cause_span_id=root_cause_span_id,
            affected_services=affected_services,
            is_anomalous=is_anomalous,
            severity="HIGH" if is_anomalous else None,
            root_cause_summary=blueprint.root_cause_summary,
        )

        metadata = GenerationMetadata(
            model=model_name,
            prompt_version=prompt_version,
            seed=self.seed,
            otel_semconv_version="1.25.0",
            schema_version="1.0.0",
            synthetic=True,
        )

        internal_trace = InternalTrace(
            trace_id=trace_id,
            spans=materialized_spans,
            logs=materialized_logs,
            label=label,
            metadata=metadata,
        )

        return internal_trace, list(self.adjustments)
