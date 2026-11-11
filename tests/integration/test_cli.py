"""Integration tests for the Typer CLI in tracedrift.cli."""

from pathlib import Path

import pytest
from typer.testing import CliRunner

from tracedrift.cli import app
from tracedrift.models import (
    GenerationMetadata,
    InternalSpan,
    InternalTrace,
    TraceLabel,
)

runner = CliRunner()


def test_cli_init_command(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["init"])
    assert result.exit_code == 0
    assert (tmp_path / "flow.yaml").exists()
    assert (tmp_path / ".env.example").exists()


def test_cli_send_safety_check(tmp_path: Path) -> None:
    dummy_otlp = tmp_path / "otlp.json"
    dummy_otlp.write_text('{"resourceSpans": []}', encoding="utf-8")

    # Trying to send to external endpoint without --yes fails safety check
    result = runner.invoke(
        app, ["send", str(dummy_otlp), "--endpoint", "http://external-prod:4318"]
    )
    assert result.exit_code != 0
    assert "AVISO DE SEGURANÇA" in result.stdout


def test_cli_plan_dry_run() -> None:
    result = runner.invoke(
        app,
        [
            "plan",
            "--flow",
            "configs/e_commerce_flow.yaml",
            "--count",
            "20",
            "--anomaly-ratio",
            "0.2",
            "--dry-run",
        ],
    )
    assert result.exit_code == 0
    assert "Plano de Geração: E-Commerce Checkout Flow" in result.stdout
    assert "Estimativa Tokens Total" in result.stdout
    assert "--dry-run concluído" in result.stdout


def test_cli_validate_flow_yaml() -> None:
    result = runner.invoke(app, ["validate", "configs/e_commerce_flow.yaml"])
    assert result.exit_code == 0
    assert "OK:" in result.stdout


def test_cli_validate_flow_yaml_invalid(tmp_path: Path) -> None:
    bad_yaml = tmp_path / "bad_flow.yaml"
    bad_yaml.write_text("services: []\nsteps: []\n", encoding="utf-8")
    result = runner.invoke(app, ["validate", str(bad_yaml)])
    assert result.exit_code != 0


def test_cli_report_and_visualize(tmp_path: Path) -> None:
    # Create sample trace dataset
    sample_trace = InternalTrace(
        trace_id="4bf92f3577b34da6a3ce929d0e0e4736",
        spans=[
            InternalSpan(
                trace_id="4bf92f3577b34da6a3ce929d0e0e4736",
                span_id="0000000000000001",
                parent_span_id=None,
                name="POST /checkout",
                service_name="api-gateway",
                kind="SPAN_KIND_SERVER",
                start_time_unix_nano=1700000000000000000,
                end_time_unix_nano=1700000000100000000,
                status={"code": "OK"},
            )
        ],
        label=TraceLabel(
            trace_id="4bf92f3577b34da6a3ce929d0e0e4736",
            anomaly_type="normal",
            is_anomalous=False,
        ),
        metadata=GenerationMetadata(model="test", prompt_version="v1", seed=42),
    )

    traces_file = tmp_path / "traces.jsonl"
    with open(traces_file, "w", encoding="utf-8") as f:
        f.write(sample_trace.model_dump_json() + "\n")

    # Test report command
    rep_result = runner.invoke(app, ["report", str(tmp_path)])
    assert rep_result.exit_code == 0
    assert "Relatório Estatístico do Dataset" in rep_result.stdout
    assert (tmp_path / "DATASET_CARD.md").exists()

    # Test visualize command
    viz_result = runner.invoke(
        app, ["visualize", str(traces_file), "--count", "1"], env={"COLUMNS": "120"}
    )
    assert viz_result.exit_code == 0
    assert "Waterfall" in viz_result.stdout
    assert "POST /checkout" in viz_result.stdout
