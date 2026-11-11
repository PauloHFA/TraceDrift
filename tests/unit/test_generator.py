"""Unit and orchestration tests for TraceGenerator in tracedrift.generator."""

import json
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
import yaml

from tracedrift.client import LLMClient
from tracedrift.flow import load_flow_from_file
from tracedrift.generator import TraceGenerator
from tracedrift.models import AnomalyCatalog
from tracedrift.planner import create_generation_plan


@pytest.mark.asyncio
async def test_trace_generator_runs_successfully(tmp_path: Path) -> None:
    flow = load_flow_from_file("configs/e_commerce_flow.yaml")
    with open("configs/anomalies_default.yaml", encoding="utf-8") as f:
        catalog = AnomalyCatalog.model_validate(yaml.safe_load(f))

    plan = create_generation_plan(flow, catalog, total_traces=3, anomaly_ratio=0.33, seed=42)

    with open("tests/golden/golden_blueprints.json", encoding="utf-8") as f:
        sample_blueprint = json.load(f)[0]

    # Mock LLMClient
    mock_client = LLMClient(api_key="mock")
    mock_client.generate_json = AsyncMock(return_value=sample_blueprint)  # type: ignore[method-assign]

    progress_events = []

    def on_progress(done: int, total: int) -> None:
        progress_events.append((done, total))

    generator = TraceGenerator(
        flow=flow,
        plan=plan,
        client=mock_client,
        output_dir=tmp_path,
        concurrency=2,
        auto_fix=True,
        resume=True,
        progress_callback=on_progress,
    )

    stats = await generator.run()

    assert stats.generated_success == 3
    assert stats.rejected_count == 0
    assert len(progress_events) == 3
    assert (tmp_path / "traces.jsonl").exists()
    assert (tmp_path / "labels.jsonl").exists()
    assert (tmp_path / "otlp_traces.json").exists()
    assert (tmp_path / ".tracedrift_state.json").exists()

    # Second run with resume should skip already completed
    generator_resume = TraceGenerator(
        flow=flow,
        plan=plan,
        client=mock_client,
        output_dir=tmp_path,
        resume=True,
    )
    mock_client.generate_json.reset_mock()
    stats_resume = await generator_resume.run()
    assert stats_resume.generated_success == 3
    mock_client.generate_json.assert_not_called()


@pytest.mark.asyncio
async def test_trace_generator_retry_and_rejection(tmp_path: Path) -> None:
    flow = load_flow_from_file("configs/e_commerce_flow.yaml")
    with open("configs/anomalies_default.yaml", encoding="utf-8") as f:
        catalog = AnomalyCatalog.model_validate(yaml.safe_load(f))

    plan = create_generation_plan(flow, catalog, total_traces=1, anomaly_ratio=0.0, seed=42)

    # Mock client returns invalid blueprint missing root span
    invalid_blueprint = {
        "scenario": "Invalid Root",
        "anomaly_type": "normal",
        "spans": [
            {
                "ref": "s1",
                "parent_ref": "nonexistent_parent",
                "service_name": "api-gateway",
                "name": "op",
                "kind": "SERVER",
                "offset_ms": 0,
                "duration_ms": 100,
            }
        ],
    }

    mock_client = LLMClient(api_key="mock")
    mock_client.generate_json = AsyncMock(return_value=invalid_blueprint)  # type: ignore[method-assign]

    generator = TraceGenerator(
        flow=flow,
        plan=plan,
        client=mock_client,
        output_dir=tmp_path,
        max_validation_retries=1,
    )

    stats = await generator.run()

    assert stats.rejected_count == 1
    assert stats.generated_success == 0
    assert stats.retries_used == 1
    assert (tmp_path / "rejected.jsonl").exists()
