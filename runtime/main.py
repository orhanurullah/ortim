# SPDX-License-Identifier: FSL-1.1-Apache-2.0
# Copyright (c) 2026 ortim.dev
"""CLI entry point for Ortim.

Babel + Analyst + Architect + Orchestrator + Worker + Reviewer chain wired.
`run` command drives intake → babel → PRD draft → ... → DAG execution.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import typer
from dotenv import load_dotenv
from rich.console import Console
from rich.table import Table

# Windows PowerShell defaults to cp1252/cp1254 which can't encode `[✓]`,
# em-dashes, or any character a Reviewer/Worker may legitimately surface.
# Force UTF-8 with replace fallback so a legitimate reject never crashes
# the CLI mid-render. No-op on platforms whose stdio is already UTF-8.
for _stream in (sys.stdout, sys.stderr):
    reconfigure = getattr(_stream, "reconfigure", None)
    if reconfigure is not None:
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except (OSError, ValueError):
            pass

from runtime.orchestrator import (
    InvalidTransition,
    Project,
    ProjectState,
    bootstrap_brownfield,
)

load_dotenv()

app = typer.Typer(help="Ortim — agentic dev pipeline (v0.6d)")
console = Console()

WORKSPACE_ROOT = Path(os.getenv("WORKSPACE_ROOT", "./workspaces"))
REPO_ROOT = Path(__file__).resolve().parent.parent


def _ensure_workspace_root() -> None:
    WORKSPACE_ROOT.mkdir(parents=True, exist_ok=True)


def _load_codebase_summary(project: "Project", workspace: Path):
    """Load the cached codebase summary for a brownfield project, or None.

    Greenfield projects never have a codebase.json — caller must tolerate None.
    A corrupt cache is also treated as None so a stale file doesn't crash
    runs; the operator can `ortim rescan <id>` to repair.
    """
    if not project.is_brownfield:
        return None
    cache = workspace / ".cache" / "codebase.json"
    if not cache.exists():
        return None
    from runtime.codebase import CodebaseSummary

    try:
        return CodebaseSummary.model_validate_json(cache.read_text(encoding="utf-8"))
    except Exception:
        return None


@app.command()
def new(
    brief: str = typer.Argument(..., help="Türkçe proje özeti"),
    name: str = typer.Option("untitled", help="Proje kısa adı"),
    from_existing: Path = typer.Option(
        None,
        "--from-existing",
        help="Brownfield: mevcut proje dizini. Babel atlanır, codebase taranır.",
    ),
    link_mode: str = typer.Option(
        "symlink",
        help="--from-existing için: symlink (hızlı, dev-mode gerekli) veya copy",
    ),
) -> None:
    """Yeni proje aç (greenfield veya --from-existing ile brownfield)."""
    _ensure_workspace_root()

    if from_existing is not None:
        try:
            project, mode = bootstrap_brownfield(
                name=name,
                brief_tr=brief,
                source_path=from_existing,
                workspace_root=WORKSPACE_ROOT,
                link_mode=link_mode,
            )
        except FileNotFoundError as e:
            console.print(f"[red]{e}[/red]")
            raise typer.Exit(1)
        console.print(
            f"[green]Brownfield[/green] [bold]{project.id}[/bold] ({name}) "
            f"materialized via [cyan]{mode}[/cyan]"
        )
        console.print(f"State: [cyan]{project.state.value}[/cyan]")
        console.print(f"App class: [cyan]{project.app_class}[/cyan]")
        console.print(
            f"Workspace: {project.workspace_path(project.id, WORKSPACE_ROOT)}"
        )
        if mode == "copy-fallback":
            console.print(
                "[yellow]Symlink failed (likely needs Developer Mode); "
                "fell back to copy.[/yellow]"
            )
        console.print(
            f"\nNext: [cyan]ortim inspect {project.id}[/cyan] to verify scan, "
            f"then [cyan]ortim run {project.id}[/cyan] (Architect skips Babel)."
        )
        return

    project = Project(name=name, initial_brief_tr=brief)
    project.save(WORKSPACE_ROOT)
    console.print(f"[green]Created[/green] [bold]{project.id}[/bold] ({name})")
    console.print(f"State: [cyan]{project.state.value}[/cyan]")
    console.print(f"Workspace: {project.workspace_path(project.id, WORKSPACE_ROOT)}")
    console.print(
        f"\nNext: [cyan]ortim run {project.id}[/cyan] "
        "(Babel + Analyst, requires ANTHROPIC_API_KEY)"
    )


@app.command()
def status(project_id: str) -> None:
    """Proje detayını göster."""
    try:
        project = Project.load(project_id, WORKSPACE_ROOT)
    except FileNotFoundError:
        console.print(f"[red]Project {project_id} not found[/red]")
        raise typer.Exit(1)

    table = Table(title=f"Project {project.id}")
    table.add_column("Field", style="cyan")
    table.add_column("Value")
    table.add_row("Name", project.name)
    table.add_row("State", project.state.value)
    table.add_row("Created", project.created_at)
    table.add_row("History", str(len(project.history)))
    if gate := project.awaiting_human():
        table.add_row("[yellow]HITL[/yellow]", gate)
    console.print(table)

    if project.history:
        history_table = Table(title="History")
        history_table.add_column("Time")
        history_table.add_column("From")
        history_table.add_column("To")
        history_table.add_column("Actor")
        history_table.add_column("Note")
        for event in project.history:
            history_table.add_row(
                event.timestamp,
                event.from_state.value,
                event.to_state.value,
                event.actor,
                event.note,
            )
        console.print(history_table)


@app.command()
def inspect(project_id: str) -> None:
    """Brownfield projenin codebase scan özetini göster."""
    try:
        project = Project.load(project_id, WORKSPACE_ROOT)
    except FileNotFoundError:
        console.print(f"[red]Project {project_id} not found[/red]")
        raise typer.Exit(1)
    if not project.is_brownfield:
        console.print(
            f"[yellow]{project_id} is not a brownfield project (no codebase scan).[/yellow]"
        )
        return

    ws = Project.workspace_path(project.id, WORKSPACE_ROOT, project.tenant_id)
    cache = ws / ".cache" / "codebase.json"
    if not cache.exists():
        console.print(
            f"[yellow]No codebase.json at {cache}. Try `ortim rescan {project_id}`.[/yellow]"
        )
        raise typer.Exit(1)

    from runtime.codebase import CodebaseSummary

    summary = CodebaseSummary.model_validate_json(cache.read_text(encoding="utf-8"))
    table = Table(title=f"Codebase summary — {project_id}")
    table.add_column("Field", style="cyan")
    table.add_column("Value")
    table.add_row("Source", project.source_path or "?")
    table.add_row("App class hint", summary.app_class_hint or "?")
    table.add_row("File count", f"{summary.file_count} (truncated: {summary.truncated})")
    table.add_row(
        "Frameworks",
        ", ".join(
            f"{f.name}@{f.version}" if f.version else f.name
            for f in summary.frameworks
        )
        or "(none detected)",
    )
    table.add_row(
        "Top languages",
        ", ".join(
            f"{ext.lstrip('.')}={n}"
            for ext, n in sorted(summary.languages.items(), key=lambda kv: -kv[1])[:5]
        ),
    )
    table.add_row("Modules", str(len(summary.modules)))
    console.print(table)


@app.command()
def rescan(project_id: str) -> None:
    """Brownfield projenin codebase summary'sini yeniden tara."""
    try:
        project = Project.load(project_id, WORKSPACE_ROOT)
    except FileNotFoundError:
        console.print(f"[red]Project {project_id} not found[/red]")
        raise typer.Exit(1)
    if not project.is_brownfield:
        console.print(
            f"[yellow]{project_id} is not a brownfield project; nothing to rescan.[/yellow]"
        )
        raise typer.Exit(1)

    from runtime.codebase import scan_codebase

    ws = Project.workspace_path(project.id, WORKSPACE_ROOT, project.tenant_id)
    source = ws / "source"
    cache_dir = ws / ".cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_path = cache_dir / "codebase.json"
    summary = scan_codebase(source, cache_path=cache_path)
    cache_path.write_text(summary.model_dump_json(indent=2), encoding="utf-8")
    console.print(
        f"[green]Rescanned[/green] {summary.file_count} files; "
        f"app_class hint: [cyan]{summary.app_class_hint or 'unknown'}[/cyan]"
    )


@app.command()
def baseline(
    project_id: str,
    recapture: bool = typer.Option(False, "--recapture", help="Test suite'i yeniden koş"),
    override: int = typer.Option(
        -1, "--override", help="Manuel passing count override (parser yetmediğinde)"
    ),
) -> None:
    """Brownfield projenin test baseline'ını göster veya yeniden yakala."""
    try:
        project = Project.load(project_id, WORKSPACE_ROOT)
    except FileNotFoundError:
        console.print(f"[red]Project {project_id} not found[/red]")
        raise typer.Exit(1)
    if not project.is_brownfield:
        console.print(f"[yellow]{project_id} is not a brownfield project.[/yellow]")
        raise typer.Exit(1)

    from runtime.codebase import (
        TestBaseline,
        capture_baseline,
        load_baseline,
        write_baseline,
    )

    ws = Project.workspace_path(project.id, WORKSPACE_ROOT, project.tenant_id)
    source = ws / "source"
    cache_dir = ws / ".cache"

    if recapture:
        try:
            new_baseline = capture_baseline(source)
        except RuntimeError as e:
            console.print(f"[red]{e}[/red]")
            raise typer.Exit(1)
        write_baseline(cache_dir, new_baseline)
        console.print(
            f"[green]Captured[/green] cmd=[cyan]{new_baseline.cmd}[/cyan] "
            f"passing={new_baseline.passing} failed={new_baseline.failed} "
            f"skipped={new_baseline.skipped}"
        )
        return

    if override >= 0:
        existing = load_baseline(cache_dir)
        if existing is None:
            console.print(
                "[red]No existing baseline to override; run --recapture first.[/red]"
            )
            raise typer.Exit(1)
        patched = TestBaseline(
            cmd=existing.cmd,
            captured_at=existing.captured_at,
            passing=override,
            skipped=existing.skipped,
            failed=existing.failed,
            full_output_tail=existing.full_output_tail,
        )
        write_baseline(cache_dir, patched)
        console.print(f"[green]Override applied[/green] passing={override}")
        return

    existing = load_baseline(cache_dir)
    if existing is None:
        console.print(
            f"[yellow]No baseline at {cache_dir / 'baseline.json'}. "
            "Run with --recapture to create one.[/yellow]"
        )
        return
    table = Table(title=f"Baseline — {project_id}")
    table.add_column("Field", style="cyan")
    table.add_column("Value")
    table.add_row("Cmd", existing.cmd)
    table.add_row("Captured at", existing.captured_at)
    table.add_row("Passing", str(existing.passing))
    table.add_row("Skipped", str(existing.skipped))
    table.add_row("Failed", str(existing.failed))
    console.print(table)


@app.command("list-projects")
def list_projects() -> None:
    """Workspace altındaki projeleri listele."""
    if not WORKSPACE_ROOT.exists():
        console.print("[yellow]No workspaces yet.[/yellow]")
        return

    projects: list[Project] = []
    for path in WORKSPACE_ROOT.iterdir():
        if not path.is_dir():
            continue
        if not (path / "state.json").exists():
            continue
        try:
            projects.append(Project.load(path.name, WORKSPACE_ROOT))
        except Exception as e:
            console.print(f"[red]Failed to load {path.name}:[/red] {e}")

    if not projects:
        console.print("[yellow]No projects.[/yellow]")
        return

    table = Table(title="Projects")
    table.add_column("ID")
    table.add_column("Name")
    table.add_column("State")
    table.add_column("HITL")
    for project in projects:
        gate = project.awaiting_human() or ""
        table.add_row(project.id, project.name, project.state.value, gate)
    console.print(table)


@app.command()
def advance(
    project_id: str,
    target: str = typer.Argument(..., help="Hedef state (intake, prd_drafting, ...)"),
    note: str = typer.Option("", help="State değişikliği için not"),
) -> None:
    """Proje state'ini manuel ilerlet (v0.2'de ajanlar otomatikleştirecek)."""
    try:
        project = Project.load(project_id, WORKSPACE_ROOT)
    except FileNotFoundError:
        console.print(f"[red]Project {project_id} not found[/red]")
        raise typer.Exit(1)

    try:
        target_state = ProjectState(target)
    except ValueError:
        valid = ", ".join(s.value for s in ProjectState)
        console.print(f"[red]Unknown state '{target}'.[/red]")
        console.print(f"Valid: {valid}")
        raise typer.Exit(1)

    try:
        project.transition(target_state, actor="cli-manual", note=note)
    except InvalidTransition as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)

    project.save(WORKSPACE_ROOT)
    console.print(f"[green]{project.id}[/green] -> [cyan]{target_state.value}[/cyan]")
    if gate := project.awaiting_human():
        console.print(f"[yellow]HITL gate:[/yellow] {gate}")


@app.command()
def gates(project_id: str) -> None:
    """Open HITL gates for a project (G1–G7)."""
    from runtime.budget import BudgetTracker
    from runtime.orchestrator import (
        HITL_GATES,
        TaskDAG,
        detect_budget_breach,
        detect_schema_tasks,
    )

    try:
        project = Project.load(project_id, WORKSPACE_ROOT)
    except FileNotFoundError:
        console.print(f"[red]Project {project_id} not found[/red]")
        raise typer.Exit(1)

    table = Table(title=f"Gates for {project.id}")
    table.add_column("Gate", style="cyan")
    table.add_column("Status")
    table.add_column("Detail")

    # Project-level gate (current state)
    gate_label = HITL_GATES.get(project.state)
    if gate_label:
        table.add_row(gate_label, "[yellow]OPEN[/yellow]", "current project state")

    workspace = Project.workspace_path(project.id, WORKSPACE_ROOT)

    # G3 — schema (DAG-derived, advisory if not in SCHEMA_AWAITING_APPROVAL)
    dag_path = workspace / "task_dag.json"
    if dag_path.exists():
        dag = TaskDAG.model_validate_json(dag_path.read_text(encoding="utf-8"))
        schema = detect_schema_tasks(dag)
        if schema.triggered:
            table.add_row(
                "G3: Schema/migration",
                "[yellow]ADVISORY[/yellow]",
                f"tasks: {', '.join(schema.task_ids)}",
            )

    # G7 — budget cap (audit-derived)
    cap = os.getenv("AI_FACTORY_BUDGET_CAP_USD")
    if cap:
        try:
            cap_f = float(cap)
        except ValueError:
            cap_f = -1.0
        if cap_f > 0:
            ev = detect_budget_breach(BudgetTracker(), project.id, cap_f)
            status = "[red]BREACHED[/red]" if ev.triggered else "[green]OK[/green]"
            table.add_row(
                "G7: Budget cap",
                status,
                f"${ev.spent_usd:.4f} / ${ev.cap_usd:.4f} ({ev.overage_pct}%)",
            )

    if table.row_count == 0:
        console.print("[green]No open gates.[/green]")
    else:
        console.print(table)


@app.command()
def states() -> None:
    """Tüm state'leri ve transition'ları listele."""
    from runtime.orchestrator.state_machine import HITL_GATES, TRANSITIONS

    table = Table(title="State Transitions")
    table.add_column("From", style="cyan")
    table.add_column("Allowed Targets")
    table.add_column("HITL Gate", style="yellow")
    for state in ProjectState:
        allowed = TRANSITIONS.get(state, set())
        targets = ", ".join(sorted(s.value for s in allowed)) or "<terminal>"
        gate = HITL_GATES.get(state, "")
        table.add_row(state.value, targets, gate)
    console.print(table)


@app.command()
def run(
    project_id: str,
    step: str = typer.Option(
        "auto", help="babel | analyst | architect | orchestrator | auto"
    ),
) -> None:
    """Projeyi bir veya birden fazla state ileri taşı (ajan çağrısıyla)."""
    from runtime.agents import AnalystAgent, ArchitectAgent, OrchestratorAgent
    from runtime.audit import AuditLogger
    from runtime.babel import BabelLayer, StructuredIntent
    from runtime.llm import client_for
    from runtime.memory import MemoryLoader

    try:
        project = Project.load(project_id, WORKSPACE_ROOT)
    except FileNotFoundError:
        console.print(f"[red]Project {project_id} not found[/red]")
        raise typer.Exit(1)

    memory = MemoryLoader(REPO_ROOT)
    audit = AuditLogger()
    workspace = Project.workspace_path(project.id, WORKSPACE_ROOT)

    intent_path = workspace / "intent.json"
    babel_resumable = (
        project.state == ProjectState.BABEL_PROCESSING and not intent_path.exists()
    )
    if step in ("babel", "auto") and (
        project.state == ProjectState.INTAKE or babel_resumable
    ):
        try:
            llm = client_for("babel")
        except RuntimeError as e:
            console.print(f"[red]{e}[/red]")
            raise typer.Exit(1)
        babel = BabelLayer(llm, memory, audit)
        if project.state == ProjectState.INTAKE:
            project.transition(ProjectState.BABEL_PROCESSING, actor="babel-layer")
            project.save(WORKSPACE_ROOT)
        else:
            console.print("[yellow]Resuming Babel from BABEL_PROCESSING.[/yellow]")

        console.print("[cyan]Babel:[/cyan] extracting intent...")
        intent = babel.extract(project.initial_brief_tr, project.id)
        intent_path.write_text(intent.model_dump_json(indent=2), encoding="utf-8")
        console.print(f"[green]Intent saved:[/green] {intent_path}")

        console.print("[cyan]Babel:[/cyan] round-trip TR validation...")
        tr_summary = babel.round_trip(intent, project.id)
        console.print(f"\n[bold]Anladığım:[/bold]\n{tr_summary}\n")

        project.transition(
            ProjectState.PRD_DRAFTING, actor="babel-layer", note="intent extracted"
        )
        project.save(WORKSPACE_ROOT)

    if step in ("analyst", "auto") and project.state == ProjectState.PRD_DRAFTING:
        intent_path = workspace / "intent.json"
        if not intent_path.exists():
            console.print(f"[red]intent.json missing at {intent_path}[/red]")
            raise typer.Exit(1)

        intent = StructuredIntent.model_validate_json(
            intent_path.read_text(encoding="utf-8")
        )
        try:
            analyst_llm = client_for("analyst")
        except RuntimeError as e:
            console.print(f"[red]{e}[/red]")
            raise typer.Exit(1)
        analyst = AnalystAgent(analyst_llm, memory, audit)

        console.print("[cyan]Analyst:[/cyan] drafting PRD...")
        prd = analyst.draft_prd(intent, project.name, project.id)
        prd_path = workspace / "PRD.md"
        prd_path.write_text(prd, encoding="utf-8")
        console.print(f"[green]PRD drafted:[/green] {prd_path}")

        project.transition(
            ProjectState.PRD_AWAITING_APPROVAL,
            actor="analyst",
            note="PRD ready for review",
        )
        project.save(WORKSPACE_ROOT)
        console.print(
            f"\n[yellow]HITL Gate G1:[/yellow] PRD'yi gözden geçir, onaylamak için:"
        )
        console.print(
            f"  ortim advance {project.id} prd_approved --note 'reviewed'"
        )

    rfc_path_check = workspace / "RFC.md"
    architect_resumable = (
        project.state == ProjectState.RFC_DRAFTING and not rfc_path_check.exists()
    )
    if step in ("architect", "auto") and (
        project.state == ProjectState.PRD_APPROVED or architect_resumable
    ):
        prd_path = workspace / "PRD.md"
        if not prd_path.exists():
            console.print(f"[red]PRD.md missing at {prd_path}[/red]")
            raise typer.Exit(1)

        prd_text = prd_path.read_text(encoding="utf-8")
        try:
            architect_llm = client_for("architect")
        except RuntimeError as e:
            console.print(f"[red]{e}[/red]")
            raise typer.Exit(1)
        architect = ArchitectAgent(architect_llm, memory, audit)

        if project.state == ProjectState.PRD_APPROVED:
            project.transition(
                ProjectState.RFC_DRAFTING, actor="architect", note="extracting inputs"
            )
            project.save(WORKSPACE_ROOT)
        else:
            console.print("[yellow]Resuming Architect from RFC_DRAFTING.[/yellow]")

        codebase_summary = _load_codebase_summary(project, workspace)
        if codebase_summary is not None:
            console.print(
                f"[dim]Brownfield context: {codebase_summary.file_count} files, "
                f"app_class hint={codebase_summary.app_class_hint}[/dim]"
            )

        console.print("[cyan]Architect:[/cyan] extracting Golden Path inputs...")
        gp_inputs = architect.extract_inputs(
            prd_text, project.id, codebase=codebase_summary
        )
        (workspace / "golden_path_inputs.json").write_text(
            gp_inputs.model_dump_json(indent=2), encoding="utf-8"
        )

        console.print("[cyan]Architect:[/cyan] selecting tier (deterministic)...")
        tier_score = architect.select(gp_inputs, project.id)
        console.print(
            f"[bold]Selected:[/bold] [green]{tier_score.tier.value}[/green] "
            f"({tier_score.name}) — score {tier_score.score}"
        )

        console.print("[cyan]Architect:[/cyan] drafting RFC...")
        rfc = architect.draft_rfc(
            prd_text,
            tier_score,
            project.name,
            project.id,
            app_class=gp_inputs.app_class.value,
            codebase=codebase_summary,
        )
        rfc_path = workspace / "RFC.md"
        rfc_path.write_text(rfc, encoding="utf-8")
        console.print(f"[green]RFC drafted:[/green] {rfc_path}")

        project.transition(
            ProjectState.RFC_AWAITING_APPROVAL,
            actor="architect",
            note=f"tier={tier_score.tier.value}",
        )
        project.save(WORKSPACE_ROOT)
        console.print(
            f"\n[yellow]HITL Gate G2:[/yellow] RFC'yi gözden geçir, onaylamak için:"
        )
        console.print(
            f"  ortim advance {project.id} rfc_approved --note 'reviewed'"
        )

    dag_path_check = workspace / "task_dag.json"
    orchestrator_resumable = (
        project.state == ProjectState.TASKS_GENERATING and not dag_path_check.exists()
    )
    if step in ("orchestrator", "auto") and (
        project.state == ProjectState.RFC_APPROVED or orchestrator_resumable
    ):
        rfc_path = workspace / "RFC.md"
        if not rfc_path.exists():
            console.print(f"[red]RFC.md missing at {rfc_path}[/red]")
            raise typer.Exit(1)

        rfc_text = rfc_path.read_text(encoding="utf-8")

        if project.state == ProjectState.RFC_APPROVED:
            project.transition(
                ProjectState.TASKS_GENERATING, actor="orchestrator", note="generating DAG"
            )
            project.save(WORKSPACE_ROOT)
        else:
            console.print("[yellow]Resuming Orchestrator from TASKS_GENERATING.[/yellow]")

        try:
            orchestrator_llm = client_for("orchestrator")
        except RuntimeError as e:
            console.print(f"[red]{e}[/red]")
            raise typer.Exit(1)
        orchestrator_agent = OrchestratorAgent(orchestrator_llm, memory, audit)
        console.print("[cyan]Orchestrator:[/cyan] generating task DAG (with retry on validation failure)...")
        try:
            dag = orchestrator_agent.generate_dag(rfc_text, project.id)
        except RuntimeError as e:
            console.print(f"[red]{e}[/red]")
            project.transition(
                ProjectState.FAILED, actor="orchestrator", note=str(e)[:200]
            )
            project.save(WORKSPACE_ROOT)
            raise typer.Exit(1)

        # Persist DAG and per-task markdown files
        (workspace / "task_dag.json").write_text(
            dag.model_dump_json(indent=2), encoding="utf-8"
        )
        tasks_dir = workspace / "tasks"
        tasks_dir.mkdir(exist_ok=True)
        task_template = memory.load_template("Task")
        for task in dag.tasks:
            md = _render_task_md(task, task_template, project.id)
            (tasks_dir / f"{task.id}.md").write_text(md, encoding="utf-8")

        batches = dag.topological_batches()
        console.print(
            f"[green]DAG generated:[/green] {len(dag.tasks)} tasks in "
            f"{len(batches)} parallel batches, "
            f"~{dag.total_estimated_tokens():,} estimated tokens"
        )

        project.transition(
            ProjectState.TASKS_READY,
            actor="orchestrator",
            note=f"{len(dag.tasks)} tasks, {len(batches)} batches",
        )
        project.save(WORKSPACE_ROOT)

    console.print(f"\nFinal state: [cyan]{project.state.value}[/cyan]")


def _render_task_md(task, template: str, project_id: str) -> str:
    """Inline task markdown — template is a starting point but we render the
    real fields directly so reviewers see the actual values, not placeholders."""
    deps = ", ".join(task.dependencies) if task.dependencies else "(none)"
    criteria = "\n".join(f"- [ ] {c}" for c in task.acceptance_criteria) or "- [ ] (none)"
    return f"""# Task: {task.id}

> **Status:** PENDING
> **Project:** {project_id}
> **Branch:** task/{task.id}
> **Module Scope:** `{task.module_scope}`
> **RFC:** {task.rfc_section}

## Title
{task.title}

## Description
{task.description}

## Dependencies
{deps}

## Acceptance Criteria
{criteria}

## Estimated Token Budget
{task.estimated_tokens:,}

## Worker Constraints
- Branch isolation: must work on `task/{task.id}`
- Must not modify files outside module scope: `{task.module_scope}`
- Must run lint + type check + tests before marking review-ready
- Max 3 retry on review failure → escalate to HITL
"""


@app.command()
def tasks(project_id: str) -> None:
    """List task DAG for a project."""
    from runtime.orchestrator import TaskDAG

    try:
        project = Project.load(project_id, WORKSPACE_ROOT)
    except FileNotFoundError:
        console.print(f"[red]Project {project_id} not found[/red]")
        raise typer.Exit(1)

    workspace = Project.workspace_path(project.id, WORKSPACE_ROOT)
    dag_path = workspace / "task_dag.json"
    if not dag_path.exists():
        console.print(f"[yellow]No task DAG yet — run orchestrator first.[/yellow]")
        raise typer.Exit(0)

    dag = TaskDAG.model_validate_json(dag_path.read_text(encoding="utf-8"))

    table = Table(title=f"Tasks for {project.id}")
    table.add_column("ID", style="cyan")
    table.add_column("Title")
    table.add_column("Module")
    table.add_column("Deps")
    table.add_column("Tokens", justify="right")
    for task in dag.tasks:
        deps = ", ".join(task.dependencies) or "-"
        table.add_row(
            task.id, task.title, task.module_scope, deps, f"{task.estimated_tokens:,}"
        )
    console.print(table)

    batches = dag.topological_batches()
    console.print(
        f"\n[bold]Execution batches[/bold] (parallel within batch, "
        f"sequential across batches):"
    )
    for i, batch in enumerate(batches, start=1):
        console.print(f"  Batch {i}: {', '.join(batch)}")

    console.print(
        f"\nTotal estimated tokens: [bold]{dag.total_estimated_tokens():,}[/bold]"
    )


def _build_reviewer_chain(memory, audit):
    """Construct optional Security/Test/Perf reviewers based on env.

    `AI_FACTORY_HARD_REVIEWERS=on` enables all three; off (default) returns None.
    A missing API key for a specific reviewer's provider degrades that reviewer
    to None with a warning rather than crashing the whole run — operators can
    opt into a partial chain (e.g., security only) by leaving other API keys
    unset.
    """
    from runtime.executor import (
        PerfReviewerAgent,
        ReviewerChain,
        SecurityReviewerAgent,
        TestReviewerAgent,
    )
    from runtime.llm import client_for

    flag = os.getenv("AI_FACTORY_HARD_REVIEWERS", "off").strip().lower()
    if flag not in ("on", "true", "1", "yes"):
        return None

    def _try(role: str, factory):
        try:
            llm = client_for(role)
        except RuntimeError as e:
            console.print(f"[yellow]hard-reviewer {role} disabled:[/yellow] {e}")
            return None
        return factory(llm, memory, audit)

    chain = ReviewerChain(
        security=_try("security_reviewer", SecurityReviewerAgent),
        test=_try("test_reviewer", TestReviewerAgent),
        perf=_try("perf_reviewer", PerfReviewerAgent),
    )
    if chain.security is None and chain.test is None and chain.perf is None:
        console.print(
            "[yellow]AI_FACTORY_HARD_REVIEWERS=on but no reviewer could be built;"
            " falling back to CodeReviewer-only.[/yellow]"
        )
        return None
    return chain


def _load_for_execute(project_id: str):
    """Shared loading for `execute` and `run-all` commands.

    Returns (project, workspace, dag, status_file, worker_llm, reviewer_llm,
    reviewer_chain, memory, audit, rfc_text) or raises typer.Exit on any
    precondition failure. Worker and Reviewer get separate clients so they
    can sit on different providers/models per the Faz 6a routing contract.
    Hard-veto reviewers are wired only when `AI_FACTORY_HARD_REVIEWERS=on`.
    """
    from runtime.audit import AuditLogger
    from runtime.executor import TaskStatusFile
    from runtime.llm import client_for
    from runtime.memory import MemoryLoader
    from runtime.orchestrator import TaskDAG

    try:
        project = Project.load(project_id, WORKSPACE_ROOT)
    except FileNotFoundError:
        console.print(f"[red]Project {project_id} not found[/red]")
        raise typer.Exit(1)

    if project.state not in (ProjectState.TASKS_READY, ProjectState.EXECUTING):
        console.print(
            f"[red]State {project.state.value} does not allow execution. "
            f"Need tasks_ready or executing.[/red]"
        )
        raise typer.Exit(1)

    workspace = Project.workspace_path(project.id, WORKSPACE_ROOT)
    dag_path = workspace / "task_dag.json"
    if not dag_path.exists():
        console.print(f"[red]task_dag.json missing — run orchestrator first[/red]")
        raise typer.Exit(1)
    dag = TaskDAG.model_validate_json(dag_path.read_text(encoding="utf-8"))

    rfc_path = workspace / "RFC.md"
    if not rfc_path.exists():
        console.print(f"[red]RFC.md missing at {rfc_path}[/red]")
        raise typer.Exit(1)
    rfc_text = rfc_path.read_text(encoding="utf-8")

    try:
        worker_llm = client_for("worker")
        reviewer_llm = client_for("reviewer")
    except RuntimeError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)

    memory = MemoryLoader(REPO_ROOT)
    audit = AuditLogger()
    reviewer_chain = _build_reviewer_chain(memory, audit)

    status_file = TaskStatusFile.load_or_init(workspace, project.id)

    # M1: brownfield projects feed real codebase context into the executor so
    # Worker sees `related_files` and the sandbox enforces the right ext set.
    codebase_summary = _load_codebase_summary(project, workspace)
    app_class = project.app_class or "web"

    return (
        project,
        workspace,
        dag,
        status_file,
        worker_llm,
        reviewer_llm,
        reviewer_chain,
        memory,
        audit,
        rfc_text,
        codebase_summary,
        app_class,
    )


def _render_execution_result(result, task) -> None:
    """Pretty-print an ExecutionResult (shared by execute / run-all)."""
    from runtime.executor import TaskStatus

    if result.status == TaskStatus.DONE:
        files = result.worker_output.files if result.worker_output else []
        console.print(
            f"[green]APPROVED[/green] {result.task_id} — {len(files)} file(s) under "
            f"`{task.module_scope}`"
            + (f" (commit {result.commit_sha[:8]})" if result.commit_sha else "")
        )
        for f in files:
            console.print(f"  + {f.path}")
        if result.test_result and result.test_result.passed:
            console.print("  [dim]tests: PASSED[/dim]")
        elif result.test_result and result.test_result.skipped:
            console.print(f"  [dim]tests: skipped — {result.test_result.skipped_reason}[/dim]")
    else:
        label = (
            "BLOCKED" if result.blocked_by else "REJECTED"
        )
        color = "red" if result.blocked_by else "yellow"
        suffix = (
            f" (hard veto by {result.blocked_by})"
            if result.blocked_by
            else ""
        )
        console.print(
            f"[{color}]{label}[/{color}] {result.task_id} — status: "
            f"{result.status.value}{suffix}"
        )
        # Surface every reviewer's findings, tagged.
        for v in result.verdicts or ([result.verdict] if result.verdict else []):
            if v is None:
                continue
            tag = getattr(v, "reviewer", "code")
            if not v.approved or v.reasons:
                for r in v.reasons:
                    console.print(f"  - [{tag}] {r}")
        if result.test_result and not result.test_result.passed and not result.test_result.skipped:
            console.print(
                f"  [red]tests FAILED[/red] (exit {result.test_result.exit_code})"
            )
            if result.test_result.stderr_tail:
                console.print(f"  [dim]{result.test_result.stderr_tail[:300]}[/dim]")
        if result.error:
            console.print(f"  [dim]error: {result.error}[/dim]")


def _bootstrap_if_ready(project, workspace, dag, app_class: str, audit) -> None:
    """Idempotently scaffold module folders + tier root files before the
    first task runs. Uses the persisted Architect inputs to recompute the
    tier deterministically, so we don't need a new persisted field on
    Project. Re-running is a no-op (every existing file is left alone).

    Skipped silently if `golden_path_inputs.json` is missing (older projects
    or partially-bootstrapped workspaces) — the legacy Worker-writes-scaffold
    path still works for those.
    """
    inputs_path = workspace / "golden_path_inputs.json"
    if not inputs_path.exists():
        return
    from runtime.architecture import (
        GoldenPathInputs,
        bootstrap_workspace_layout,
        select_tier,
    )

    inputs = GoldenPathInputs.model_validate_json(
        inputs_path.read_text(encoding="utf-8")
    )
    tier_score = select_tier(inputs)
    modules = sorted({t.module_scope for t in dag.tasks})
    created = bootstrap_workspace_layout(
        workspace,
        modules=modules,
        tier=tier_score.tier.value,
        app_class=app_class,
        project_name=project.name,
    )
    if created:
        audit.log(
            "workspace_bootstrapped",
            project_id=project.id,
            tier=tier_score.tier.value,
            app_class=app_class,
            modules=modules,
            paths=[str(p.relative_to(workspace)) for p in created],
        )


def _maybe_finalize_done(project, status_file, dag, workspace) -> bool:
    """If every task is DONE, transition project to DONE. Returns True if transitioned."""
    from runtime.executor import TaskStatus

    if not all(
        (rec := status_file.records.get(t.id)) and rec.status == TaskStatus.DONE
        for t in dag.tasks
    ):
        return False
    if project.state != ProjectState.EXECUTING:
        return False
    project.transition(ProjectState.DONE, actor="executor", note="all tasks done")
    project.save(WORKSPACE_ROOT)
    return True


@app.command()
def execute(
    project_id: str,
    task_id: str = typer.Argument(..., help="Task ID (T-...)"),
    max_attempts: int = typer.Option(3, help="Reject sonrasi max retry"),
) -> None:
    """Tek bir task'i Worker -> tests -> Reviewer pipeline'indan gecir.

    v0.5b: gercek kod + git branch (auto-on if `git` available) +
    AI_FACTORY_TEST_CMD set ise test runner.
    """
    from runtime.executor import TaskStatus, execute_task

    (
        project,
        workspace,
        dag,
        status_file,
        worker_llm,
        reviewer_llm,
        reviewer_chain,
        memory,
        audit,
        rfc_text,
        codebase_summary,
        app_class,
    ) = _load_for_execute(project_id)

    task = next((t for t in dag.tasks if t.id == task_id), None)
    if task is None:
        valid = ", ".join(t.id for t in dag.tasks)
        console.print(f"[red]Task {task_id} not in DAG. Valid: {valid}[/red]")
        raise typer.Exit(1)

    record = status_file.get_or_create(task_id)
    if record.status == TaskStatus.DONE:
        console.print(f"[yellow]Task {task_id} already DONE — nothing to do[/yellow]")
        return
    if record.status == TaskStatus.AWAITING_HITL:
        console.print(
            f"[red]Task {task_id} is AWAITING_HITL. "
            f"Reset task_status.json or raise --max-attempts to retry.[/red]"
        )
        raise typer.Exit(1)

    for dep in task.dependencies:
        dep_record = status_file.records.get(dep)
        if not dep_record or dep_record.status != TaskStatus.DONE:
            dep_status = dep_record.status.value if dep_record else "PENDING"
            console.print(
                f"[red]Dependency {dep} is {dep_status}, must be DONE first[/red]"
            )
            raise typer.Exit(1)

    if project.state == ProjectState.TASKS_READY:
        _bootstrap_if_ready(project, workspace, dag, app_class, audit)
        project.transition(
            ProjectState.EXECUTING, actor="executor", note=f"start {task_id}"
        )
        project.save(WORKSPACE_ROOT)

    # Self-correcting loop. `execute_task` already feeds prior_reasons into
    # the Worker prompt on attempts > 1 and bumps the task to AWAITING_HITL
    # when the retry budget is exhausted. We just keep calling it while the
    # task stays in soft-reject (PENDING) and budget remains.
    result = None
    while True:
        console.print(
            f"[cyan]Executing[/cyan] [bold]{task_id}[/bold] (attempt "
            f"{record.attempts + 1}/{max_attempts})..."
        )
        result = execute_task(
            task=task,
            rfc_text=rfc_text,
            project_id=project.id,
            workspace=workspace,
            status_file=status_file,
            llm=worker_llm,
            reviewer_llm=reviewer_llm,
            reviewer_chain=reviewer_chain,
            memory=memory,
            audit=audit,
            max_attempts=max_attempts,
            codebase_summary=codebase_summary,
            app_class=app_class,
        )
        status_file.save(workspace)
        _render_execution_result(result, task)

        if result.status != TaskStatus.PENDING:
            break
        # Soft reject + budget remains → loop with reviewer feedback.
        console.print(
            f"[yellow]Retrying with reviewer feedback "
            f"(attempt {record.attempts + 1}/{max_attempts})...[/yellow]"
        )

    if _maybe_finalize_done(project, status_file, dag, workspace):
        console.print("\n[bold green]All tasks DONE — project complete.[/bold green]")
    elif result.status != TaskStatus.DONE:
        raise typer.Exit(1)


@app.command("run-all")
def run_all(
    project_id: str,
    max_attempts: int = typer.Option(3, help="Her task icin max retry"),
    stop_on_fail: bool = typer.Option(
        True, "--stop-on-fail/--continue-on-fail",
        help="Bir task FAILED/AWAITING_HITL olunca dur",
    ),
    parallel: bool = typer.Option(
        False, "--parallel/--sequential",
        help="Batch icindeki task'lari paralel kostur (worktree ile, git gerektirir)",
    ),
    max_workers: int = typer.Option(
        4, help="Paralel mode icin maksimum worker thread sayisi",
    ),
) -> None:
    """DAG'i topolojik batch'lerde calistir.

    - sequential (default): tek tek, ana repo'da `task/<id>` checkout
    - parallel: batch icindeki task'lar ThreadPoolExecutor + git worktree
      ile paralel; merge'ler seri, status save lock altinda. Gerektirir:
      git PATH'te ve `AI_FACTORY_GIT_ENABLED` 'false' degil.
    """
    from runtime.concurrency import LockTimeout, file_lock
    from runtime.executor import GitNotAvailable, git_enabled

    (
        project,
        workspace,
        dag,
        status_file,
        worker_llm,
        reviewer_llm,
        reviewer_chain,
        memory,
        audit,
        rfc_text,
        codebase_summary,
        app_class,
    ) = _load_for_execute(project_id)

    if parallel:
        try:
            if not git_enabled(workspace):
                console.print(
                    "[red]--parallel requires git enabled "
                    "(set AI_FACTORY_GIT_ENABLED=auto or true)[/red]"
                )
                raise typer.Exit(1)
        except GitNotAvailable as e:
            console.print(f"[red]{e}[/red]")
            raise typer.Exit(1)

    batches = dag.topological_batches()
    tasks_by_id = {t.id: t for t in dag.tasks}

    if project.state == ProjectState.TASKS_READY:
        _bootstrap_if_ready(project, workspace, dag, app_class, audit)
        project.transition(
            ProjectState.EXECUTING, actor="executor", note="run-all start"
        )
        project.save(WORKSPACE_ROOT)

    mode_label = "parallel" if parallel else "sequential"
    console.print(
        f"[bold]run-all[/bold] ({mode_label}) {len(dag.tasks)} task(s) in "
        f"{len(batches)} batch(es)"
    )

    # Cross-process guard against concurrent run-all on the same workspace.
    try:
        lock_ctx = file_lock(workspace / ".exec", timeout=5.0)
    except Exception as e:
        console.print(f"[red]Failed to acquire workspace exec lock: {e}[/red]")
        raise typer.Exit(1)

    try:
        with lock_ctx:
            blocked = _run_all_loop(
                batches=batches,
                tasks_by_id=tasks_by_id,
                project=project,
                workspace=workspace,
                dag=dag,
                status_file=status_file,
                worker_llm=worker_llm,
                reviewer_llm=reviewer_llm,
                reviewer_chain=reviewer_chain,
                memory=memory,
                audit=audit,
                rfc_text=rfc_text,
                max_attempts=max_attempts,
                stop_on_fail=stop_on_fail,
                parallel=parallel,
                max_workers=max_workers,
                codebase_summary=codebase_summary,
                app_class=app_class,
            )
    except LockTimeout:
        console.print(
            "[red]Another run-all is in progress on this workspace[/red]"
        )
        raise typer.Exit(1)

    if _maybe_finalize_done(project, status_file, dag, workspace):
        console.print("\n[bold green]All tasks DONE — project complete.[/bold green]")
        
        readme_path = workspace / "README.md"
        if not readme_path.exists():
            console.print("\n[cyan]Documenter:[/cyan] drafting README.md...")
            try:
                from runtime.agents.documenter import DocumenterAgent
                from runtime.llm import client_for
                
                doc_llm = client_for("analyst")
                documenter = DocumenterAgent(doc_llm, memory, audit)
                
                prd_text = (workspace / "PRD.md").read_text(encoding="utf-8") if (workspace / "PRD.md").exists() else ""
                
                readme_text = documenter.generate_readme(
                    project_name=project.name,
                    prd_text=prd_text,
                    rfc_text=rfc_text,
                    project_id=project.id,
                )
                
                readme_path.write_text(readme_text, encoding="utf-8")
                console.print(f"[green]README saved:[/green] {readme_path}")
            except Exception as e:
                console.print(f"[yellow]Could not generate README.md automatically: {e}[/yellow]")

    elif blocked:
        console.print(
            "\n[yellow]Stopped: at least one task is not DONE. "
            "Inspect task_status.json and re-run.[/yellow]"
        )
        raise typer.Exit(1)


def _run_all_loop(
    *,
    batches,
    tasks_by_id,
    project,
    workspace,
    dag,
    status_file,
    worker_llm,
    reviewer_llm,
    reviewer_chain,
    memory,
    audit,
    rfc_text,
    max_attempts: int,
    stop_on_fail: bool,
    parallel: bool,
    max_workers: int,
    codebase_summary=None,
    app_class: str = "web",
) -> bool:
    """Run every batch. Returns True if blocked (a task failed and we stopped)."""
    import threading
    import time
    from concurrent.futures import ThreadPoolExecutor, as_completed

    from runtime.executor import (
        GitOperationFailed,
        TaskStatus,
        execute_task,
        merge_task_to_main,
    )

    blocked = False
    merge_lock = threading.Lock()
    status_lock = threading.Lock()

    for i, batch in enumerate(batches, start=1):
        console.print(f"\n[bold cyan]Batch {i}[/bold cyan]: {', '.join(batch)}")

        pending = [
            tasks_by_id[tid]
            for tid in batch
            if (
                (rec := status_file.records.get(tid)) is None
                or rec.status not in (TaskStatus.DONE, TaskStatus.AWAITING_HITL)
            )
        ]
        for tid in batch:
            rec = status_file.records.get(tid)
            if rec and rec.status == TaskStatus.DONE:
                console.print(f"  [dim]skip {tid} — already DONE[/dim]")
            elif rec and rec.status == TaskStatus.AWAITING_HITL:
                console.print(f"  [red]{tid} AWAITING_HITL — skipping[/red]")
                blocked = True

        if blocked and stop_on_fail:
            break
        if not pending:
            continue

        batch_start = time.monotonic()
        per_task_durations: dict[str, float] = {}
        merge_wait_total = 0.0
        approved_count = 0

        if parallel and len(pending) > 1:
            with ThreadPoolExecutor(max_workers=max_workers) as pool:
                submit_at: dict[str, float] = {}
                futures = {}
                for task in pending:
                    submit_at[task.id] = time.monotonic()
                    fut = pool.submit(
                        execute_task,
                        task=task,
                        rfc_text=rfc_text,
                        project_id=project.id,
                        workspace=workspace,
                        status_file=status_file,
                        llm=worker_llm,
                        reviewer_llm=reviewer_llm,
                        reviewer_chain=reviewer_chain,
                        memory=memory,
                        audit=audit,
                        max_attempts=max_attempts,
                        use_worktree=True,
                        codebase_summary=codebase_summary,
                        app_class=app_class,
                    )
                    futures[fut] = task
                console.print(
                    f"  [dim]paralel: {len(pending)} task, "
                    f"max-workers={max_workers}[/dim]"
                )
                for fut in as_completed(futures):
                    task = futures[fut]
                    per_task_durations[task.id] = (
                        time.monotonic() - submit_at[task.id]
                    )
                    try:
                        result = fut.result()
                    except Exception as e:
                        console.print(
                            f"  [red]EXCEPTION[/red] {task.id}: {e!r}"
                        )
                        blocked = True
                        continue

                    if result.needs_merge:
                        wait_start = time.monotonic()
                        with merge_lock:
                            merge_wait_total += time.monotonic() - wait_start
                            try:
                                merge_task_to_main(workspace, task.id)
                            except GitOperationFailed as e:
                                console.print(
                                    f"  [red]merge conflict {task.id}[/red]: {e}"
                                )
                                rec = status_file.records[task.id]
                                rec.status = TaskStatus.AWAITING_HITL
                                rec.last_error = f"merge: {e}"[:300]
                    with status_lock:
                        status_file.save(workspace)

                    _render_execution_result(result, task)
                    if result.status == TaskStatus.DONE:
                        approved_count += 1
                    else:
                        blocked = True
        else:
            for task in pending:
                t0 = time.monotonic()
                while True:
                    rec = status_file.get_or_create(task.id)
                    console.print(
                        f"  [cyan]exec[/cyan] {task.id} "
                        f"(attempt {rec.attempts + 1}/{max_attempts})"
                    )
                    result = execute_task(
                        task=task,
                        rfc_text=rfc_text,
                        project_id=project.id,
                        workspace=workspace,
                        status_file=status_file,
                        llm=worker_llm,
                        reviewer_llm=reviewer_llm,
                        reviewer_chain=reviewer_chain,
                        memory=memory,
                        audit=audit,
                        max_attempts=max_attempts,
                        use_worktree=False,
                        codebase_summary=codebase_summary,
                        app_class=app_class,
                    )
                    status_file.save(workspace)
                    _render_execution_result(result, task)
                    if result.status != TaskStatus.PENDING:
                        break
                    console.print(
                        f"  [yellow]retry {task.id} after reviewer feedback[/yellow]"
                    )
                per_task_durations[task.id] = time.monotonic() - t0
                if result.status == TaskStatus.DONE:
                    approved_count += 1
                else:
                    blocked = True
                    if stop_on_fail:
                        break

        wall_seconds = time.monotonic() - batch_start
        sum_seconds = sum(per_task_durations.values())
        speedup = (sum_seconds / wall_seconds) if wall_seconds > 0 else 1.0
        audit.log(
            "executor_batch_metrics",
            project_id=project.id,
            batch_index=i,
            mode="parallel" if parallel and len(pending) > 1 else "sequential",
            task_count=len(pending),
            approved=approved_count,
            wall_seconds=round(wall_seconds, 3),
            sum_task_seconds=round(sum_seconds, 3),
            speedup=round(speedup, 2),
            merge_wait_seconds=round(merge_wait_total, 3),
            max_workers=max_workers if parallel else 1,
        )
        if parallel and len(pending) > 1:
            console.print(
                f"  [dim]batch süresi {wall_seconds:.1f}s, "
                f"toplam çalışma {sum_seconds:.1f}s, hızlanma x{speedup:.2f}[/dim]"
            )

        if blocked and stop_on_fail:
            break

    return blocked


@app.command()
def budget(
    project_id: str = typer.Argument(None, help="Belirli proje (opsiyonel — boşsa toplam)"),
    by_provider: bool = typer.Option(
        False, "--by-provider/--total-only",
        help="Provider başına token + USD dağılımını göster",
    ),
) -> None:
    """Token kullanım ve maliyet raporu."""
    from runtime.budget import BudgetTracker

    tracker = BudgetTracker()
    report = tracker.report(project_id)

    table = Table(title=f"Budget Report ({'all' if not project_id else project_id})")
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


@app.command("score-tier")
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
    from runtime.architecture import (
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


if __name__ == "__main__":
    app()
