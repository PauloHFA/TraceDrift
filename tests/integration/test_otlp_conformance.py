"""Integration test ensuring 100% of exported OTLP files conform to Protobuf specifications."""

import json
from pathlib import Path

from google.protobuf import json_format
from opentelemetry.proto.trace.v1.trace_pb2 import TracesData

from tracedrift.exporter import convert_trace_to_otlp_json
from tracedrift.normalizer import TraceNormalizer
from tracedrift.validator import TraceValidator


def test_batch_otlp_protobuf_parsing() -> None:
    golden_path = Path("tests/golden/golden_blueprints.json")
    with open(golden_path, encoding="utf-8") as f:
        blueprints = json.load(f)

    validator = TraceValidator()
    normalizer = TraceNormalizer(seed=123)

    consolidated_resource_spans = []

    for i, bp in enumerate(blueprints):
        bp_obj, _ = validator.validate_blueprint(bp)
        assert bp_obj is not None
        trace, _ = normalizer.normalize(bp_obj, trace_index=i, base_time_unix_nano=1700000000000000000)
        otlp = convert_trace_to_otlp_json(trace)
        consolidated_resource_spans.extend(otlp.get("resourceSpans", []))

    final_payload = {"resourceSpans": consolidated_resource_spans}
    json_bytes = json.dumps(final_payload).encode("utf-8")

    # Parse through official protobuf
    parsed_msg = TracesData()
    json_format.Parse(json_bytes, parsed_msg)

    assert len(parsed_msg.resource_spans) == len(consolidated_resource_spans)
