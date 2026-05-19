"""CLI: raporlama komutları — budget, retro, drift-check, score-tier, mutation-test."""

# SPDX-License-Identifier: FSL-1.1-Apache-2.0
# Copyright (c) 2026 ortim.dev
from __future__ import annotations
import os
import sys
from pathlib import Path
import typer
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from ortim.cli import _globals
from ortim.cli._globals import (
    console,
    _apply_invocation_overrides, _block_if_archived,
    _ensure_workspace_root, _load_codebase_summary, _resolve_project,
)
from ortim.env import env_get
from ortim.orchestrator import InvalidTransition, Project, ProjectState

_DEMO_DEFAULT_BRIEF = (
    "Build a simple CLI todo manager that adds, lists, completes, "
    "and deletes tasks. Persist tasks to a local JSON file."
)

def budget(
    project_id: str = typer.Argument(
        None,
        help="Belirli proje (opsiyonel — boşsa cwd'den keşfedilir veya toplam).",
    ),
    all_projects: bool = typer.Option(
        False, "--all",
        help="Cwd discovery atlanır — global toplam gösterilir.",
    ),
    by_provider: bool = typer.Option(
        False, "--by-provider/--total-only",
        help="Provider başına token + USD dağılımını göster",
    ),
) -> None:
    """Token kullanım ve maliyet raporu (default: cwd projesi varsa onu, yoksa toplam)."""
    from ortim.budget import BudgetTracker

    # arg verilirse resolver üzerinden AUDIT_LOG_PATH bind et (pool + project
    # mode tek yoldan); arg verilmediyse cwd discovery dene ve aynı bind'i
    # uygula; başarısızsa global default audit'e düş. --all discovery'yi atlatır.
    effective_id = project_id
    if not all_projects:
        if project_id is not None:
            project, _, _ = _resolve_project(project_id)
            effective_id = project.id
        else:
            from ortim.workspace import discover_from_cwd, ProjectStore

            loc = discover_from_cwd()
            if loc is not None:
                store = ProjectStore(loc)
                if store.exists():
                    effective_id = store.load().id
                    os.environ["AUDIT_LOG_PATH"] = str(store.audit_log_path())

    tracker = BudgetTracker()
    report = tracker.report(effective_id)

    title_scope = "all" if not effective_id else effective_id
    table = Table(title=f"Budget Report ({title_scope})")
    table.add_column("Metric", style="cyan")
    table.add_column("Value", justify="right")
    table.add_row("LLM calls", str(report.entry_count))
    table.add_row("Input tokens", f"{report.input_tokens:,}")
    table.add_row("Output tokens", f"{report.output_tokens:,}")
    table.add_row("Total tokens", f"{report.total_tokens:,}")
    table.add_row("Estimated cost (USD)", f"${report.estimated_cost_usd:.4f}")
    console.print(table)

    if by_provider and report.per_provider:
        prov_table = Table(title="Per-provider breakdown")
        prov_table.add_column("Provider", style="cyan")
        prov_table.add_column("Calls", justify="right")
        prov_table.add_column("Input tok", justify="right")
        prov_table.add_column("Output tok", justify="right")
        prov_table.add_column("Cost (USD)", justify="right")
        for prov in sorted(report.per_provider):
            br = report.per_provider[prov]
            prov_table.add_row(
                prov,
                str(br.entry_count),
                f"{br.input_tokens:,}",
                f"{br.output_tokens:,}",
                f"${br.estimated_cost_usd:.4f}",
            )
        console.print(prov_table)
    elif by_provider:
        console.print("[dim](no provider data — audit log may be empty)[/dim]")
def drift_check(
    project_id: str = typer.Argument(
        None,
        help="Workspace ID. Boş bırakılırsa cwd'den keşfedilir.",
    ),
    as_json: bool = typer.Option(
        False, "--json",
        help="JSON çıktısı (otomasyon için)",
    ),
) -> None:
    """Multi-cycle integrity check — RFC ↔ DAG ↔ status ↔ audit alignment.

    M3.1.1 validators DAG generation sırasında zaten çoğunu enforce ediyor;
    drift-check post-hoc bir sanity gate: artefakt manuel düzenlenmiş veya
    orchestrator bir gap'i kaçırmışsa burada yakalanır.

    Exit kodları:
      0 — drift yok
      2 — sadece warning'ler (status ↔ audit mismatch gibi)
      3 — error'lar (module scope ihlali, ID continuity kırılması, ...)
    """
    import json as _json

    from ortim.audit import AuditLogger
    from ortim.extend import drift_to_json_dict, inspect_drift

    project, store, _ = _resolve_project(project_id)
    workspace = store.metadata_dir

    try:
        report = inspect_drift(workspace, project_id=project.id)
    except FileNotFoundError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(code=1) from None

    audit = AuditLogger(path=store.audit_log_path())
    audit.log(
        "drift_check_run",
        project_id=project.id,
        cycle_count=report.cycle_count,
        error_count=len(report.errors),
        warning_count=len(report.warnings),
        findings=[
            {"kind": f.kind, "severity": f.severity, "entity": f.entity}
            for f in report.findings[:20]
        ],
    )

    if as_json:
        console.print_json(_json.dumps(drift_to_json_dict(report)))
    else:
        console.print(
            f"[bold]Drift Check — {project.id}[/bold] "
            f"(cycles inspected: {report.cycle_count})"
        )
        if report.is_clean:
            console.print("[green]No drift detected.[/green]")
        else:
            for f in report.findings:
                tag = "[red]ERROR[/red]" if f.severity == "error" else "[yellow]WARN[/yellow]"
                cycle = f" (cycle {f.cycle})" if f.cycle is not None else ""
                console.print(f"  {tag}  {f.kind}  {f.entity}{cycle}")
                console.print(f"         {f.message}")
            console.print(
                f"\nTotal: {len(report.errors)} error(s), "
                f"{len(report.warnings)} warning(s)"
            )

    if report.errors:
        raise typer.Exit(code=3)
    if report.warnings:
        raise typer.Exit(code=2)
def retro(
    project_id: str = typer.Argument(
        None,
        help="Workspace ID. Boş bırakılırsa cwd'den keşfedilir.",
    ),
    per_task: bool = typer.Option(
        False, "--per-task",
        help="Sadece per-task attempt tablosu (rollup gizlenir)",
    ),
    category: str = typer.Option(
        "", "--category",
        help="Tek kategori filtresi (worker, reviewer, architect, ...)",
    ),
    as_json: bool = typer.Option(
        False, "--json",
        help="JSON çıktısı (otomasyon / dashboard için)",
    ),
) -> None:
    """Retrospective rollup — audit log üzerinden çok-eksenli rapor.

    Eksenler:
      * Per-category token + USD breakdown
      * Per-task attempt distribution (worker / sandbox / reviewer rejects)
      * Skill triggers (executor_skill_resolved events)
      * Headline: total LLM calls, retry rate, HITL escalations, p50/p95 wall

    `budget` komutuyla aynı kaynaktan okur ama daha geniş eksenlerde rollup.
    """
    import json as _json

    from ortim.audit import aggregate, to_json_dict

    project, _, _ = _resolve_project(project_id)
    # aggregate() expects (project_id, workspace_root) — pool layout assumption.
    # Both pool and project mode workspaces have a per-workspace audit.jsonl
    # accessible via AUDIT_LOG_PATH (set by _resolve_project); aggregate uses
    # it transparently when no workspace_root match is found.
    report = aggregate(project.id, workspace_root=_globals.WORKSPACE_ROOT)

    if as_json:
        console.print_json(_json.dumps(to_json_dict(report)))
        return

    if report.total_llm_calls == 0 and not report.per_task:
        console.print(
            f"[yellow]No audit data found for project '{project.id}'.[/yellow]"
        )
        console.print(
            "[dim](Either the project hasn't run yet, or AUDIT_LOG_PATH "
            "points elsewhere.)[/dim]"
        )
        return

    if not per_task:
        headline = Table(title=f"Retro — {project.id}")
        headline.add_column("Metric", style="cyan")
        headline.add_column("Value", justify="right")
        headline.add_row("Total LLM calls", f"{report.total_llm_calls:,}")
        headline.add_row("Retry rate", f"{report.retry_rate * 100:.1f}%")
        headline.add_row("HITL escalations", str(report.hitl_escalations))
        headline.add_row(
            "Task wall p50",
            f"{report.wall_seconds_p50:.1f}s"
            if report.wall_seconds_p50 is not None
            else "—",
        )
        headline.add_row(
            "Task wall p95",
            f"{report.wall_seconds_p95:.1f}s"
            if report.wall_seconds_p95 is not None
            else "—",
        )
        console.print(headline)

        cat_table = Table(title="Per-category rollup")
        cat_table.add_column("Category", style="cyan")
        cat_table.add_column("Calls", justify="right")
        cat_table.add_column("Input tok", justify="right")
        cat_table.add_column("Output tok", justify="right")
        cat_table.add_column("Cost (USD)", justify="right")
        rows = report.per_category
        if category:
            rows = [r for r in rows if r.category == category.lower()]
        if rows:
            for r in rows:
                cat_table.add_row(
                    r.category,
                    str(r.entry_count),
                    f"{r.input_tokens:,}",
                    f"{r.output_tokens:,}",
                    f"${r.estimated_cost_usd:.4f}",
                )
            console.print(cat_table)
        elif category:
            console.print(
                f"[dim](no rows for category '{category}')[/dim]"
            )

    task_table = Table(title="Per-task attempts")
    task_table.add_column("Task", style="cyan")
    task_table.add_column("Worker OK", justify="right")
    task_table.add_column("Sandbox", justify="right")
    task_table.add_column("Reject", justify="right")
    task_table.add_column("Status", style="dim")
    task_table.add_column("Wall (s)", justify="right")
    for t in report.per_task:
        task_table.add_row(
            t.task_id,
            str(t.worker_attempts),
            str(t.sandbox_violations),
            str(t.reviewer_rejects),
            t.final_status or "—",
            f"{t.wall_seconds:.1f}" if t.wall_seconds is not None else "—",
        )
    if report.per_task:
        console.print(task_table)

    if not per_task and report.skill_triggers:
        skill_table = Table(title="Skill triggers")
        skill_table.add_column("Skill", style="cyan")
        skill_table.add_column("Count", justify="right")
        skill_table.add_column("Last task", style="dim")
        for s in report.skill_triggers:
            skill_table.add_row(
                s.skill_name,
                str(s.trigger_count),
                s.last_task_id or "—",
            )
        console.print(skill_table)
def score_tier_cmd(
    has_state: bool = typer.Option(True, "--state/--no-state"),
    has_auth: bool = typer.Option(True, "--auth/--no-auth"),
    scale: str = typer.Option("unknown", help="small | medium | large | unknown"),
    team: str = typer.Option("unknown", help="solo | small | large | unknown"),
    ops: str = typer.Option("unknown", help="low | medium | high | unknown"),
    compliance: str = typer.Option("", help="comma-separated, e.g. KVKK,GDPR"),
    audit_heavy: bool = False,
    realtime: bool = False,
    bursty: bool = False,
) -> None:
    """Verili input'larla tier seçim algoritmasını koştur (deterministic, API key gerekmez)."""
    from ortim.architecture import (
        GoldenPathInputs,
        OpsCapacity,
        Scale,
        TeamSize,
        score_all,
    )

    inputs = GoldenPathInputs(
        has_persistent_state=has_state,
        has_auth=has_auth,
        compliance=[c.strip() for c in compliance.split(",") if c.strip()],
        expected_scale=Scale(scale),
        team_size=TeamSize(team),
        ops_capacity=OpsCapacity(ops),
        audit_heavy=audit_heavy,
        realtime_required=realtime,
        bursty_workload=bursty,
    )

    scores = score_all(inputs)
    table = Table(title="Tier Scoring")
    table.add_column("Tier")
    table.add_column("Name")
    table.add_column("Score", justify="right")
    table.add_column("Status")
    table.add_column("Notes")
    for s in scores:
        if s.disqualified:
            status = "[red]BLOCKED[/red]"
            notes = "; ".join(s.blockers)
        else:
            status = "[green]OK[/green]"
            notes = "; ".join(s.pros[:2])
        table.add_row(s.tier.value, s.name, str(s.score), status, notes)
    console.print(table)

    valid = [s for s in scores if not s.disqualified]
    if valid:
        winner = max(valid, key=lambda s: s.score)
        console.print(
            f"\n[bold]Selected:[/bold] [green]{winner.tier.value}[/green] "
            f"({winner.name}) — score {winner.score}"
        )
def mutation_test(
    live: bool = typer.Option(
        False,
        "--live",
        help="Çağrıları gerçek bir Reviewer LLM'ine gönder. Olmadan komut "
        "case listesini ve metadata'yı bastırır (zero cost).",
    ),
    provider: str = typer.Option(
        "deepseek",
        "--provider",
        help="--live için Reviewer provider'ı (anthropic / deepseek / "
        "ollama). Role-spesifik override mevcutsa onu kullanır.",
    ),
    bug_class: str = typer.Option(
        "",
        "--bug-class",
        help="Sadece bu bug class'ın case'lerini çalıştır. Boş ise "
        "DEFAULT_CASES'in tamamı.",
    ),
) -> None:
    """Faz 2.3 — Reviewer mutation testing.

    Bilinen-bug fixture'larını Reviewer'a 'Worker output'muş gibi gönderir;
    catch rate (loose + strict) ölçer. Hedef ≥%70 strict; <%50 → Reviewer
    prompt sertleştirme tetiği.

    Default --dry-run modu sadece case listesini bastırır (LLM çağrısı yok).
    --live için Reviewer modeli üzerinden gerçek çağrı yapar (DeepSeek
    örnek tahmini: 6 case × ~1500 token ≈ \\$0.02).
    """
    from ortim.mutation import DEFAULT_CASES, run_mutation_suite

    cases = list(DEFAULT_CASES)
    if bug_class:
        cases = [c for c in cases if c.bug_class == bug_class]
        if not cases:
            valid = sorted({c.bug_class for c in DEFAULT_CASES})
            console.print(
                f"[red]Unknown --bug-class={bug_class!r}. "
                f"Valid: {', '.join(valid)}[/red]"
            )
            raise typer.Exit(1)

    if not live:
        console.print(
            f"[cyan]Mutation suite — {len(cases)} cases "
            f"(--live olmadan, sadece listeleme):[/cyan]"
        )
        table = Table(show_header=True)
        table.add_column("Bug class")
        table.add_column("Case")
        table.add_column("Language")
        table.add_column("Keywords (strict)")
        for c in cases:
            table.add_row(
                c.bug_class,
                c.name,
                c.language,
                ", ".join(c.bug_keywords[:3])
                + (" …" if len(c.bug_keywords) > 3 else ""),
            )
        console.print(table)
        console.print(
            "\n[dim]--live ekleyince Reviewer LLM'ine gönderilir. "
            f"Provider override: --provider={provider}[/dim]"
        )
        return

    # Live mode — instantiate a real Reviewer.
    from ortim.audit import AuditLogger
    from ortim.executor.reviewer import CodeReviewerAgent
    from ortim.llm import client_for
    from ortim.memory import MemoryLoader

    memory = MemoryLoader(_globals.REPO_ROOT)
    audit_path = _globals.REPO_ROOT / "ortim" / "audit" / "mutation_decisions.jsonl"
    audit = AuditLogger(path=audit_path)
    llm = client_for("reviewer", provider=provider)
    reviewer = CodeReviewerAgent(llm=llm, memory=memory, audit=audit)

    console.print(
        f"[cyan]Mutation suite — {len(cases)} cases, "
        f"reviewer={llm.provider}/{llm.model}[/cyan]\n"
    )
    report = run_mutation_suite(cases, reviewer)
    console.print(report.render())

    table = Table(title="\nPer-case detail", show_header=True)
    table.add_column("Class")
    table.add_column("Case")
    table.add_column("Loose")
    table.add_column("Strict")
    table.add_column("Verdict summary")
    for r in report.cases:
        loose_mark = "[green]✓[/green]" if r.caught_loose else "[red]✗[/red]"
        strict_mark = "[green]✓[/green]" if r.caught_strict else "[red]✗[/red]"
        summary = r.error if r.error else r.verdict_summary
        table.add_row(r.bug_class, r.case_name, loose_mark, strict_mark, summary)
    console.print(table)

    if report.strict_rate < 0.50:
        console.print(
            "\n[red]Strict catch rate < 50% — Reviewer prompt sertleştirme "
            "tetiği. Roadmap 2.3 acceptance criteria not met.[/red]"
        )
        raise typer.Exit(1)
    if report.strict_rate < 0.70:
        console.print(
            "\n[yellow]Strict catch rate < 70% — target henüz tutmuyor. "
            "Acceptable for v0.9 lansman ama prompt iteration önerilir.[/yellow]"
        )


def register(app: typer.Typer) -> None:
    """Wire reporting-module commands onto the top-level Typer app."""
    app.command()(budget)
    app.command("drift-check")(drift_check)
    app.command()(retro)
    app.command("score-tier")(score_tier_cmd)
    app.command("mutation-test")(mutation_test)
