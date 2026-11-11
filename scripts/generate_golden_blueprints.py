"""Generates 20 canonical, manually-reviewable golden blueprints for regression testing."""

import json
from pathlib import Path

import yaml

from tracedrift.models import AnomalyCatalog


def generate_golden_dataset() -> None:
    with open("configs/anomalies_default.yaml", encoding="utf-8") as f:
        catalog = AnomalyCatalog.model_validate(yaml.safe_load(f))

    golden_blueprints = []

    for anomaly in catalog.anomalies:
        anom_id = anomaly.id
        root_op = "POST /api/v1/resource"
        root_service = "api-gateway"
        db_service = "postgres-db"
        backend_service = "order-service"

        spans = [
            {
                "ref": "s1",
                "parent_ref": None,
                "service_name": root_service,
                "name": root_op,
                "kind": "SERVER",
                "offset_ms": 0.0,
                "duration_ms": 350.0,
                "status": {"code": "ERROR" if anom_id in ("circuit_breaker_tripping", "cascading_timeout", "retry_storm") else "OK"},
                "attributes": {
                    "http.request.method": "POST",
                    "http.response.status_code": 500 if anom_id in ("circuit_breaker_tripping", "cascading_timeout") else 200,
                    "url.path": "/api/v1/resource",
                },
                "events": [],
                "links": [],
            },
            {
                "ref": "s2",
                "parent_ref": "s1",
                "service_name": backend_service,
                "name": "handle_request",
                "kind": "INTERNAL",
                "offset_ms": 10.0,
                "duration_ms": 320.0,
                "status": {"code": "OK"},
                "attributes": {},
                "events": [],
                "links": [],
            },
        ]

        logs = [
            {
                "span_ref": "s1",
                "severity": "INFO",
                "body": f"Recebida requisição para cenário de teste: {anomaly.name}",
                "offset_ms": 5.0,
                "attributes": {},
            }
        ]

        if anom_id == "retry_storm":
            # 3 retry spans
            for r_idx in range(1, 4):
                spans.append(
                    {
                        "ref": f"s_retry_{r_idx}",
                        "parent_ref": "s2",
                        "service_name": backend_service,
                        "name": f"HTTP POST /downstream/call (retry #{r_idx})",
                        "kind": "CLIENT",
                        "offset_ms": 20.0 + (r_idx * 60.0),
                        "duration_ms": 50.0,
                        "status": {"code": "ERROR", "message": "Downstream timeout, retrying"},
                        "attributes": {
                            "http.request.method": "POST",
                            "http.response.status_code": 503,
                            "retry.count": r_idx,
                        },
                        "events": [
                            {
                                "name": "exception",
                                "offset_ms": 45.0,
                                "attributes": {
                                    "exception.type": "ConnectTimeout",
                                    "exception.message": "Connection timed out",
                                },
                            }
                        ],
                        "links": [],
                    }
                )
                logs.append(
                    {
                        "span_ref": f"s_retry_{r_idx}",
                        "severity": "WARN",
                        "body": f"Retry #{r_idx} falhou com HTTP 503",
                        "offset_ms": 40.0,
                        "attributes": {},
                    }
                )
            root_cause_ref = "s_retry_1"
        elif anom_id == "circuit_breaker_tripping":
            spans.append(
                {
                    "ref": "s_cb",
                    "parent_ref": "s2",
                    "service_name": backend_service,
                    "name": "circuit_breaker_call",
                    "kind": "CLIENT",
                    "offset_ms": 20.0,
                    "duration_ms": 2.0,  # Fast fail
                    "status": {"code": "ERROR", "message": "Circuit breaker is OPEN"},
                    "attributes": {
                        "circuit_breaker.state": "OPEN",
                        "http.response.status_code": 503,
                    },
                    "events": [
                        {
                            "name": "exception",
                            "offset_ms": 1.0,
                            "attributes": {
                                "exception.type": "CircuitBreakerOpenException",
                                "exception.message": "Target service unavailable",
                            },
                        }
                    ],
                    "links": [],
                }
            )
            logs.append(
                {
                    "span_ref": "s_cb",
                    "severity": "ERROR",
                    "body": "Circuito aberto! Rejeitando chamada imediata.",
                    "offset_ms": 1.0,
                    "attributes": {},
                }
            )
            root_cause_ref = "s_cb"
        else:
            # Standard downstream DB query span
            spans.append(
                {
                    "ref": "s3",
                    "parent_ref": "s2",
                    "service_name": db_service,
                    "name": "SELECT * FROM records WHERE id = $1",
                    "kind": "CLIENT",
                    "offset_ms": 30.0,
                    "duration_ms": 180.0,
                    "status": {"code": "ERROR" if "lock" in anom_id or "deadlock" in anom_id else "OK"},
                    "attributes": {
                        "db.system": "postgresql",
                        "db.operation": "SELECT",
                    },
                    "events": [],
                    "links": [],
                }
            )
            root_cause_ref = "s3"

        golden_blueprints.append(
            {
                "scenario": f"Cenário Dourado: {anomaly.name}",
                "anomaly_type": anom_id,
                "spans": spans,
                "logs": logs,
                "root_cause_ref": root_cause_ref,
                "root_cause_summary": f"Falha causada por {anomaly.name}: {anomaly.description}",
            }
        )

    target_dir = Path("tests/golden")
    target_dir.mkdir(parents=True, exist_ok=True)
    out_file = target_dir / "golden_blueprints.json"
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(golden_blueprints, f, indent=2, ensure_ascii=False)

    print(f"Generated {len(golden_blueprints)} golden blueprints into {out_file}")


if __name__ == "__main__":
    generate_golden_dataset()
