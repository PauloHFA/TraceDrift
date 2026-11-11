"""Deterministic trace generation planner."""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from datetime import UTC, datetime

from tracedrift.models import AnomalyCatalog, AnomalyPattern, FlowDefinition


@dataclass
class PlannedTrace:
    index: int
    scheduled_time_iso: str
    scheduled_time_unix_nano: int
    is_anomalous: bool
    anomaly_type: str  # "normal" or pattern.id
    anomaly_pattern: AnomalyPattern | None = None


@dataclass
class GenerationPlan:
    flow_name: str
    total_traces: int
    normal_traces_count: int
    anomalous_traces_count: int
    target_anomaly_ratio: float
    effective_anomaly_ratio: float
    seed: int
    traces: list[PlannedTrace] = field(default_factory=list)
    compatible_anomalies: list[str] = field(default_factory=list)
    discarded_anomalies: list[dict[str, str]] = field(default_factory=list)
    estimated_prompt_tokens: int = 0
    estimated_completion_tokens: int = 0
    estimated_total_tokens: int = 0


def filter_compatible_anomalies(
    flow: FlowDefinition, catalog: AnomalyCatalog
) -> tuple[list[AnomalyPattern], list[dict[str, str]]]:
    """Filters anomalies from catalog that match the technologies present in the flow."""
    flow_technologies = {s.technology.lower() for s in flow.services}
    # General protocols/terms that apply widely
    flow_technologies.update({"http", "grpc", "amqp", "sql", "tcp"})

    compatible: list[AnomalyPattern] = []
    discarded: list[dict[str, str]] = []

    for anomaly in catalog.anomalies:
        applicable = {tech.lower() for tech in anomaly.applicable_technologies}
        overlap = flow_technologies.intersection(applicable)
        if overlap:
            compatible.append(anomaly)
        else:
            discarded.append(
                {
                    "anomaly_id": anomaly.id,
                    "reason": (
                        f"Tecnologias da anomalia ({sorted(applicable)}) não estão presentes no fluxo "
                        f"({sorted(flow_technologies)})."
                    ),
                }
            )

    return compatible, discarded


def create_generation_plan(
    flow: FlowDefinition,
    catalog: AnomalyCatalog,
    total_traces: int = 100,
    anomaly_ratio: float = 0.15,
    seed: int = 42,
    base_time: datetime | None = None,
    time_window_seconds: float = 3600.0,
    anomaly_start_pct: float = 0.2,
) -> GenerationPlan:
    """Creates a deterministic generation plan for synthetic traces."""
    if total_traces <= 0:
        raise ValueError("total_traces deve ser maior que 0.")
    if not (0.0 <= anomaly_ratio <= 1.0):
        raise ValueError("anomaly_ratio deve estar entre 0.0 e 1.0.")

    rng = random.Random(seed)

    compatible_anomalies, discarded_anomalies = filter_compatible_anomalies(flow, catalog)
    if anomaly_ratio > 0 and not compatible_anomalies:
        raise ValueError(
            "Nenhuma anomalia do catálogo é compatível com as tecnologias dos serviços no fluxo."
        )

    if base_time is None:
        base_time = datetime(2026, 11, 10, 12, 0, 0, tzinfo=UTC)
    elif base_time.tzinfo is None:
        base_time = base_time.replace(tzinfo=UTC)

    base_time_nano = int(base_time.timestamp() * 1_000_000_000)

    target_anomalous = int(round(total_traces * anomaly_ratio))
    target_normal = total_traces - target_anomalous

    # Determine which slots are anomalous
    anomaly_start_index = int(total_traces * anomaly_start_pct)
    eligible_anomaly_indices = list(range(anomaly_start_index, total_traces))

    if len(eligible_anomaly_indices) < target_anomalous:
        eligible_anomaly_indices = list(range(total_traces))

    anomalous_indices = set(rng.sample(eligible_anomaly_indices, target_anomalous))

    traces: list[PlannedTrace] = []
    window_nano = int(time_window_seconds * 1_000_000_000)
    step_nano = window_nano // total_traces if total_traces > 1 else 0

    for i in range(total_traces):
        trace_time_nano = base_time_nano + (i * step_nano) + rng.randint(0, max(1, step_nano // 4))
        trace_time_iso = datetime.fromtimestamp(trace_time_nano / 1_000_000_000, tz=UTC).isoformat()

        is_anom = i in anomalous_indices
        if is_anom and compatible_anomalies:
            pattern = rng.choice(compatible_anomalies)
            anomaly_id = pattern.id
        else:
            pattern = None
            anomaly_id = "normal"

        traces.append(
            PlannedTrace(
                index=i,
                scheduled_time_iso=trace_time_iso,
                scheduled_time_unix_nano=trace_time_nano,
                is_anomalous=is_anom,
                anomaly_type=anomaly_id,
                anomaly_pattern=pattern,
            )
        )

    # Token estimation:
    # Prompt tokens per trace ~ base schema/prompt overhead (~750) + flow steps (~40 per step)
    prompt_tokens_per_trace = 750 + (len(flow.steps) * 40)
    # Completion tokens per trace ~ 120 per span (approx 1 span per step + root)
    completion_tokens_per_trace = 150 + ((len(flow.steps) + 1) * 110)

    est_prompt = prompt_tokens_per_trace * total_traces
    est_completion = completion_tokens_per_trace * total_traces

    return GenerationPlan(
        flow_name=flow.name,
        total_traces=total_traces,
        normal_traces_count=target_normal,
        anomalous_traces_count=target_anomalous,
        target_anomaly_ratio=anomaly_ratio,
        effective_anomaly_ratio=target_anomalous / total_traces if total_traces > 0 else 0.0,
        seed=seed,
        traces=traces,
        compatible_anomalies=[a.id for a in compatible_anomalies],
        discarded_anomalies=discarded_anomalies,
        estimated_prompt_tokens=est_prompt,
        estimated_completion_tokens=est_completion,
        estimated_total_tokens=est_prompt + est_completion,
    )
