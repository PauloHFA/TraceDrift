"""Command Line Interface for TraceDrift using Typer and Rich."""

from __future__ import annotations

import asyncio
import json
import shutil
import time
from pathlib import Path

import httpx
import typer
import yaml
from rich.console import Console
from rich.progress import BarColumn, Progress, SpinnerColumn, TextColumn, TimeRemainingColumn
from rich.table import Table

from tracedrift.client import LLMClient
from tracedrift.exporter import validate_otlp_conformance
from tracedrift.flow import FlowValidationError, load_flow_from_file
from tracedrift.generator import TraceGenerator
from tracedrift.models import AnomalyCatalog
from tracedrift.planner import create_generation_plan
from tracedrift.report import analyze_dataset, generate_dataset_card
from tracedrift.validator import TraceValidator
from tracedrift.viz import visualize_traces_file

app = typer.Typer(
    name="tracedrift",
    help="Gerador sintético de traces OpenTelemetry, logs correlacionados e anomalias de observabilidade.",
    add_completion=False,
)
console = Console()


@app.command()
def init() -> None:
    """Inicializa arquivos padrão de configuração (flow.yaml e .env.example) no diretório atual."""
    current_dir = Path.cwd()
    sample_flow = Path(__file__).parent.parent / "configs" / "e_commerce_flow.yaml"
    target_flow = current_dir / "flow.yaml"

    if not target_flow.exists():
        if sample_flow.exists():
            shutil.copy(sample_flow, target_flow)
        else:
            target_flow.write_text("# TraceDrift flow.yaml\n", encoding="utf-8")
        console.print(f"[bold green]Criado:[/bold green] {target_flow}")
    else:
        console.print(f"[yellow]Arquivo existente preservado:[/yellow] {target_flow}")

    sample_env = Path(__file__).parent.parent / ".env.example"
    target_env = current_dir / ".env.example"
    if not target_env.exists() and sample_env.exists():
        shutil.copy(sample_env, target_env)
        console.print(f"[bold green]Criado:[/bold green] {target_env}")

    console.print("\n[bold cyan]TraceDrift inicializado com sucesso![/bold cyan]")
    console.print("Edite 'flow.yaml' ou execute: [green]tracedrift plan --dry-run[/green]")


@app.command()
def plan(
    flow: Path = typer.Option(
        Path("configs/e_commerce_flow.yaml"), "--flow", "-f", help="Caminho do flow.yaml"
    ),
    anomalies: Path = typer.Option(
        Path("configs/anomalies_default.yaml"),
        "--anomalies",
        "-a",
        help="Caminho do catálogo de anomalias",
    ),
    count: int = typer.Option(50, "--count", "-n", help="Número total de traces a gerar"),
    anomaly_ratio: float = typer.Option(
        0.15, "--anomaly-ratio", "-r", help="Proporção de traces anômalos"
    ),
    seed: int = typer.Option(42, "--seed", "-s", help="Semente determinística"),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Exibe plano e estimativa de tokens sem chamar a LLM"
    ),
) -> None:
    """Calcula e visualiza o plano determinístico de geração de traces e estimativa de tokens."""
    flow_obj = load_flow_from_file(flow)
    with open(anomalies, encoding="utf-8") as f:
        catalog = AnomalyCatalog.model_validate(yaml.safe_load(f))

    gen_plan = create_generation_plan(
        flow=flow_obj,
        catalog=catalog,
        total_traces=count,
        anomaly_ratio=anomaly_ratio,
        seed=seed,
    )

    table = Table(title=f"Plano de Geração: {flow_obj.name}", expand=True)
    table.add_column("Métrica / Parâmetro", style="cyan")
    table.add_column("Valor", style="magenta")

    table.add_row("Total de Traces", str(gen_plan.total_traces))
    table.add_row("Traces Normais", str(gen_plan.normal_traces_count))
    table.add_row("Traces Anômalos", str(gen_plan.anomalous_traces_count))
    table.add_row("Proporção Alvo", f"{gen_plan.target_anomaly_ratio:.1%}")
    table.add_row("Semente Determinística", str(gen_plan.seed))
    table.add_row("Anomalias Compatíveis", f"{len(gen_plan.compatible_anomalies)} padrões")
    table.add_row("Anomalias Descartadas", f"{len(gen_plan.discarded_anomalies)} padrões")
    table.add_row("Estimativa Tokens Prompt", f"~{gen_plan.estimated_prompt_tokens:,}")
    table.add_row("Estimativa Tokens Completion", f"~{gen_plan.estimated_completion_tokens:,}")
    table.add_row("Estimativa Tokens Total", f"~{gen_plan.estimated_total_tokens:,}")

    console.print(table)

    if gen_plan.discarded_anomalies:
        console.print(
            "\n[yellow]Exemplos de anomalias descartadas por incompatibilidade com as tecnologias do fluxo:[/yellow]"
        )
        for d in gen_plan.discarded_anomalies[:3]:
            console.print(f" - [bold]{d['anomaly_id']}[/bold]: {d['reason']}")

    if dry_run:
        console.print(
            "\n[bold green]Modo --dry-run concluído. Nenhuma requisição foi enviada à LLM.[/bold green]"
        )


@app.command()
def generate(
    flow: Path = typer.Option(
        Path("configs/e_commerce_flow.yaml"), "--flow", "-f", help="Caminho do flow.yaml"
    ),
    anomalies: Path = typer.Option(
        Path("configs/anomalies_default.yaml"), "--anomalies", "-a", help="Catálogo de anomalias"
    ),
    count: int = typer.Option(50, "--count", "-n", help="Total de traces"),
    anomaly_ratio: float = typer.Option(
        0.15, "--anomaly-ratio", "-r", help="Proporção de anomalias"
    ),
    output: Path = typer.Option(
        Path("datasets/output"), "--output", "-o", help="Diretório de saída"
    ),
    seed: int = typer.Option(42, "--seed", "-s", help="Semente determinística"),
    concurrency: int = typer.Option(4, "--concurrency", "-c", help="Chamadas simultâneas à LLM"),
    max_validation_retries: int = typer.Option(
        2, "--max-validation-retries", help="Tentativas de correção"
    ),
    auto_fix: bool = typer.Option(
        True, "--auto-fix/--no-auto-fix", help="Auto-ajuste de violações temporais <= 5%"
    ),
    resume: bool = typer.Option(
        False, "--resume", help="Retoma geração anterior do ponto onde parou"
    ),
    max_tokens_budget: int | None = typer.Option(
        None, "--max-tokens-budget", help="Limite máximo de tokens"
    ),
) -> None:
    """Executa a geração em lote assíncrona com controle de concorrência e exportação de datasets."""
    flow_obj = load_flow_from_file(flow)
    with open(anomalies, encoding="utf-8") as f:
        catalog = AnomalyCatalog.model_validate(yaml.safe_load(f))

    gen_plan = create_generation_plan(
        flow=flow_obj,
        catalog=catalog,
        total_traces=count,
        anomaly_ratio=anomaly_ratio,
        seed=seed,
    )

    client = LLMClient(max_tokens_budget=max_tokens_budget)

    console.print(
        f"[bold cyan]Iniciando geração de {count} traces para o fluxo '{flow_obj.name}'...[/bold cyan]"
    )
    console.print(f"Concorrência: {concurrency} workers | Destino: {output}\n")

    progress = Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
        TimeRemainingColumn(),
        console=console,
    )

    with progress:
        task_id = progress.add_task("Gerando traces...", total=count)

        def update_progress(completed: int, _total: int) -> None:
            progress.update(task_id, completed=completed)

        generator = TraceGenerator(
            flow=flow_obj,
            plan=gen_plan,
            client=client,
            output_dir=output,
            concurrency=concurrency,
            max_validation_retries=max_validation_retries,
            auto_fix=auto_fix,
            resume=resume,
            progress_callback=update_progress,
        )

        stats = asyncio.run(generator.run())

    console.print("\n[bold green]Geração concluída![/bold green]")
    console.print(
        f" - Traces gerados com sucesso: [bold green]{stats.generated_success}[/bold green] / {count}"
    )
    console.print(f" - Traces rejeitados: [bold red]{stats.rejected_count}[/bold red]")
    console.print(f" - Retries utilizados: {stats.retries_used}")
    console.print(f" - Tokens consumidos: {stats.tokens_used:,}")
    console.print(f" - Arquivos salvos em: [bold]{output}[/bold]\n")


@app.command()
def validate(
    target: Path = typer.Argument(
        ..., help="Arquivo a ser validado (.yaml, traces.jsonl ou otlp_traces.json)"
    ),
) -> None:
    """Valida a estrutura, integridade temporal, grafo e segurança de arquivos do TraceDrift."""
    if not target.exists():
        console.print(f"[bold red]Arquivo não encontrado:[/bold red] {target}")
        raise typer.Exit(code=1)

    suffix = target.suffix.lower()

    if suffix in (".yaml", ".yml"):
        console.print(f"[cyan]Validando fluxo YAML '{target}'...[/cyan]")
        try:
            flow = load_flow_from_file(target)
            console.print(
                f"[bold green]OK:[/bold green] Fluxo '{flow.name}' é válido com {len(flow.services)} serviços e {len(flow.steps)} passos."
            )
        except FlowValidationError as err:
            console.print(f"[bold red]Erro de validação do fluxo:[/bold red]\n{err}")
            raise typer.Exit(code=1) from err

    elif suffix == ".json" and "otlp" in target.name.lower():
        console.print(f"[cyan]Validando arquivo OTLP Protobuf '{target}'...[/cyan]")
        with open(target, encoding="utf-8") as f:
            data = json.load(f)
        try:
            validate_otlp_conformance(data)
            spans_count = sum(
                len(ss.get("spans", []))
                for rs in data.get("resourceSpans", [])
                for ss in rs.get("scopeSpans", [])
            )
            console.print(
                f"[bold green]OK (RNF02):[/bold green] Arquivo OTLP/JSON parseado via Protobuf com sucesso ({spans_count} spans verificados)."
            )
        except Exception as err:
            console.print(f"[bold red]Falha na validação OTLP Protobuf:[/bold red] {err}")
            raise typer.Exit(code=1) from err

    elif suffix in (".jsonl", ".json"):
        from tracedrift.models import InternalTrace

        console.print(f"[cyan]Validando traces internos em '{target}'...[/cyan]")
        validator = TraceValidator()
        valid_count = 0
        invalid_count = 0

        with open(target, encoding="utf-8") as f:
            for idx, line in enumerate(f, start=1):
                if not line.strip():
                    continue
                try:
                    data = json.loads(line)
                    if "trace_id" in data and "spans" in data:
                        trace_obj = InternalTrace.model_validate(data)
                        rep = validator.validate_materialized_trace(trace_obj)
                        if rep.is_valid:
                            valid_count += 1
                        else:
                            invalid_count += 1
                            console.print(f"[yellow]Linha #{idx} ({trace_obj.trace_id[:8]}...): {rep.errors}[/yellow]")
                    else:
                        invalid_count += 1
                        console.print(
                            f"[yellow]Linha #{idx}: campos obrigatórios ausentes.[/yellow]"
                        )
                except Exception as err:
                    invalid_count += 1
                    console.print(f"[red]Linha #{idx}: JSON inválido: {err}[/red]")

        console.print(
            f"[bold]Resultado da validação:[/bold] {valid_count} válidos, {invalid_count} inválidos."
        )
        if invalid_count > 0:
            raise typer.Exit(code=1)


@app.command()
def send(
    file: Path = typer.Argument(
        Path("datasets/output/otlp_traces.json"), help="Arquivo OTLP/JSON a enviar"
    ),
    endpoint: str = typer.Option(
        "http://localhost:4318/v1/traces", "--endpoint", "-e", help="URL do receptor OTLP/HTTP"
    ),
    protocol: str = typer.Option("http", "--protocol", "-p", help="Protocolo (http ou grpc)"),
    replay_realtime: bool = typer.Option(
        False, "--replay-realtime", help="Desloca timestamps para o momento atual"
    ),
    yes: bool = typer.Option(False, "--yes", "-y", help="Confirma envio para endpoints não-locais"),
) -> None:
    """Envia traces gerados diretamente para um OpenTelemetry Collector (Jaeger/Tempo)."""
    if not file.exists():
        console.print(f"[bold red]Arquivo não encontrado:[/bold red] {file}")
        raise typer.Exit(code=1)

    # Safety check for non-localhost endpoints (Section 8)
    is_localhost = any(h in endpoint for h in ("localhost", "127.0.0.1", "::1"))
    if not is_localhost and not yes:
        console.print(
            f"[bold red]AVISO DE SEGURANÇA:[/bold red] O endpoint '{endpoint}' não é localhost."
        )
        console.print(
            "Para evitar poluir ambientes de teste/produção, use a flag [bold]--yes[/bold] para confirmar."
        )
        raise typer.Exit(code=1)

    with open(file, encoding="utf-8") as f:
        payload = json.load(f)

    # Replay realtime shift
    if replay_realtime:
        console.print(
            "[cyan]Ajustando timestamps para o momento atual (--replay-realtime)...[/cyan]"
        )
        now_nano = int(time.time() * 1_000_000_000)
        # Find earliest start time
        earliest_start: int | None = None
        for rs in payload.get("resourceSpans", []):
            for ss in rs.get("scopeSpans", []):
                for s in ss.get("spans", []):
                    st = int(s["startTimeUnixNano"])
                    if earliest_start is None or st < earliest_start:
                        earliest_start = st

        if earliest_start is not None:
            delta = now_nano - earliest_start
            for rs in payload.get("resourceSpans", []):
                for ss in rs.get("scopeSpans", []):
                    for s in ss.get("spans", []):
                        s["startTimeUnixNano"] = str(int(s["startTimeUnixNano"]) + delta)
                        s["endTimeUnixNano"] = str(int(s["endTimeUnixNano"]) + delta)
                        for ev in s.get("events", []):
                            ev["timeUnixNano"] = str(int(ev["timeUnixNano"]) + delta)

    console.print(
        f"[cyan]Enviando traces para [bold]{endpoint}[/bold] via OTLP/{protocol.upper()}...[/cyan]"
    )

    if protocol.lower() == "http":
        try:
            with httpx.Client(timeout=30.0) as http_cli:
                resp = http_cli.post(
                    endpoint,
                    json=payload,
                    headers={"Content-Type": "application/json"},
                )
            if resp.status_code in (200, 202):
                console.print(
                    f"[bold green]Sucesso ({resp.status_code}):[/bold green] Traces recebidos pelo coletor!"
                )
            else:
                console.print(
                    f"[bold red]Erro do coletor ({resp.status_code}):[/bold red] {resp.text}"
                )
                raise typer.Exit(code=1)
        except Exception as err:
            console.print(f"[bold red]Falha na conexão com o coletor:[/bold red] {err}")
            raise typer.Exit(code=1) from err
    else:
        console.print("[yellow]Para envio gRPC nativo, use endpoint no formato host:4317.[/yellow]")


@app.command()
def report(
    dataset_dir: Path = typer.Argument(Path("datasets/output"), help="Diretório do dataset gerado"),
    card: bool = typer.Option(True, "--card/--no-card", help="Gera o arquivo DATASET_CARD.md"),
) -> None:
    """Calcula estatísticas de latência, percentis e gera o DATASET_CARD.md."""
    if not dataset_dir.exists():
        console.print(f"[bold red]Diretório não encontrado:[/bold red] {dataset_dir}")
        raise typer.Exit(code=1)

    rep = analyze_dataset(dataset_dir)

    table = Table(title="Relatório Estatístico do Dataset", expand=True)
    table.add_column("Métrica", style="cyan")
    table.add_column("Valor", style="green")

    table.add_row("Total de Traces", f"{rep.total_traces:,}")
    table.add_row("Traces Normais", f"{rep.normal_traces:,}")
    table.add_row("Traces Anômalos", f"{rep.anomalous_traces:,}")
    table.add_row("Total de Spans", f"{rep.total_spans:,}")
    table.add_row("Média de Spans / Trace", f"{rep.avg_spans_per_trace:.2f}")
    table.add_row("Total de Logs Correlacionados", f"{rep.total_logs:,}")
    table.add_row("Taxa de Spans com Erro", f"{rep.error_spans_rate:.2%}")
    table.add_row("Percentil P50 de Duração", f"{rep.p50_duration_ms:.2f} ms")
    table.add_row("Percentil P90 de Duração", f"{rep.p90_duration_ms:.2f} ms")
    table.add_row("Percentil P99 de Duração", f"{rep.p99_duration_ms:.2f} ms")
    table.add_row("Traces Rejeitados na Validação", str(rep.rejected_traces))

    console.print(table)

    if card:
        card_path = generate_dataset_card(dataset_dir, rep)
        console.print(f"[bold green]Dataset Card gerado com sucesso:[/bold green] {card_path}")


@app.command()
def visualize(
    file: Path = typer.Argument(Path("datasets/output/traces.jsonl"), help="Arquivo traces.jsonl"),
    count: int = typer.Option(3, "--count", "-n", help="Número de traces a exibir"),
) -> None:
    """Visualiza árvores de execução e waterfall de traces no terminal."""
    try:
        visualize_traces_file(file, max_traces=count)
    except Exception as err:
        console.print(f"[bold red]Erro ao visualizar traces:[/bold red] {err}")
        raise typer.Exit(code=1) from err


if __name__ == "__main__":
    app()
