"""Unit tests for LLM-as-judge evaluation in tracedrift.judge."""

import json
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from tracedrift.client import LLMClient
from tracedrift.flow import load_flow_from_file
from tracedrift.judge import TraceJudge


@pytest.mark.asyncio
async def test_trace_judge_evaluation(tmp_path: Path) -> None:
    flow = load_flow_from_file("configs/e_commerce_flow.yaml")

    mock_judge_response = {
        "score": 4.5,
        "verdict": "APROVADO",
        "realism_score": 5.0,
        "coherence_score": 4.0,
        "observability_score": 4.5,
        "reasoning": "Estrutura realista e consistente.",
    }

    mock_client = LLMClient(api_key="mock")
    mock_client.generate_json = AsyncMock(return_value=mock_judge_response)  # type: ignore[method-assign]

    judge = TraceJudge(client=mock_client)

    sample_trace = {
        "trace_id": "4bf92f3577b34da6a3ce929d0e0e4736",
        "scenario": "E-Commerce Checkout",
        "label": {"anomaly_type": "retry_storm"},
        "spans": [],
    }

    traces_file = tmp_path / "traces.jsonl"
    with open(traces_file, "w", encoding="utf-8") as f:
        f.write(json.dumps(sample_trace) + "\n")

    report = await judge.evaluate_traces_file(traces_file, flow=flow, max_traces=1)

    assert report.total_evaluated == 1
    assert report.average_score == 4.5
    assert report.average_realism == 5.0
    assert report.scores[0].verdict == "APROVADO"
