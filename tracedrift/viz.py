"""Terminal visualization for OpenTelemetry trace trees and waterfalls using Rich."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.markup import escape
from rich.table import Table
from rich.text import Text


def render_trace_waterfall(trace_data: dict[str, Any], console: Console | None = None) -> None:
    """Renders a single trace as a visual waterfall and tree in the terminal."""
    if console is None:
        console = Console()

    trace_id = trace_data.get("trace_id", "unknown")
    label = trace_data.get("label", {})
    spans = trace_data.get("spans", [])
    logs = trace_data.get("logs", [])

    if not spans:
        console.print(f"[yellow]Trace {trace_id} não possui spans.[/yellow]")
        return

    # Sort spans by start_time
    sorted_spans = sorted(spans, key=lambda s: int(s["start_time_unix_nano"]))
    min_start_nano = int(sorted_spans[0]["start_time_unix_nano"])
    max_end_nano = max(int(s["end_time_unix_nano"]) for s in sorted_spans)
    total_trace_duration_ms = max(0.1, (max_end_nano - min_start_nano) / 1_000_000)

    # Title & Label summary
    is_anomalous = label.get("is_anomalous", False)
    status_tag = (
        f"[bold red]ANÔMALO: {label.get('anomaly_type')}[/bold red]"
        if is_anomalous
        else "[bold green]NORMAL[/bold green]"
    )

    console.rule(f"[bold cyan]Trace {trace_id[:8]}...{trace_id[-8:]} | {status_tag}")
    if is_anomalous and label.get("root_cause_summary"):
        console.print(f"[dim]Causa-raiz: {label.get('root_cause_summary')}[/dim]\n")

    # Build Waterfall Table
    table = Table(
        title=f"Waterfall (Duração Total: {total_trace_duration_ms:.2f} ms)",
        show_header=True,
        header_style="bold magenta",
        expand=True,
    )
    table.add_column("Serviço / Operação", style="cyan", no_wrap=False, overflow="fold", ratio=3)
    table.add_column("Kind", style="dim", width=10)
    table.add_column("Status", width=8)
    table.add_column("Duração", justify="right", width=12)
    table.add_column("Linha Temporal", ratio=4)

    timeline_bar_width = 30

    for s in sorted_spans:
        s_start = int(s["start_time_unix_nano"])
        s_end = int(s["end_time_unix_nano"])
        dur_ms = (s_end - s_start) / 1_000_000
        offset_ms = (s_start - min_start_nano) / 1_000_000

        # Timeline bar calculation
        start_ratio = offset_ms / total_trace_duration_ms
        dur_ratio = dur_ms / total_trace_duration_ms

        left_spaces = int(start_ratio * timeline_bar_width)
        bar_len = max(1, int(dur_ratio * timeline_bar_width))
        right_spaces = max(0, timeline_bar_width - (left_spaces + bar_len))

        status_code = s.get("status", {}).get("code", "OK")
        if status_code == "ERROR":
            status_text = Text("ERROR", style="bold red")
            bar_char = "█"
            bar_color = "red"
        else:
            status_text = Text("OK", style="green")
            bar_char = "■"
            bar_color = "green"

        timeline_text = Text()
        timeline_text.append(" " * left_spaces)
        timeline_text.append(bar_char * bar_len, style=f"bold {bar_color}")
        timeline_text.append(" " * right_spaces)

        kind_short = s.get("kind", "").replace("SPAN_KIND_", "")
        service_label = (
            f"[{escape(str(s.get('service_name', '')))}] {escape(str(s.get('name', '')))}"
        )

        table.add_row(
            service_label,
            kind_short,
            status_text,
            f"{dur_ms:.2f} ms",
            timeline_text,
        )

    console.print(table)

    # Correlated Logs
    if logs:
        console.print("\n[bold yellow]Logs Correlacionados:[/bold yellow]")
        for log in logs:
            sev = log.get("severity_text", "INFO")
            color = "red" if sev in ("ERROR", "FATAL") else ("yellow" if sev == "WARN" else "dim")
            console.print(
                f"  [{color}][{sev}][/{color}] [{log.get('service_name')}] {log.get('body')}"
            )
    console.print()


def visualize_traces_file(file_path: str | Path, max_traces: int = 3) -> None:
    """Reads a JSONL traces file and renders the first N traces."""
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"Arquivo não encontrado: {path}")

    console = Console()
    count = 0
    with open(path, encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            data = json.loads(line)
            render_trace_waterfall(data, console=console)
            count += 1
            if count >= max_traces:
                break
