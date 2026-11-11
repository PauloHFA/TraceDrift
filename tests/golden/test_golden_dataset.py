"""Regression tests using the 20 canonical golden blueprints (RF02, RNF01, RNF02)."""

import json
from pathlib import Path

from tracedrift.exporter import convert_trace_to_otlp_json, validate_otlp_conformance
from tracedrift.normalizer import TraceNormalizer
from tracedrift.validator import TraceValidator


def test_all_20_golden_blueprints_pass_validation() -> None:
    golden_path = Path("tests/golden/golden_blueprints.json")
    assert golden_path.exists(), "golden_blueprints.json deve existir"

    with open(golden_path, encoding="utf-8") as f:
        golden_list = json.load(f)

    assert len(golden_list) == 20, (
        "O conjunto dourado deve conter exatamente 20 blueprints canônicos"
    )

    validator = TraceValidator()
    normalizer = TraceNormalizer(seed=42, auto_fix=True)

    base_time_nano = 1700000000000000000

    for idx, bp_raw in enumerate(golden_list):
        # 1. Blueprint Validation (Layer 1 & 2)
        blueprint_obj, bp_report = validator.validate_blueprint(bp_raw)
        assert bp_report.is_valid is True, (
            f"Blueprint #{idx} ({bp_raw.get('anomaly_type')}) falhou: {bp_report.errors}"
        )
        assert blueprint_obj is not None

        # 2. Normalization
        internal_trace, adjustments = normalizer.normalize(
            blueprint=blueprint_obj,
            trace_index=idx,
            base_time_unix_nano=base_time_nano + (idx * 1_000_000_000),
            model_name="golden-verified",
        )

        # 3. Materialized Validation (Layer 3 & 4)
        mat_report = validator.validate_materialized_trace(
            internal_trace,
            expected_anomaly_type=bp_raw.get("anomaly_type"),
        )
        assert mat_report.is_valid is True, (
            f"Trace #{idx} ({bp_raw.get('anomaly_type')}) falhou na Camada {mat_report.layer_failed}: {mat_report.errors}"
        )

        # 4. OTLP Protobuf Conformance (RNF02)
        otlp_dict = convert_trace_to_otlp_json(internal_trace)
        assert validate_otlp_conformance(otlp_dict) is True
