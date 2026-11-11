"""Unit tests for planner in tracedrift.planner."""

import pytest
import yaml

from tracedrift.flow import load_flow_from_file
from tracedrift.models import AnomalyCatalog
from tracedrift.planner import create_generation_plan


@pytest.fixture
def ecommerce_flow():
    return load_flow_from_file("configs/e_commerce_flow.yaml")


@pytest.fixture
def default_catalog():
    with open("configs/anomalies_default.yaml", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return AnomalyCatalog.model_validate(data)


def test_planner_deterministic_with_same_seed(ecommerce_flow, default_catalog) -> None:
    plan1 = create_generation_plan(ecommerce_flow, default_catalog, total_traces=20, anomaly_ratio=0.2, seed=42)
    plan2 = create_generation_plan(ecommerce_flow, default_catalog, total_traces=20, anomaly_ratio=0.2, seed=42)

    assert plan1.total_traces == plan2.total_traces
    assert plan1.anomalous_traces_count == plan2.anomalous_traces_count
    for t1, t2 in zip(plan1.traces, plan2.traces, strict=True):
        assert t1.index == t2.index
        assert t1.is_anomalous == t2.is_anomalous
        assert t1.anomaly_type == t2.anomaly_type
        assert t1.scheduled_time_unix_nano == t2.scheduled_time_unix_nano


def test_planner_different_seed_produces_different_distribution(ecommerce_flow, default_catalog) -> None:
    plan1 = create_generation_plan(ecommerce_flow, default_catalog, total_traces=50, anomaly_ratio=0.3, seed=42)
    plan2 = create_generation_plan(ecommerce_flow, default_catalog, total_traces=50, anomaly_ratio=0.3, seed=999)

    anom_indices_1 = [t.index for t in plan1.traces if t.is_anomalous]
    anom_indices_2 = [t.index for t in plan2.traces if t.is_anomalous]

    assert anom_indices_1 != anom_indices_2


def test_planner_anomaly_ratio_boundary(ecommerce_flow, default_catalog) -> None:
    plan_zero = create_generation_plan(ecommerce_flow, default_catalog, total_traces=10, anomaly_ratio=0.0)
    assert plan_zero.anomalous_traces_count == 0
    assert all(not t.is_anomalous for t in plan_zero.traces)

    plan_full = create_generation_plan(ecommerce_flow, default_catalog, total_traces=10, anomaly_ratio=1.0)
    assert plan_full.anomalous_traces_count == 10
    assert all(t.is_anomalous for t in plan_full.traces)


def test_planner_token_estimation(ecommerce_flow, default_catalog) -> None:
    plan = create_generation_plan(ecommerce_flow, default_catalog, total_traces=10)
    assert plan.estimated_prompt_tokens > 0
    assert plan.estimated_completion_tokens > 0
    assert plan.estimated_total_tokens == plan.estimated_prompt_tokens + plan.estimated_completion_tokens
