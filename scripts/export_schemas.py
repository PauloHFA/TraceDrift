"""Utility to export JSON Schemas for Blueprint and Internal Trace models."""

import json
from pathlib import Path

from tracedrift.models import BlueprintTrace, FlowDefinition, InternalTrace


def export_schemas() -> None:
    schema_dir = Path("schema")
    schema_dir.mkdir(parents=True, exist_ok=True)

    blueprint_schema = BlueprintTrace.model_json_schema()
    with open(schema_dir / "blueprint.schema.json", "w", encoding="utf-8") as f:
        json.dump(blueprint_schema, f, indent=2, ensure_ascii=False)

    trace_schema = InternalTrace.model_json_schema()
    with open(schema_dir / "trace.schema.json", "w", encoding="utf-8") as f:
        json.dump(trace_schema, f, indent=2, ensure_ascii=False)

    flow_schema = FlowDefinition.model_json_schema()
    with open(schema_dir / "flow.schema.json", "w", encoding="utf-8") as f:
        json.dump(flow_schema, f, indent=2, ensure_ascii=False)

    print("Schemas exported successfully into schema/")


if __name__ == "__main__":
    export_schemas()
