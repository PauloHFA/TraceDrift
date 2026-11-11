"""Asynchronous trace generation orchestrator with concurrency, resume, and corrective retries."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import aiofiles
from jinja2 import Environment, FileSystemLoader

from tracedrift.client import LLMClient, TokenBudgetExceededError
from tracedrift.exporter import StreamingTraceExporter
from tracedrift.models import FlowDefinition
from tracedrift.normalizer import TraceNormalizer
from tracedrift.planner import GenerationPlan, PlannedTrace
from tracedrift.validator import TraceValidator


@dataclass
class GenerationStats:
    total_requested: int = 0
    generated_success: int = 0
    rejected_count: int = 0
    retries_used: int = 0
    layer_failures: dict[int, int] = field(default_factory=lambda: {1: 0, 2: 0, 3: 0, 4: 0})
    tokens_used: int = 0


class TraceGenerator:
    def __init__(
        self,
        flow: FlowDefinition,
        plan: GenerationPlan,
        client: LLMClient,
        output_dir: str | Path = "datasets/output",
        concurrency: int = 4,
        max_validation_retries: int = 2,
        auto_fix: bool = True,
        resume: bool = False,
        progress_callback: Callable[[int, int], None] | None = None,
    ) -> None:
        self.flow = flow
        self.plan = plan
        self.client = client
        self.output_dir = Path(output_dir)
        self.concurrency = concurrency
        self.max_validation_retries = max_validation_retries
        self.auto_fix = auto_fix
        self.resume = resume
        self.progress_callback = progress_callback

        self.validator = TraceValidator()
        self.normalizer = TraceNormalizer(seed=plan.seed, auto_fix=auto_fix)
        self.exporter = StreamingTraceExporter(self.output_dir)

        self.state_file = self.output_dir / ".tracedrift_state.json"
        self.rejected_file = self.output_dir / "rejected.jsonl"

        # Setup Jinja2 templates
        prompts_dir = Path(__file__).parent / "prompts"
        self.jinja_env = Environment(
            loader=FileSystemLoader(str(prompts_dir)),
            autoescape=False,
        )
        self.blueprint_template = self.jinja_env.get_template("blueprint_v1.j2")
        self.correction_template = self.jinja_env.get_template("correction_v1.j2")

        self.stats = GenerationStats(total_requested=plan.total_traces)
        self._completed_indices: set[int] = set()
        self._lock = asyncio.Lock()

    def _load_resume_state(self) -> None:
        """Loads completed trace indices from existing state file."""
        if self.resume and self.state_file.exists():
            try:
                with open(self.state_file, encoding="utf-8") as f:
                    data = json.load(f)
                    self._completed_indices = set(data.get("completed_indices", []))
                    self.stats.generated_success = len(self._completed_indices)
            except Exception:
                self._completed_indices = set()

    async def _save_checkpoint(self, trace_index: int) -> None:
        """Saves completed trace index to state file for resume capability."""
        async with self._lock:
            self._completed_indices.add(trace_index)
            state_data = {
                "flow_name": self.flow.name,
                "seed": self.plan.seed,
                "total_traces": self.plan.total_traces,
                "completed_indices": sorted(self._completed_indices),
            }
            async with aiofiles.open(self.state_file, "w", encoding="utf-8") as f:
                await f.write(json.dumps(state_data, indent=2))

    async def _log_rejected(
        self,
        planned: PlannedTrace,
        reason: str,
        layer: int | None,
        last_raw_payload: dict[str, Any] | None = None,
    ) -> None:
        """Appends unrecoverable trace to rejected.jsonl."""
        async with self._lock:
            self.stats.rejected_count += 1
            if layer in self.stats.layer_failures:
                self.stats.layer_failures[layer] += 1

            record = {
                "trace_index": planned.index,
                "scheduled_time_iso": planned.scheduled_time_iso,
                "anomaly_type": planned.anomaly_type,
                "layer_failed": layer,
                "reason": reason,
                "raw_payload": last_raw_payload,
            }
            async with aiofiles.open(self.rejected_file, "a", encoding="utf-8") as f:
                await f.write(json.dumps(record, ensure_ascii=False) + "\n")

    async def _process_single_trace(
        self,
        planned: PlannedTrace,
        semaphore: asyncio.Semaphore,
    ) -> None:
        """Generates, validates, and normalizes a single trace with retry logic."""
        if planned.index in self._completed_indices:
            return

        async with semaphore:
            prompt_content = self.blueprint_template.render(
                flow=self.flow,
                is_anomalous=planned.is_anomalous,
                anomaly=planned.anomaly_pattern,
            )

            raw_blueprint: dict[str, Any] | None = None
            last_errors: list[str] = []
            attempt = 0

            while attempt <= self.max_validation_retries:
                try:
                    if attempt == 0:
                        raw_blueprint = await self.client.generate_json(prompt_content)
                    else:
                        async with self._lock:
                            self.stats.retries_used += 1

                        corr_prompt = self.correction_template.render(
                            errors=last_errors,
                            previous_blueprint_json=json.dumps(
                                raw_blueprint, indent=2, ensure_ascii=False
                            ),
                        )
                        raw_blueprint = await self.client.generate_json(corr_prompt)
                except TokenBudgetExceededError:
                    raise
                except Exception as err:
                    last_errors = [f"Erro na chamada do modelo: {err}"]
                    attempt += 1
                    continue

                # 1. Validate Blueprint (Layer 1 & 2)
                blueprint_obj, bp_report = self.validator.validate_blueprint(raw_blueprint)
                if not bp_report.is_valid:
                    last_errors = bp_report.errors
                    attempt += 1
                    continue

                assert blueprint_obj is not None

                # 2. Normalize to InternalTrace
                try:
                    internal_trace, _ = self.normalizer.normalize(
                        blueprint=blueprint_obj,
                        trace_index=planned.index,
                        base_time_unix_nano=planned.scheduled_time_unix_nano,
                        model_name=self.client.model,
                    )
                except Exception as err:
                    last_errors = [f"Erro de normalização: {err}"]
                    attempt += 1
                    continue

                # 3. Validate Materialized Trace (Layer 3 & 4)
                mat_report = self.validator.validate_materialized_trace(
                    trace=internal_trace,
                    expected_anomaly_type=planned.anomaly_type,
                )
                if not mat_report.is_valid:
                    last_errors = mat_report.errors
                    attempt += 1
                    continue

                # Success! Write trace and save checkpoint
                await self.exporter.write_trace(internal_trace)
                await self._save_checkpoint(planned.index)

                async with self._lock:
                    self.stats.generated_success += 1
                    if self.progress_callback:
                        self.progress_callback(self.stats.generated_success, self.plan.total_traces)
                return

            # Exhausted retries
            await self._log_rejected(
                planned=planned,
                reason="; ".join(last_errors),
                layer=3,
                last_raw_payload=raw_blueprint,
            )

    async def run(self) -> GenerationStats:
        """Executes full batch generation according to plan."""
        self._load_resume_state()
        semaphore = asyncio.Semaphore(self.concurrency)

        tasks = [
            self._process_single_trace(planned, semaphore)
            for planned in self.plan.traces
            if planned.index not in self._completed_indices
        ]

        try:
            await asyncio.gather(*tasks)
        except asyncio.CancelledError:
            # Clean exit on Ctrl+C / cancellation
            pass
        finally:
            await self.exporter.finalize()
            self.stats.tokens_used = self.client.total_tokens_used

        return self.stats
