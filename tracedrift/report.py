"""Dataset reporting and DATASET_CARD.md generation."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np


@dataclass
class DatasetReport:
    total_traces: int = 0
    total_spans: int = 0
    total_logs: int = 0
    normal_traces: int = 0
    anomalous_traces: int = 0
    error_spans_count: int = 0
    error_spans_rate: float = 0.0
    avg_spans_per_trace: float = 0.0
    p50_duration_ms: float = 0.0
    p90_duration_ms: float = 0.0
    p95_duration_ms: float = 0.0
    p99_duration_ms: float = 0.0
    anomalies_distribution: dict[str, int] = field(default_factory=dict)
    services_distribution: dict[str, int] = field(default_factory=dict)
    rejected_traces: int = 0


def analyze_dataset(dataset_dir: str | Path) -> DatasetReport:
    """Reads a dataset output directory and computes comprehensive statistics."""
    dir_path = Path(dataset_dir)
    traces_file = dir_path / "traces.jsonl"
    rejected_file = dir_path / "rejected.jsonl"

    if not traces_file.exists():
        raise FileNotFoundError(f"Arquivo traces.jsonl não encontrado em '{dir_path}'.")

    report = DatasetReport()
    durations_ms: list[float] = []

    with open(traces_file, encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            data = json.loads(line)
            report.total_traces += 1

            label = data.get("label", {})
            anom_type = label.get("anomaly_type", "normal")
            if label.get("is_anomalous", False):
                report.anomalous_traces += 1
            else:
                report.normal_traces += 1

            report.anomalies_distribution[anom_type] = (
                report.anomalies_distribution.get(anom_type, 0) + 1
            )

            spans = data.get("spans", [])
            report.total_spans += len(spans)
            logs = data.get("logs", [])
            report.total_logs += len(logs)

            if spans:
                starts = [int(s["start_time_unix_nano"]) for s in spans]
                ends = [int(s["end_time_unix_nano"]) for s in spans]
                trace_dur_ms = (max(ends) - min(starts)) / 1_000_000
                durations_ms.append(trace_dur_ms)

                for s in spans:
                    svc = s.get("service_name", "unknown")
                    report.services_distribution[svc] = report.services_distribution.get(svc, 0) + 1
                    status_code = s.get("status", {}).get("code")
                    if status_code in ("ERROR", 2):
                        report.error_spans_count += 1

    # Rejected traces
    if rejected_file.exists():
        with open(rejected_file, encoding="utf-8") as f:
            report.rejected_traces = sum(1 for line in f if line.strip())

    if report.total_traces > 0:
        report.avg_spans_per_trace = report.total_spans / report.total_traces
    if report.total_spans > 0:
        report.error_spans_rate = report.error_spans_count / report.total_spans

    if durations_ms:
        dur_arr = np.array(durations_ms)
        report.p50_duration_ms = float(np.percentile(dur_arr, 50))
        report.p90_duration_ms = float(np.percentile(dur_arr, 90))
        report.p95_duration_ms = float(np.percentile(dur_arr, 95))
        report.p99_duration_ms = float(np.percentile(dur_arr, 99))

    return report


def generate_dataset_card(
    dataset_dir: str | Path,
    report: DatasetReport,
    model_name: str = "gpt-4o-mini",
    seed: int = 42,
    output_path: str | Path | None = None,
) -> Path:
    """Generates DATASET_CARD.md summarizing dataset characteristics and synthetic nature."""
    target = Path(dataset_dir) / "DATASET_CARD.md" if output_path is None else Path(output_path)

    card_content = f"""# Dataset Card — TraceDrift Synthetic Dataset

## Visão Geral
Este dataset foi gerado de forma **100% sintética** pelo **TraceDrift**, uma ferramenta para simulação realista de rastreamento distribuído (OpenTelemetry spans) e logs correlacionados com padrões de falha e degradações de microsserviços.

- **Natureza dos Dados**: Sintético (Livre de PII, senhas ou credenciais de produção).
- **Modelo Gerador**: `{model_name}`
- **Semente Aleatória**: `{seed}`
- **Convenções Semânticas OTel**: `1.25.0`
- **Licença**: [Apache-2.0](https://www.apache.org/licenses/LICENSE-2.0)

---

## Estatísticas do Dataset

| Métrica | Valor |
| :--- | :--- |
| **Total de Traces** | {report.total_traces:,} |
| **Traces Normais (Linha de Base)** | {report.normal_traces:,} ({report.normal_traces / max(1, report.total_traces):.1%}) |
| **Traces Anômalos** | {report.anomalous_traces:,} ({report.anomalous_traces / max(1, report.total_traces):.1%}) |
| **Total de Spans** | {report.total_spans:,} |
| **Média de Spans por Trace** | {report.avg_spans_per_trace:.2f} |
| **Total de Logs Correlacionados** | {report.total_logs:,} |
| **Spans com Erro** | {report.error_spans_count:,} ({report.error_spans_rate:.2%}) |
| **Traces Rejeitados na Validação** | {report.rejected_traces:,} |

### Percentis de Duração dos Traces
- **P50 (Mediana)**: {report.p50_duration_ms:.2f} ms
- **P90**: {report.p90_duration_ms:.2f} ms
- **P95**: {report.p95_duration_ms:.2f} ms
- **P99**: {report.p99_duration_ms:.2f} ms

---

## Distribuição de Anomalias

| Padrão de Anomalia | Contagem de Traces |
| :--- | :--- |
"""

    for anom, cnt in sorted(
        report.anomalies_distribution.items(), key=lambda x: x[1], reverse=True
    ):
        card_content += f"| `{anom}` | {cnt:,} |\n"

    card_content += """
---

## Limitações e Uso Recomendado
1. **Treinamento e Avaliação**: Indicado para treino supervisionado ou não supervisionado de detectores de anomalias em observabilidade.
2. **Testes de Plataforma**: Indicado para validação de ingestão em Jaeger, Tempo, SigNoz e OpenTelemetry Collector.
3. **Não utilizar para dimensionamento físico direto**: Os dados representam simulações probabilísticas e estruturadas, e não captura de profiling em nível de CPU/kernel.
"""

    with open(target, "w", encoding="utf-8") as f:
        f.write(card_content)

    return target
