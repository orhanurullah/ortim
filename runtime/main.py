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


# Semantic verb aliases for HITL approvals. Each alias resolves to a real
# ProjectState and emits a distinct audit event so the gate log captures
# the *intent* of the operator, not just the resulting state.
_APPROVAL_ALIASES: dict[str, tuple[ProjectState, str]] = {
    "prd_approved": (ProjectState.PRD_APPROVED, "gate_prd_approved"),
    "rfc_approved": (ProjectState.RFC_APPROVED, "gate_rfc_approved"),
    "schema_approved": (ProjectState.EXECUTING, "gate_schema_approved"),
    "budget_approved": (ProjectState.EXECUTING, "gate_budget_approved"),
    "deploy_approved": (ProjectState.DONE, "gate_deploy_approved"),
    "extend_prd_approved": (
        ProjectState.EXTEND_PRD_APPROVED,
        "gate_extend_prd_approved",
    ),
    "extend_rfc_approved": (
        ProjectState.EXTEND_RFC_APPROVED,
        "gate_extend_rfc_approved",
    ),
}


@app.command()
def advance(
    project_id: str,
    target: str = typer.Argument(..., help="Hedef state veya alias (intake, prd_drafting, schema_approved, ...)"),
    note: str = typer.Option("", help="State değişikliği için not"),
) -> None:
    """Proje state'ini manuel ilerlet (HITL onayları + acil durum)."""
    from runtime.audit import AuditLogger

    try:
        project = Project.load(project_id, WORKSPACE_ROOT)
    except FileNotFoundError:
        console.print(f"[red]Project {project_id} not found[/red]")
        raise typer.Exit(1)

    alias = _APPROVAL_ALIASES.get(target)
    if alias is not None:
        target_state, audit_event = alias
    else:
        try:
            target_state = ProjectState(target)
        except ValueError:
            valid_states = ", ".join(s.value for s in ProjectState)
            valid_aliases = ", ".join(_APPROVAL_ALIASES)
            console.print(f"[red]Unknown state or alias '{target}'.[/red]")
            console.print(f"States: {valid_states}")
            console.print(f"Aliases: {valid_aliases}")
            raise typer.Exit(1)
        audit_event = None

    try:
        project.transition(target_state, actor="cli-manual", note=note)
    except InvalidTransition as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)

    project.save(WORKSPACE_ROOT)
    if audit_event:
        # Surface the alias intent so `ortim retro` and downstream audit
        # tooling can distinguish "schema approval" from a bare state
        # bump that happened to land on EXECUTING.
        AuditLogger().log(
            audit_event,
            project_id=project.id,
            note=note,
            target_state=target_state.value,
        )
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

        # M2: route through INTAKE_DIALOG when AI_FACTORY_DIALOG_MODE=on
        # (default). Legacy direct-to-PRD_DRAFTING path is preserved for
        # AI_FACTORY_DIALOG_MODE=off + older fixtures.
        from runtime.dialog import (
            append_dialog_turn,
            dialog_mode_on,
            save_intent_md,
        )

        if dialog_mode_on():
            from runtime.agents import IntentAnalyst

            project.transition(
                ProjectState.INTAKE_DIALOG,
                actor="babel-layer",
                note="intent extracted; entering INTAKE_DIALOG",
            )
            project.save(WORKSPACE_ROOT)

            console.print("[cyan]IntentAnalyst:[/cyan] drafting intent summary...")
            intent_analyst = IntentAnalyst(
                client_for("analyst"), memory, audit
            )
            intent_md = intent_analyst.draft(intent, project.name, project.id)
            save_intent_md(workspace, intent_md)
            append_dialog_turn(
                workspace,
                ProjectState.INTAKE_DIALOG,
                user_feedback=None,
                response_text=intent_md,
            )
            console.print(
                f"[green]intent.md drafted:[/green] {workspace / 'intent.md'}"
            )
            console.print(
                "\nReview, then refine or lock:\n"
                f"  [cyan]ortim show {project.id} --artifact intent[/cyan]\n"
                f"  [cyan]ortim refine {project.id} \"<feedback>\"[/cyan]\n"
                f"  [cyan]ortim lock {project.id}[/cyan]"
            )
            return
        else:
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

        # M2 dialog path: golden_path_inputs.json and stack.json were
        # produced during STACK_DIALOG lock. Skip re-extraction; load them.
        from runtime.architecture import GoldenPathInputs
        from runtime.dialog import load_locked_stack

        locked_stack = load_locked_stack(workspace)
        gp_path = workspace / "golden_path_inputs.json"
        if locked_stack is not None and gp_path.exists():
            console.print(
                "[dim]Reusing locked stack + cached golden_path_inputs.json "
                "from dialog flow.[/dim]"
            )
            gp_inputs = GoldenPathInputs.model_validate_json(
                gp_path.read_text(encoding="utf-8")
            )
            tier_score = architect.select(gp_inputs, project.id)
        else:
            console.print(
                "[cyan]Architect:[/cyan] extracting Golden Path inputs..."
            )
            gp_inputs = architect.extract_inputs(
                prd_text, project.id, codebase=codebase_summary
            )
            gp_path.write_text(
                gp_inputs.model_dump_json(indent=2), encoding="utf-8"
            )
            console.print(
                "[cyan]Architect:[/cyan] selecting tier (deterministic)..."
            )
            tier_score = architect.select(gp_inputs, project.id)

        console.print(
            f"[bold]Tier:[/bold] [green]{tier_score.tier.value}[/green] "
            f"({tier_score.name}) — score {tier_score.score}"
        )
        if locked_stack is not None:
            console.print(
                f"[bold]Locked stack:[/bold] [green]{locked_stack.language}[/green] "
                f"/ {locked_stack.primary_framework}"
            )

        console.print("[cyan]Architect:[/cyan] drafting RFC...")
        rfc = architect.draft_rfc(
            prd_text,
            tier_score,
            project.name,
            project.id,
            app_class=gp_inputs.app_class.value,
            codebase=codebase_summary,
            locked_stack=locked_stack,
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

    # ---- M3.1 extend cycle: EXTEND_PRD_APPROVED → EXTEND_RFC_AWAITING_APPROVAL ----
    if step in ("architect", "auto") and (
        project.state == ProjectState.EXTEND_PRD_APPROVED
    ):
        cycle, blocked = _draft_extend_rfc(
            project=project,
            workspace=workspace,
            audit=audit,
            memory=memory,
            extender_llm=client_for("analyst"),
        )
        if blocked is not None:
            console.print(
                f"[yellow]BLOCKED-STACK[/yellow]: cycle {cycle} RFC draft "
                f"requires library [bold]{blocked}[/bold] not in the locked "
                "stack. State stays at "
                f"[cyan]{project.state.value}[/cyan]; rework the PRD or "
                "wait for stack-amendment support (M3.2)."
            )
        else:
            console.print(
                f"[green]Extension cycle {cycle} delta RFC written.[/green]\n"
                f"State: [cyan]{project.state.value}[/cyan]\n"
                f"\n[yellow]HITL Gate G2 (cycle {cycle}):[/yellow] "
                f"RFC.md'nin yeni `## Extension {cycle}` bölümünü gözden "
                "geçir, onaylamak için:\n"
                f"  [cyan]ortim advance {project.id} extend_rfc_approved "
                "--note 'reviewed'[/cyan]"
            )

    # ---- M3.1 extend cycle: EXTEND_RFC_APPROVED → TASKS_GENERATING → TASKS_READY ----
    if step in ("orchestrator", "auto") and (
        project.state == ProjectState.EXTEND_RFC_APPROVED
    ):
        cycle, new_count = _generate_extend_dag(
            project=project,
            workspace=workspace,
            audit=audit,
            memory=memory,
            orchestrator_llm=client_for("orchestrator"),
        )
        console.print(
            f"[green]Extension cycle {cycle}: {new_count} new task(s) "
            f"appended to task_dag.json.[/green] State: "
            f"[cyan]{project.state.value}[/cyan]\n"
            f"\nRun [cyan]ortim run-all {project.id}[/cyan] to execute the "
            "new tasks (existing DONE tasks are skipped)."
        )

    console.print(f"\nFinal state: [cyan]{project.state.value}[/cyan]")


# ---- M2 dialog commands -------------------------------------------------

_DIALOG_STATE_ALIASES = {
    "intake": ProjectState.INTAKE_DIALOG,
    "stack": ProjectState.STACK_DIALOG,
    "prd": ProjectState.PRD_DIALOG,
}


def _dialog_setup(project_id: str):
    """Shared bootstrap for the dialog CLI commands: load project,
    workspace, audit, and memory. Returns a tuple of those plus an
    early-exit flag if the state is not a dialog state."""
    from runtime.audit import AuditLogger
    from runtime.memory import MemoryLoader

    try:
        project = Project.load(project_id, WORKSPACE_ROOT)
    except FileNotFoundError:
        console.print(f"[red]Project {project_id} not found[/red]")
        raise typer.Exit(1)
    workspace = Project.workspace_path(project.id, WORKSPACE_ROOT, project.tenant_id)
    return project, workspace, AuditLogger(), MemoryLoader(REPO_ROOT)


def _require_dialog_state(project) -> None:
    dialog_states = {
        ProjectState.INTAKE_DIALOG,
        ProjectState.STACK_DIALOG,
        ProjectState.PRD_DIALOG,
    }
    if project.state not in dialog_states:
        console.print(
            f"[red]Project {project.id} is in state '{project.state.value}', "
            f"not a dialog state.[/red]\n"
            "Dialog commands (refine/lock/show) only work in "
            "INTAKE_DIALOG, STACK_DIALOG, or PRD_DIALOG."
        )
        raise typer.Exit(1)


@app.command()
def refine(
    project_id: str,
    feedback: str = typer.Argument(
        ..., help="Geri bildirim. Örn: 'add tagging to must-have features'"
    ),
    force: bool = typer.Option(
        False, "--force", help="Turn cap aşıldıysa bilinçli devam et."
    ),
) -> None:
    """Aktif dialog state'inin agent'ını feedback ile yeniden çağır."""
    from runtime.babel import StructuredIntent
    from runtime.dialog import (
        append_dialog_turn,
        count_dialog_turns,
        load_intent_md,
        load_locked_stack,
        load_prd_md,
        save_intent_md,
        save_locked_stack,
        save_prd_md,
        snapshot_current_artifact,
        turn_cap,
    )
    from runtime.llm import client_for

    project, workspace, audit, memory = _dialog_setup(project_id)
    _require_dialog_state(project)

    used = count_dialog_turns(workspace, project.state)
    cap = turn_cap()
    if used >= cap and not force:
        console.print(
            f"[yellow][budget][/yellow] turn cap reached for "
            f"{project.state.value}: {used}/{cap}. "
            "Re-run with --force to continue, or `ortim lock` to advance."
        )
        raise typer.Exit(2)

    # Snapshot BEFORE writing the new artifact so `lock` can diff later.
    snapshot_current_artifact(workspace, project.state)

    if project.state == ProjectState.INTAKE_DIALOG:
        from runtime.agents import IntentAnalyst

        intent_path = workspace / "intent.json"
        if not intent_path.exists():
            console.print(f"[red]intent.json missing at {intent_path}[/red]")
            raise typer.Exit(1)
        structured = StructuredIntent.model_validate_json(
            intent_path.read_text(encoding="utf-8")
        )
        prev = load_intent_md(workspace) or ""
        agent = IntentAnalyst(client_for("analyst"), memory, audit)
        new_md = agent.refine(
            previous_md=prev,
            intent=structured,
            user_feedback=feedback,
            project_name=project.name,
            project_id=project.id,
        )
        save_intent_md(workspace, new_md)
        append_dialog_turn(workspace, project.state, feedback, new_md)
        console.print(
            f"[green]intent.md refined (turn {used + 1}/{cap}).[/green]"
        )
    elif project.state == ProjectState.STACK_DIALOG:
        from runtime.agents import StackAnalyst
        from runtime.architecture import GoldenPathInputs, select_tier

        prev_stack = load_locked_stack(workspace)
        intent_md = load_intent_md(workspace)
        gp_path = workspace / "golden_path_inputs.json"
        if intent_md is None:
            console.print("[red]intent.md missing — lock INTAKE_DIALOG first.[/red]")
            raise typer.Exit(1)
        if not gp_path.exists():
            console.print(
                "[red]golden_path_inputs.json missing — `ortim lock` "
                "should have produced it.[/red]"
            )
            raise typer.Exit(1)
        gp_inputs = GoldenPathInputs.model_validate_json(
            gp_path.read_text(encoding="utf-8")
        )
        tier_score = select_tier(gp_inputs)
        agent = StackAnalyst(client_for("analyst"), memory, audit)
        if prev_stack is None:
            new_stack = agent.propose(
                intent_md=intent_md,
                tier_suggestion=tier_score,
                app_class=gp_inputs.app_class.value,
                project_id=project.id,
            )
        else:
            new_stack = agent.refine(
                previous_stack=prev_stack,
                intent_md=intent_md,
                user_feedback=feedback,
                tier_suggestion=tier_score,
                project_id=project.id,
            )
        save_locked_stack(workspace, new_stack)
        append_dialog_turn(workspace, project.state, feedback, new_stack.to_markdown())
        console.print(
            f"[green]stack.json refined (turn {used + 1}/{cap}) — "
            f"language={new_stack.language}.[/green]"
        )
    else:  # PRD_DIALOG
        from runtime.agents import PRDAnalyst

        intent_md = load_intent_md(workspace)
        stack = load_locked_stack(workspace)
        prev_prd = load_prd_md(workspace) or ""
        if intent_md is None or stack is None:
            console.print(
                "[red]intent.md or stack.json missing — earlier dialog "
                "states must be locked first.[/red]"
            )
            raise typer.Exit(1)
        agent = PRDAnalyst(client_for("analyst"), memory, audit)
        new_prd = agent.refine(
            previous_prd=prev_prd,
            intent_md=intent_md,
            stack=stack,
            user_feedback=feedback,
            project_name=project.name,
            project_id=project.id,
        )
        save_prd_md(workspace, new_prd)
        append_dialog_turn(workspace, project.state, feedback, new_prd)
        console.print(
            f"[green]PRD.md refined (turn {used + 1}/{cap}).[/green]"
        )


@app.command()
def show(
    project_id: str,
    artifact: str = typer.Option(
        "current",
        "--artifact",
        "-a",
        help="intent | stack | prd | current",
    ),
) -> None:
    """Aktif (ya da seçili) dialog artifact'ini konsola bas."""
    from runtime.dialog import load_intent_md, load_locked_stack, load_prd_md

    try:
        project = Project.load(project_id, WORKSPACE_ROOT)
    except FileNotFoundError:
        console.print(f"[red]Project {project_id} not found[/red]")
        raise typer.Exit(1)
    workspace = Project.workspace_path(project.id, WORKSPACE_ROOT, project.tenant_id)

    requested = artifact.lower()
    if requested == "current":
        if project.state == ProjectState.INTAKE_DIALOG:
            requested = "intent"
        elif project.state == ProjectState.STACK_DIALOG:
            requested = "stack"
        elif project.state == ProjectState.PRD_DIALOG:
            requested = "prd"
        else:
            console.print(
                f"[yellow]Project is in '{project.state.value}', not a dialog "
                "state. Pass --artifact intent|stack|prd explicitly.[/yellow]"
            )
            raise typer.Exit(1)

    if requested == "intent":
        md = load_intent_md(workspace)
    elif requested == "stack":
        stack = load_locked_stack(workspace)
        md = stack.to_markdown() if stack is not None else None
    elif requested == "prd":
        md = load_prd_md(workspace)
    else:
        console.print(f"[red]Unknown artifact '{artifact}'[/red]")
        raise typer.Exit(1)

    if md is None:
        console.print(f"[yellow]No {requested}.md yet for {project.id}.[/yellow]")
        raise typer.Exit(1)
    console.print(md)


@app.command()
def lock(
    project_id: str,
    yes: bool = typer.Option(False, "--yes", "-y", help="Confirm prompts'ı atla."),
) -> None:
    """Aktif dialog state'i kilitle, bir sonrakine geç. Diff göster, onay al,
    bir sonraki state'in ilk draft'ını üret (varsa)."""
    import difflib

    from rich.panel import Panel

    from runtime.dialog import (
        load_current_artifact,
        load_intent_md,
        load_locked_stack,
        load_prev_snapshot,
    )

    project, workspace, audit, memory = _dialog_setup(project_id)
    _require_dialog_state(project)

    current = load_current_artifact(workspace, project.state)
    if current is None:
        console.print(
            f"[red]No artifact to lock — "
            f"{project.state.value} has no draft yet.[/red]"
        )
        raise typer.Exit(1)

    # Diff vs the previous turn's snapshot, if any. First-lock case has
    # no prior snapshot — we just show the current artifact in a panel.
    prev = load_prev_snapshot(workspace, project.state)
    if prev is not None and prev != current:
        diff_lines = list(
            difflib.unified_diff(
                prev.splitlines(keepends=False),
                current.splitlines(keepends=False),
                fromfile="prev",
                tofile="current",
                lineterm="",
                n=2,
            )
        )
        if diff_lines:
            console.print(
                Panel(
                    "\n".join(diff_lines),
                    title=f"Changes in {project.state.value}",
                    border_style="cyan",
                )
            )
    else:
        # First lock for this state — show the artifact compactly so the
        # operator can spot-check before committing.
        preview = current if len(current) < 1500 else current[:1500] + "\n…"
        console.print(
            Panel(
                preview,
                title=f"{project.state.value} — initial draft",
                border_style="cyan",
            )
        )

    if not yes:
        confirm = typer.confirm(
            f"Lock {project.state.value} and advance?", default=True
        )
        if not confirm:
            console.print("[yellow]Lock aborted.[/yellow]")
            raise typer.Exit(0)

    # Transition + drive the next state's initial draft (if any).
    if project.state == ProjectState.INTAKE_DIALOG:
        _lock_intake(project, workspace, audit, memory)
    elif project.state == ProjectState.STACK_DIALOG:
        _lock_stack(project, workspace, audit, memory)
    else:  # PRD_DIALOG
        _lock_prd(project, workspace, audit, memory)


def _lock_intake(project, workspace, audit, memory) -> None:
    """INTAKE_DIALOG → STACK_DIALOG. Run Architect Call 1 + tier scorer
    deterministically against intent.md (we use it as a stand-in PRD
    for tier scoring), then draft the initial stack proposal."""
    from runtime.agents import ArchitectAgent, StackAnalyst
    from runtime.dialog import (
        append_dialog_turn,
        load_intent_md,
        save_locked_stack,
    )
    from runtime.llm import client_for

    intent_md = load_intent_md(workspace)
    if intent_md is None:
        console.print("[red]intent.md missing — cannot advance.[/red]")
        raise typer.Exit(1)

    project.transition(
        ProjectState.STACK_DIALOG,
        actor="lock",
        note="intent locked; entering stack dialog",
    )
    project.save(WORKSPACE_ROOT)

    audit.log(
        "dialog_lock",
        project_id=project.id,
        from_state=ProjectState.INTAKE_DIALOG.value,
        to_state=ProjectState.STACK_DIALOG.value,
    )

    architect = ArchitectAgent(client_for("architect"), memory, audit)
    console.print(
        "[cyan]Architect:[/cyan] extracting Golden Path inputs from intent..."
    )
    gp_inputs = architect.extract_inputs(intent_md, project.id, codebase=None)
    (workspace / "golden_path_inputs.json").write_text(
        gp_inputs.model_dump_json(indent=2), encoding="utf-8"
    )

    tier_score = architect.select(gp_inputs, project.id)
    console.print(
        f"[bold]Tier suggestion:[/bold] [green]{tier_score.tier.value}[/green] "
        f"({tier_score.name}) — score {tier_score.score}"
    )

    console.print("[cyan]StackAnalyst:[/cyan] proposing initial stack...")
    stack_analyst = StackAnalyst(client_for("analyst"), memory, audit)
    stack = stack_analyst.propose(
        intent_md=intent_md,
        tier_suggestion=tier_score,
        app_class=gp_inputs.app_class.value,
        project_id=project.id,
    )
    save_locked_stack(workspace, stack)
    append_dialog_turn(
        workspace, ProjectState.STACK_DIALOG, None, stack.to_markdown()
    )
    console.print(
        f"[green]stack.json drafted:[/green] {stack.language} / "
        f"{stack.primary_framework}\n"
        f"  [cyan]ortim show {project.id}[/cyan]\n"
        f"  [cyan]ortim refine {project.id} \"<feedback>\"[/cyan]\n"
        f"  [cyan]ortim lock {project.id}[/cyan]"
    )


def _lock_stack(project, workspace, audit, memory) -> None:
    """STACK_DIALOG → PRD_DIALOG. Draft the initial PRD from locked
    intent + locked stack."""
    from runtime.agents import PRDAnalyst
    from runtime.dialog import (
        append_dialog_turn,
        load_intent_md,
        load_locked_stack,
        save_prd_md,
    )
    from runtime.llm import client_for

    intent_md = load_intent_md(workspace)
    stack = load_locked_stack(workspace)
    if intent_md is None or stack is None:
        console.print(
            "[red]intent.md or stack.json missing — cannot advance.[/red]"
        )
        raise typer.Exit(1)

    project.transition(
        ProjectState.PRD_DIALOG,
        actor="lock",
        note="stack locked; entering PRD dialog",
    )
    project.save(WORKSPACE_ROOT)

    audit.log(
        "dialog_lock",
        project_id=project.id,
        from_state=ProjectState.STACK_DIALOG.value,
        to_state=ProjectState.PRD_DIALOG.value,
    )

    console.print("[cyan]PRDAnalyst:[/cyan] drafting initial PRD...")
    prd_analyst = PRDAnalyst(client_for("analyst"), memory, audit)
    prd_md = prd_analyst.draft(
        intent_md=intent_md,
        stack=stack,
        project_name=project.name,
        project_id=project.id,
    )
    save_prd_md(workspace, prd_md)
    append_dialog_turn(workspace, ProjectState.PRD_DIALOG, None, prd_md)
    console.print(
        f"[green]PRD.md drafted:[/green] {workspace / 'PRD.md'}\n"
        f"  [cyan]ortim show {project.id}[/cyan]\n"
        f"  [cyan]ortim refine {project.id} \"<feedback>\"[/cyan]\n"
        f"  [cyan]ortim lock {project.id}[/cyan]"
    )


# ---- M3.1 `ortim extend` ------------------------------------------------


def _initiate_extend_prd(
    project,
    brief: str,
    workspace: Path,
    audit,
    memory,
    extender_llm,
    babel_llm,
):
    """Drive a project from DONE through to EXTEND_PRD_AWAITING_APPROVAL.

    Returns a tuple `(cycle, blocked_lib_or_none)`.
    - `cycle` is the 1-indexed extend cycle just initiated.
    - `blocked_lib_or_none` is the library name when ExtenderAgent emits a
      `[BLOCKED-STACK]` marker; the project state stays at EXTEND_PRD_DIALOG
      in that case (no PRD section appended). Otherwise it's None and the
      project state advances to EXTEND_PRD_AWAITING_APPROVAL.

    Raises:
    - InvalidTransition if `project.state` is not DONE.
    - FileNotFoundError if PRD.md / intent.md / stack.json are missing.
    """
    from runtime.architecture import LockedStack
    from runtime.babel import BabelLayer
    from runtime.extend import (
        BLOCKED_STACK_MARKER,
        ExtenderAgent,
        ExtensionIntent,
        append_delta_section,
        section_cycles_in,
    )

    intent_md_path = workspace / "intent.md"
    prd_path = workspace / "PRD.md"
    stack_path = workspace / "stack.json"
    for p in (intent_md_path, prd_path, stack_path):
        if not p.exists():
            raise FileNotFoundError(
                f"missing artifact required for extend: {p.name}"
            )

    existing_intent_md = intent_md_path.read_text(encoding="utf-8")
    existing_prd = prd_path.read_text(encoding="utf-8")
    locked_stack = LockedStack.model_validate_json(
        stack_path.read_text(encoding="utf-8")
    )

    cycle = max(section_cycles_in(existing_prd), default=0) + 1

    project.transition(
        ProjectState.EXTEND_DIALOG,
        actor="cli-extend",
        note=f"cycle {cycle} initiated",
    )
    audit.log(
        "extend_initiated",
        project_id=project.id,
        cycle=cycle,
        brief_chars=len(brief),
    )

    babel = BabelLayer(babel_llm, memory, audit)
    raw_intent = babel.extract(brief, project.id)
    extension_intent = ExtensionIntent(
        parent_project_id=project.id,
        cycle=cycle,
        goal=raw_intent.goal,
        must_have_features=list(raw_intent.must_have_features or []),
        explicit_non_goals=list(raw_intent.explicit_non_goals or []),
        constraints=list(raw_intent.constraints or []),
    )
    cycle_dir = workspace / "extensions" / f"cycle_{cycle}"
    cycle_dir.mkdir(parents=True, exist_ok=True)
    (cycle_dir / "intent.json").write_text(
        extension_intent.model_dump_json(indent=2), encoding="utf-8"
    )

    project.transition(
        ProjectState.EXTEND_PRD_DIALOG,
        actor="cli-extend",
        note="delta intent persisted; drafting PRD section",
    )
    project.save(WORKSPACE_ROOT)

    extender = ExtenderAgent(extender_llm, memory, audit)
    section = extender.draft_delta_prd(
        feature_brief=brief,
        existing_intent_md=existing_intent_md,
        existing_prd=existing_prd,
        locked_stack=locked_stack,
        cycle=cycle,
        project_id=project.id,
    )

    if section.startswith(BLOCKED_STACK_MARKER):
        # Stack-amendment escape hatch — do NOT append to PRD.md and
        # leave state at EXTEND_PRD_DIALOG so the user can either rework
        # the brief, abandon the extend, or wait for M3.2 stack-amendment.
        blocked_lib = section.removeprefix(BLOCKED_STACK_MARKER).split("—")[0]
        blocked_lib = blocked_lib.strip(" :")
        return cycle, blocked_lib

    append_delta_section(prd_path, section, cycle=cycle)

    project.transition(
        ProjectState.EXTEND_PRD_AWAITING_APPROVAL,
        actor="cli-extend",
        note=f"cycle {cycle} delta PRD locked; G1 HITL gate open",
    )
    project.save(WORKSPACE_ROOT)
    return cycle, None


def _extract_extension_section(text: str, cycle: int) -> str | None:
    """Return the text of `## Extension <cycle> — ...` from the document,
    spanning from that header until the next `## ` (any H2) or EOF.

    Returns `None` if the cycle's section isn't present. Used by the
    extend RFC handler to feed the latest delta PRD section into
    `ExtenderAgent.draft_delta_rfc`.
    """
    import re as _re

    pattern = _re.compile(
        rf"^##\s+Extension\s+{cycle}\b.*?(?=^##\s|\Z)",
        _re.MULTILINE | _re.DOTALL,
    )
    match = pattern.search(text)
    return match.group(0).rstrip() if match else None


def _extension_feature_title(section_text: str, fallback: str = "untitled") -> str:
    """Pull the title segment from a `## Extension N — Title` header. The
    separator may be em-dash / hyphen / colon; tolerate all three. Falls
    back to `fallback` when the header is bare (e.g. `## Extension 1`)."""
    import re as _re

    line = section_text.lstrip().splitlines()[0] if section_text.strip() else ""
    match = _re.match(
        r"^##\s+Extension\s+\d+\s*[—\-:]\s*(.+?)\s*$", line
    )
    return match.group(1).strip() if match else fallback


def _draft_extend_rfc(
    project,
    workspace: Path,
    audit,
    memory,
    extender_llm,
):
    """Drive EXTEND_PRD_APPROVED → EXTEND_RFC_AWAITING_APPROVAL.

    Returns `(cycle, blocked_lib_or_none)`. Mirrors `_initiate_extend_prd`:
    BLOCKED-STACK marker leaves state at EXTEND_RFC_DRAFTING (NOT
    advanced to G2) so the user can rework.
    """
    from runtime.architecture import LockedStack
    from runtime.extend import (
        BLOCKED_STACK_MARKER,
        ExtenderAgent,
        append_delta_section,
        section_cycles_in,
    )

    prd_path = workspace / "PRD.md"
    rfc_path = workspace / "RFC.md"
    stack_path = workspace / "stack.json"
    for p in (prd_path, rfc_path, stack_path):
        if not p.exists():
            raise FileNotFoundError(
                f"missing artifact required for extend RFC draft: {p.name}"
            )

    prd_text = prd_path.read_text(encoding="utf-8")
    rfc_text = rfc_path.read_text(encoding="utf-8")
    locked_stack = LockedStack.model_validate_json(
        stack_path.read_text(encoding="utf-8")
    )

    cycles = section_cycles_in(prd_text)
    if not cycles:
        raise RuntimeError(
            "EXTEND_PRD_APPROVED but PRD.md has no ## Extension sections; "
            "state machine and artifact disagree"
        )
    cycle = max(cycles)

    delta_prd_section = _extract_extension_section(prd_text, cycle)
    if delta_prd_section is None:
        raise RuntimeError(
            f"PRD.md cycle marker {cycle} not extractable (section parser "
            "regression?)"
        )

    project.transition(
        ProjectState.EXTEND_RFC_DRAFTING,
        actor="cli-extend-rfc",
        note=f"cycle {cycle} delta RFC drafting",
    )
    project.save(WORKSPACE_ROOT)

    codebase_summary = _load_codebase_summary(project, workspace)
    extender = ExtenderAgent(extender_llm, memory, audit)
    section = extender.draft_delta_rfc(
        delta_prd_section=delta_prd_section,
        existing_rfc=rfc_text,
        existing_codebase_summary=codebase_summary,
        locked_stack=locked_stack,
        cycle=cycle,
        project_id=project.id,
    )

    if section.startswith(BLOCKED_STACK_MARKER):
        blocked_lib = section.removeprefix(BLOCKED_STACK_MARKER).split("—")[0]
        blocked_lib = blocked_lib.strip(" :")
        return cycle, blocked_lib

    append_delta_section(rfc_path, section, cycle=cycle)

    project.transition(
        ProjectState.EXTEND_RFC_AWAITING_APPROVAL,
        actor="cli-extend-rfc",
        note=f"cycle {cycle} delta RFC locked; G2 HITL gate open",
    )
    project.save(WORKSPACE_ROOT)
    return cycle, None


def _generate_extend_dag(
    project,
    workspace: Path,
    audit,
    memory,
    orchestrator_llm,
):
    """Drive EXTEND_RFC_APPROVED → TASKS_GENERATING → TASKS_READY.

    Loads the persisted task_dag.json as prior_dag, runs Orchestrator
    with `prior_dag=...`, appends the delta tasks to task_dag.json and
    records a DagDelta in `extensions`. Returns `(cycle, new_task_count)`.
    """
    from runtime.agents import OrchestratorAgent
    from runtime.extend import (
        DagDelta,
        section_cycles_in,
    )
    from runtime.orchestrator import TaskDAG

    rfc_path = workspace / "RFC.md"
    dag_path = workspace / "task_dag.json"
    if not rfc_path.exists() or not dag_path.exists():
        raise FileNotFoundError(
            "EXTEND_RFC_APPROVED requires both RFC.md and task_dag.json"
        )

    rfc_text = rfc_path.read_text(encoding="utf-8")
    prior_dag = TaskDAG.model_validate_json(
        dag_path.read_text(encoding="utf-8")
    )

    cycles = section_cycles_in(rfc_text)
    if not cycles:
        raise RuntimeError(
            "EXTEND_RFC_APPROVED but RFC.md has no ## Extension sections"
        )
    cycle = max(cycles)

    project.transition(
        ProjectState.TASKS_GENERATING,
        actor="orchestrator-extend",
        note=f"cycle {cycle} delta DAG",
    )
    project.save(WORKSPACE_ROOT)

    orchestrator_agent = OrchestratorAgent(orchestrator_llm, memory, audit)
    try:
        delta_dag = orchestrator_agent.generate_dag(
            rfc_markdown=rfc_text,
            project_id=project.id,
            prior_dag=prior_dag,
        )
    except RuntimeError as e:
        project.transition(
            ProjectState.FAILED, actor="orchestrator-extend", note=str(e)[:200]
        )
        project.save(WORKSPACE_ROOT)
        raise

    # Derive the feature title from the RFC's `## Extension <cycle>` line.
    delta_rfc_section = _extract_extension_section(rfc_text, cycle) or ""
    title = _extension_feature_title(delta_rfc_section)

    # Persist merged DAG: prior tasks + new tasks + new DagDelta entry.
    delta = DagDelta(
        cycle=cycle,
        feature_title=title,
        new_tasks=list(delta_dag.tasks),
        starts_from_task_id=delta_dag.tasks[0].id,
    )
    merged = TaskDAG(
        project_id=project.id,
        tasks=[*prior_dag.tasks, *delta_dag.tasks],
        extensions=[*prior_dag.extensions, delta.model_dump()],
    )
    dag_path.write_text(merged.model_dump_json(indent=2), encoding="utf-8")

    # Per-task markdown files for the new tasks (existing ones already
    # written when initial DAG was generated).
    task_template = memory.load_template("Task")
    tasks_dir = workspace / "tasks"
    tasks_dir.mkdir(exist_ok=True)
    for task in delta_dag.tasks:
        md = _render_task_md(task, task_template, project.id)
        (tasks_dir / f"{task.id}.md").write_text(md, encoding="utf-8")

    audit.log(
        "extend_dag_appended",
        project_id=project.id,
        cycle=cycle,
        new_task_count=len(delta_dag.tasks),
        new_task_ids=[t.id for t in delta_dag.tasks],
    )

    project.transition(
        ProjectState.TASKS_READY,
        actor="orchestrator-extend",
        note=f"cycle {cycle}: {len(delta_dag.tasks)} new tasks",
    )
    project.save(WORKSPACE_ROOT)
    return cycle, len(delta_dag.tasks)


def _list_extensions(workspace: Path) -> list[tuple[int, str]]:
    """Return [(cycle, header_line), ...] for every extension in PRD.md.
    `header_line` is the full `## Extension N — Title` line as it appears
    in the file. Used by `ortim extensions <id>` for the table render."""
    from runtime.extend import section_cycles_in

    prd_path = workspace / "PRD.md"
    if not prd_path.exists():
        return []
    text = prd_path.read_text(encoding="utf-8")
    cycles = section_cycles_in(text)
    out: list[tuple[int, str]] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped.startswith("## Extension"):
            continue
        # Match the cycle integer and pair with its header line.
        for c in cycles:
            if stripped.startswith(f"## Extension {c}"):
                out.append((c, stripped))
                cycles.remove(c)
                break
    return out


@app.command("extend")
def extend_cmd(
    project_id: str = typer.Argument(..., help="Mevcut DONE projenin ID'si"),
    brief: str = typer.Argument(..., help="Yeni feature için Türkçe brief"),
) -> None:
    """M3.1 — DONE projeye yeni bir feature delta'sı ekle.

    Project DONE durumunda olmalı. Babel + ExtenderAgent çalıştırır,
    PRD.md'ye `## Extension <N>` bölümü ekler, G1 (cycle N) HITL
    gate'inde durur. ExtenderAgent BLOCKED-STACK marker'ı üretirse
    bölüm yazılmaz; kullanıcı bilgilendirilir."""
    from runtime.audit import AuditLogger
    from runtime.llm import client_for
    from runtime.memory import MemoryLoader

    try:
        project = Project.load(project_id, WORKSPACE_ROOT)
    except FileNotFoundError:
        console.print(f"[red]Project {project_id} not found[/red]")
        raise typer.Exit(1)

    if project.state != ProjectState.DONE:
        console.print(
            f"[red]extend requires DONE state; project is "
            f"{project.state.value}[/red]"
        )
        raise typer.Exit(1)

    memory = MemoryLoader(REPO_ROOT)
    audit = AuditLogger()
    workspace = Project.workspace_path(project.id, WORKSPACE_ROOT)

    try:
        babel_llm = client_for("babel")
        extender_llm = client_for("analyst")  # ExtenderAgent role
    except RuntimeError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)

    try:
        cycle, blocked = _initiate_extend_prd(
            project=project,
            brief=brief,
            workspace=workspace,
            audit=audit,
            memory=memory,
            extender_llm=extender_llm,
            babel_llm=babel_llm,
        )
    except FileNotFoundError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)
    except InvalidTransition as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)

    if blocked is not None:
        console.print(
            f"[yellow]BLOCKED-STACK[/yellow]: cycle {cycle} requires "
            f"library [bold]{blocked}[/bold] which is not in the locked "
            "stack. Either rework the brief to use existing libraries, or "
            "wait for stack-amendment support (M3.2). Project state stays "
            f"at [cyan]{project.state.value}[/cyan]."
        )
        return

    console.print(
        f"[green]Extension cycle {cycle} delta PRD written.[/green]\n"
        f"State: [cyan]{project.state.value}[/cyan]\n"
        f"\n[yellow]HITL Gate G1 (cycle {cycle}):[/yellow] "
        f"PRD.md'nin yeni `## Extension {cycle}` bölümünü gözden geçir, "
        "onaylamak için:\n"
        f"  [cyan]ortim advance {project.id} extend_prd_approved "
        "--note 'reviewed'[/cyan]"
    )


@app.command("extensions")
def extensions_cmd(
    project_id: str = typer.Argument(..., help="Project ID"),
) -> None:
    """M3.1 — Projenin extend cycle geçmişini listele (PRD.md'den okur)."""
    try:
        project = Project.load(project_id, WORKSPACE_ROOT)
    except FileNotFoundError:
        console.print(f"[red]Project {project_id} not found[/red]")
        raise typer.Exit(1)

    workspace = Project.workspace_path(project.id, WORKSPACE_ROOT)
    rows = _list_extensions(workspace)
    if not rows:
        console.print(
            f"No extensions yet for [bold]{project_id}[/bold]. Use "
            f"[cyan]ortim extend {project_id} \"<feature brief>\"[/cyan] "
            "to add one (project must be DONE)."
        )
        return

    table = Table(title=f"Extensions for {project_id}")
    table.add_column("Cycle", style="cyan")
    table.add_column("Header line")
    for cycle, header in rows:
        table.add_row(str(cycle), header)
    console.print(table)


def _lock_prd(project, workspace, audit, memory) -> None:
    """PRD_DIALOG → PRD_AWAITING_APPROVAL. No further drafting; this is
    the existing G1 HITL gate. The user inspects PRD.md and runs
    `ortim advance <id> prd_approved` to continue."""
    project.transition(
        ProjectState.PRD_AWAITING_APPROVAL,
        actor="lock",
        note="PRD locked; G1 HITL gate open",
    )
    project.save(WORKSPACE_ROOT)
    audit.log(
        "dialog_lock",
        project_id=project.id,
        from_state=ProjectState.PRD_DIALOG.value,
        to_state=ProjectState.PRD_AWAITING_APPROVAL.value,
    )
    console.print(
        f"[green]PRD locked.[/green] State: "
        f"[cyan]{project.state.value}[/cyan]\n"
        f"\n[yellow]HITL Gate G1:[/yellow] PRD'yi gözden geçir, onaylamak için:\n"
        f"  [cyan]ortim advance {project.id} prd_approved --note 'reviewed'[/cyan]"
    )


skill_app = typer.Typer(help="M3 skills inspection.", no_args_is_help=True)
app.add_typer(skill_app, name="skill")


@skill_app.command("list")
def skill_list(
    project_id: str = typer.Argument(
        None,
        help="Opsiyonel proje ID. Verilirse o projenin stack'ine uyan skills'ler listelenir.",
    ),
) -> None:
    """Yüklenmiş skills'leri (ya da bir projenin stack'ine resolve olanları) tabloda göster."""
    from runtime.skills import load_all_skills, resolve_for_task

    skills = load_all_skills(REPO_ROOT)
    if not skills:
        console.print(
            "[yellow]No skills under <repo_root>/skills/. "
            "Add skill files there to populate this list.[/yellow]"
        )
        return

    if project_id is None:
        table = Table(title=f"All skills ({len(skills)})")
        table.add_column("Name", style="cyan")
        table.add_column("Audience")
        table.add_column("Triggers")
        table.add_column("Description")
        for sk in skills:
            trig_parts: list[str] = []
            if sk.triggers.language:
                trig_parts.append(f"lang={','.join(sk.triggers.language)}")
            if sk.triggers.tier:
                trig_parts.append(f"tier={','.join(sk.triggers.tier)}")
            if sk.triggers.app_class:
                trig_parts.append(f"app={','.join(sk.triggers.app_class)}")
            if sk.triggers.keywords:
                trig_parts.append(f"kw={','.join(sk.triggers.keywords)}")
            table.add_row(
                sk.name,
                "/".join(sk.audience),
                ", ".join(trig_parts) or "(universal)",
                sk.description,
            )
        console.print(table)
        return

    # Project-specific resolve: load stack + tier and probe with a stub task
    try:
        project = Project.load(project_id, WORKSPACE_ROOT)
    except FileNotFoundError:
        console.print(f"[red]Project {project_id} not found[/red]")
        raise typer.Exit(1)
    workspace = Project.workspace_path(project.id, WORKSPACE_ROOT, project.tenant_id)

    from runtime.architecture import GoldenPathInputs, select_tier
    from runtime.dialog import load_locked_stack
    from runtime.orchestrator import TaskSpec

    locked_stack = load_locked_stack(workspace)
    tier: str | None = None
    gp_path = workspace / "golden_path_inputs.json"
    if gp_path.exists():
        try:
            gp_inputs = GoldenPathInputs.model_validate_json(
                gp_path.read_text(encoding="utf-8")
            )
            tier = select_tier(gp_inputs).tier.value
        except Exception:
            tier = None

    # Probe task — broad keywords so any keyword-triggered skill matches.
    probe = TaskSpec(
        id="T-probe",
        title="probe",
        description=(
            "test vitest expect behavior criteria assert component ui render "
            "props react tsx jsx hook import module"
        ),
        module_scope="probe",
        rfc_section="§probe",
        acceptance_criteria=["probe"],
        estimated_tokens=100,
    )
    worker = resolve_for_task(
        skills=skills,
        task=probe,
        tier=tier,
        app_class=project.app_class or "web",
        locked_stack=locked_stack,
        audience="worker",
    )
    reviewer = resolve_for_task(
        skills=skills,
        task=probe,
        tier=tier,
        app_class=project.app_class or "web",
        locked_stack=locked_stack,
        audience="reviewer",
    )
    console.print(
        f"[bold]Project {project_id}[/bold] — "
        f"tier={tier or '?'}, app_class={project.app_class}, "
        f"stack_lang={locked_stack.language if locked_stack else '?'}"
    )
    table = Table(title="Resolved skills")
    table.add_column("Name", style="cyan")
    table.add_column("Worker")
    table.add_column("Reviewer")
    worker_names = {s.name for s in worker}
    reviewer_names = {s.name for s in reviewer}
    for name in sorted(worker_names | reviewer_names):
        table.add_row(
            name,
            "✓" if name in worker_names else "",
            "✓" if name in reviewer_names else "",
        )
    if table.row_count == 0:
        console.print("[yellow]No skills resolve for this project.[/yellow]")
    else:
        console.print(table)


@skill_app.command("show")
def skill_show(name: str) -> None:
    """Bir skill'in tüm gövdesini (frontmatter + body) konsola bas."""
    from runtime.skills import load_all_skills

    skills = load_all_skills(REPO_ROOT)
    match = next((s for s in skills if s.name == name), None)
    if match is None:
        console.print(f"[red]No skill named '{name}'.[/red]")
        console.print("Available:")
        for s in skills:
            console.print(f"  - {s.name}")
        raise typer.Exit(1)
    console.print(f"[dim]Source: {match.path}[/dim]\n")
    console.print(f"[bold cyan]{match.name}[/bold cyan] — {match.description}")
    console.print(f"Audience: {', '.join(match.audience)}")
    triggers_info: list[str] = []
    if match.triggers.tier:
        triggers_info.append(f"tier={match.triggers.tier}")
    if match.triggers.app_class:
        triggers_info.append(f"app_class={match.triggers.app_class}")
    if match.triggers.language:
        triggers_info.append(f"language={match.triggers.language}")
    if match.triggers.keywords:
        triggers_info.append(f"keywords={match.triggers.keywords}")
    if triggers_info:
        console.print(f"Triggers: {' / '.join(triggers_info)}")
    else:
        console.print("Triggers: (universal)")
    console.print(f"\n{match.body}")


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

    # M2: locked_stack (from STACK_DIALOG lock) — single source of truth for
    # language / framework / test_cmd that downstream layers consume.
    from runtime.dialog import load_locked_stack

    locked_stack = load_locked_stack(workspace)

    # Recompute tier deterministically from the cached gp_inputs so we
    # don't need a new persisted Project field. Mirrors `_bootstrap_if_ready`.
    tier: str | None = None
    gp_path = workspace / "golden_path_inputs.json"
    if gp_path.exists():
        from runtime.architecture import GoldenPathInputs, select_tier

        try:
            gp_inputs = GoldenPathInputs.model_validate_json(
                gp_path.read_text(encoding="utf-8")
            )
            tier = select_tier(gp_inputs).tier.value
        except Exception:
            tier = None

    # M3: load all skills once per execute/run-all invocation. The
    # resolver picks the right subset per task in the runner.
    from runtime.skills import load_all_skills

    skills = load_all_skills(REPO_ROOT)

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
        locked_stack,
        tier,
        skills,
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
    from runtime.dialog import load_locked_stack

    inputs = GoldenPathInputs.model_validate_json(
        inputs_path.read_text(encoding="utf-8")
    )
    tier_score = select_tier(inputs)
    modules = sorted({t.module_scope for t in dag.tasks})
    # M2: when a LockedStack exists, it overrides heuristic test-cmd
    # selection in bootstrap. Closes items 17 + 18a structurally.
    locked_stack = load_locked_stack(workspace)
    created = bootstrap_workspace_layout(
        workspace,
        modules=modules,
        tier=tier_score.tier.value,
        app_class=app_class,
        project_name=project.name,
        locked_stack=locked_stack,
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


def _maybe_open_schema_gate(project, dag, audit) -> tuple[bool, list[str]]:
    """G3 — when DAG has migration/schema tasks and project is still in
    TASKS_READY, transition to SCHEMA_AWAITING_APPROVAL and halt. Returns
    `(gated, task_ids)`. The caller is responsible for printing a clear
    HITL message and exiting non-zero.

    Idempotent: if project state has already moved past TASKS_READY (e.g.
    the user already approved and we're back in EXECUTING after extend
    cycle), the gate does NOT re-fire. State transition is the only
    "have we approved this batch" signal — extending re-enters
    TASKS_READY, so a new migration in the delta DAG will gate again.
    """
    from runtime.orchestrator import detect_schema_tasks

    if project.state != ProjectState.TASKS_READY:
        return False, []
    evidence = detect_schema_tasks(dag)
    if not evidence.triggered:
        return False, []

    project.transition(
        ProjectState.SCHEMA_AWAITING_APPROVAL,
        actor="executor",
        note=f"schema gate opened for {', '.join(evidence.task_ids)}",
    )
    audit.log(
        "gate_schema_opened",
        project_id=project.id,
        task_ids=list(evidence.task_ids),
    )
    project.save(WORKSPACE_ROOT)
    return True, list(evidence.task_ids)


def _print_schema_gate_message(task_ids: list[str]) -> None:
    console.print(
        "[yellow]G3 — Schema/migration gate opened.[/yellow]"
    )
    console.print(
        f"Tasks flagged: [bold]{', '.join(task_ids)}[/bold]"
    )
    console.print(
        "Review each migration task carefully (data integrity / "
        "downtime risk). When ready:"
    )
    console.print(
        "  [cyan]ortim advance <project-id> schema_approved[/cyan]"
    )
    console.print(
        "Or to bounce back for DAG revision:"
    )
    console.print(
        "  [cyan]ortim advance <project-id> tasks_ready[/cyan]"
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
        locked_stack,
        tier,
        skills,
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
        gated, gated_ids = _maybe_open_schema_gate(project, dag, audit)
        if gated:
            _print_schema_gate_message(gated_ids)
            raise typer.Exit(code=2)
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
            locked_stack=locked_stack,
            tier=tier,
            skills=skills,
            dag=dag,
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
        locked_stack,
        tier,
        skills,
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
        gated, gated_ids = _maybe_open_schema_gate(project, dag, audit)
        if gated:
            _print_schema_gate_message(gated_ids)
            raise typer.Exit(code=2)
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
                locked_stack=locked_stack,
                tier=tier,
                skills=skills,
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

                # M2: hand the locked stack to the documenter so README's
                # install / test / run commands match the agreed stack
                # exactly (no language-guessing).
                from runtime.dialog import load_locked_stack
                locked_stack = load_locked_stack(workspace)

                readme_text = documenter.generate_readme(
                    project_name=project.name,
                    prd_text=prd_text,
                    rfc_text=rfc_text,
                    project_id=project.id,
                    locked_stack=locked_stack,
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
    locked_stack=None,
    tier=None,
    skills=None,
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
                        locked_stack=locked_stack,
                        tier=tier,
                        skills=skills,
                        dag=dag,
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
                        locked_stack=locked_stack,
                        tier=tier,
                        skills=skills,
                        dag=dag,
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


@app.command("drift-check")
def drift_check(
    project_id: str = typer.Argument(..., help="Proje ID"),
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

    from runtime.audit import AuditLogger
    from runtime.extend import drift_to_json_dict, inspect_drift

    workspace = WORKSPACE_ROOT / project_id
    if not workspace.exists():
        console.print(f"[red]Workspace not found: {workspace}[/red]")
        raise typer.Exit(code=1)

    try:
        report = inspect_drift(workspace, project_id=project_id)
    except FileNotFoundError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(code=1) from None

    audit = AuditLogger()
    audit.log(
        "drift_check_run",
        project_id=project_id,
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
            f"[bold]Drift Check — {project_id}[/bold] "
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


@app.command()
def retro(
    project_id: str = typer.Argument(..., help="Proje ID"),
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

    from runtime.audit import aggregate, to_json_dict

    report = aggregate(project_id, workspace_root=WORKSPACE_ROOT)

    if as_json:
        console.print_json(_json.dumps(to_json_dict(report)))
        return

    if report.total_llm_calls == 0 and not report.per_task:
        console.print(
            f"[yellow]No audit data found for project '{project_id}'.[/yellow]"
        )
        console.print(
            "[dim](Either the project hasn't run yet, or AUDIT_LOG_PATH "
            "points elsewhere.)[/dim]"
        )
        return

    if not per_task:
        headline = Table(title=f"Retro — {project_id}")
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
