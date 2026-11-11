"""LLM-as-judge evaluation engine for assessing trace realism, failure coherence, and richness."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader

from tracedrift.client import LLMClient
from tracedrift.models import FlowDefinition


@dataclass
class JudgeScore:
    trace_id: str
    scenario: str
    anomaly_type: str
    score: float
    verdict: str
    realism_score: float
    coherence_score: float
    observability_score: float
    reasoning: str


@dataclass
class JudgeEvaluationReport:
    total_evaluated: int = 0
    average_score: float = 0.0
    average_realism: float = 0.0
    average_coherence: float = 0.0
    average_observability: float = 0.0
    scores: list[JudgeScore] = field(default_factory=list)


class TraceJudge:
    def __init__(self, client: LLMClient) -> None:
        self.client = client
        prompts_dir = Path(__file__).parent / "prompts"
        self.jinja_env = Environment(
            loader=FileSystemLoader(str(prompts_dir)),
            autoescape=False,
        )
        self.judge_template = self.jinja_env.get_template("judge_v1.j2")

    async def evaluate_single_trace(
        self,
        trace_dict: dict[str, Any],
        flow: FlowDefinition,
    ) -> JudgeScore:
        """Submits a single trace to the LLM judge."""
        trace_id = trace_dict.get("trace_id", "unknown")
        label = trace_dict.get("label", {})
        anomaly_type = label.get("anomaly_type", "normal")
        scenario = trace_dict.get("scenario", "Synthetic Trace")

        prompt = self.judge_template.render(
            flow=flow,
            anomaly_type=anomaly_type,
            trace_json=json.dumps(trace_dict, indent=2, ensure_ascii=False),
        )

        resp = await self.client.generate_json(
            prompt=prompt,
            system_prompt="Você é um avaliador rigoroso de observabilidade SRE.",
            temperature=0.2,
        )

        return JudgeScore(
            trace_id=trace_id,
            scenario=scenario,
            anomaly_type=anomaly_type,
            score=float(resp.get("score", 4.0)),
            verdict=str(resp.get("verdict", "APROVADO")),
            realism_score=float(resp.get("realism_score", 4.0)),
            coherence_score=float(resp.get("coherence_score", 4.0)),
            observability_score=float(resp.get("observability_score", 4.0)),
            reasoning=str(resp.get("reasoning", "Sem justificativa.")),
        )

    async def evaluate_traces_file(
        self,
        traces_file: str | Path,
        flow: FlowDefinition,
        max_traces: int = 5,
    ) -> JudgeEvaluationReport:
        """Evaluates up to max_traces from a traces.jsonl file."""
        report = JudgeEvaluationReport()
        path = Path(traces_file)

        traces_to_eval = []
        with open(path, encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    traces_to_eval.append(json.loads(line))
                    if len(traces_to_eval) >= max_traces:
                        break

        for trace_data in traces_to_eval:
            score_item = await self.evaluate_single_trace(trace_data, flow)
            report.scores.append(score_item)

        if report.scores:
            report.total_evaluated = len(report.scores)
            report.average_score = sum(s.score for s in report.scores) / report.total_evaluated
            report.average_realism = sum(s.realism_score for s in report.scores) / report.total_evaluated
            report.average_coherence = sum(s.coherence_score for s in report.scores) / report.total_evaluated
            report.average_observability = sum(s.observability_score for s in report.scores) / report.total_evaluated

        return report
