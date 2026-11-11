# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] - 2026-11-10

### Added
- Initial project structure, Pydantic v2 schemas and validation models.
- Default catalog with 20+ distributed microservice anomalies.
- Flow topology parser (`flow.yaml`) supporting sync and async calls.
- Deterministic planner and normalizer with nanosecond timestamps and seed reproducibility.
- 4-layer validation engine (Pydantic schema, NetworkX graph acyclicity, temporal invariants, PII/security).
- Multi-exporter: internal JSONL, ML labels, and OTLP/JSON compliant with Protobuf.
- Asynchronous generator with semaphore rate limiting, retry backoff, and state checkpointing (`--resume`).
- CLI commands (`init`, `plan`, `generate`, `validate`, `send`, `report`, `visualize`).
- Terminal waterfall trace visualizer using Rich.
- Docker Compose environment with OpenTelemetry Collector Contrib and Jaeger.
