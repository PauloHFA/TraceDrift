"""Generates realistic sample datasets for offline inspection and testing."""

import asyncio
import json
from pathlib import Path

from tracedrift.exporter import StreamingTraceExporter
from tracedrift.normalizer import TraceNormalizer
from tracedrift.validator import TraceValidator


async def main() -> None:
    golden_file = Path("tests/golden/golden_blueprints.json")
    with open(golden_file, encoding="utf-8") as f:
        golden_bps = json.load(f)

    target_dir = Path("datasets")
    target_dir.mkdir(parents=True, exist_ok=True)

    exporter = StreamingTraceExporter(output_dir=target_dir)
    # Rename targets to match spec naming
    exporter.traces_path = target_dir / "sample_traces_100.jsonl"
    exporter.labels_path = target_dir / "sample_labels.jsonl"
    exporter.otlp_traces_path = target_dir / "sample_otlp.json"

    # Reset files if existing
    for p in (exporter.traces_path, exporter.labels_path, exporter.otlp_traces_path):
        if p.exists():
            p.unlink()

    validator = TraceValidator()
    normalizer = TraceNormalizer(seed=42, auto_fix=True)

    base_time_nano = 1700000000000000000
    step_nano = 36_000_000_000  # 36s apart

    for i in range(100):
        # Pick from golden blueprints cyclically
        bp_raw = golden_bps[i % len(golden_bps)]
        bp_obj, _ = validator.validate_blueprint(bp_raw)
        assert bp_obj is not None

        trace, _ = normalizer.normalize(
            blueprint=bp_obj,
            trace_index=i,
            base_time_unix_nano=base_time_nano + (i * step_nano),
            model_name="sample-generator",
        )
        await exporter.write_trace(trace)

    await exporter.finalize()
    print("Successfully generated datasets/sample_traces_100.jsonl, sample_otlp.json, sample_labels.jsonl")


if __name__ == "__main__":
    asyncio.run(main())
