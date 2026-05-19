"""CLI: yürütme komutları — tasks, execute, run-all + skill/* subcommands."""

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

skill_app = typer.Typer(help="M3 skills inspection.", no_args_is_help=True)

def skill_list(
    project_id: str = typer.Argument(
        None,
        help="Opsiyonel proje ID. Verilirse o projenin stack'ine uyan skills'ler listelenir.",
    ),
) -> None:
    """Yüklenmiş skills'leri (ya da bir projenin stack'ine resolve olanları) tabloda göster."""
    from ortim.skills import load_all_skills, resolve_for_task

    skills = load_all_skills(_globals.REPO_ROOT)
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
        project = Project.load(project_id, _globals.WORKSPACE_ROOT)
    except FileNotFoundError:
        console.print(f"[red]Project {project_id} not found[/red]")
        raise typer.Exit(1)
    workspace = project.current_metadata_dir(_globals.WORKSPACE_ROOT)

    from ortim.architecture import GoldenPathInputs, select_tier
    from ortim.dialog import load_locked_stack
    from ortim.orchestrator import TaskSpec

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


def skill_show(name: str) -> None:
    """Bir skill'in tüm gövdesini (frontmatter + body) konsola bas."""
    from ortim.skills import load_all_skills

    skills = load_all_skills(_globals.REPO_ROOT)
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
def tasks(
    project_id: str = typer.Argument(
        None,
        help="Workspace ID. Boş bırakılırsa cwd'den keşfedilir.",
    ),
) -> None:
    """List task DAG for a project."""
    from ortim.orchestrator import TaskDAG

    project, store, _ = _resolve_project(project_id)
    dag_path = store.artifact_path("task_dag.json")
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

    `ORTIM_HARD_REVIEWERS=on` enables all three; off (default) returns None.
    A missing API key for a specific reviewer's provider degrades that reviewer
    to None with a warning rather than crashing the whole run — operators can
    opt into a partial chain (e.g., security only) by leaving other API keys
    unset.
    """
    from ortim.executor import (
        PerfReviewerAgent,
        ReviewerChain,
        SecurityReviewerAgent,
        TestReviewerAgent,
    )
    from ortim.llm import client_for

    flag = (env_get("ORTIM_HARD_REVIEWERS", "off") or "off").strip().lower()
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
            "[yellow]ORTIM_HARD_REVIEWERS=on but no reviewer could be built;"
            " falling back to CodeReviewer-only.[/yellow]"
        )
        return None
    return chain
def _load_for_execute(project_id: str | None):
    """Shared loading for `execute` and `run-all` commands.

    Returns (project, workspace, dag, status_file, worker_llm, reviewer_llm,
    reviewer_chain, memory, audit, rfc_text) or raises typer.Exit on any
    precondition failure. Worker and Reviewer get separate clients so they
    can sit on different providers/models per the Faz 6a routing contract.
    Hard-veto reviewers are wired only when `ORTIM_HARD_REVIEWERS=on`.
    """
    from ortim.audit import AuditLogger
    from ortim.executor import TaskStatusFile
    from ortim.llm import client_for
    from ortim.memory import MemoryLoader
    from ortim.orchestrator import TaskDAG

    project, store, _ = _resolve_project(project_id)
    _block_if_archived(project, action="execute tasks")

    if project.state not in (ProjectState.TASKS_READY, ProjectState.EXECUTING):
        console.print(
            f"[red]State {project.state.value} does not allow execution. "
            f"Need tasks_ready or executing.[/red]"
        )
        raise typer.Exit(1)

    workspace = store.metadata_dir
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

    memory = MemoryLoader(_globals.REPO_ROOT)
    audit = AuditLogger(path=store.audit_log_path())
    reviewer_chain = _build_reviewer_chain(memory, audit)

    status_file = TaskStatusFile.load_or_init(workspace, project.id)

    # M1: brownfield projects feed real codebase context into the executor so
    # Worker sees `related_files` and the sandbox enforces the right ext set.
    codebase_summary = _load_codebase_summary(project, workspace)
    app_class = project.app_class or "web"

    # M2: locked_stack (from STACK_DIALOG lock) — single source of truth for
    # language / framework / test_cmd that downstream layers consume.
    from ortim.dialog import load_locked_stack

    locked_stack = load_locked_stack(workspace)

    # Recompute tier deterministically from the cached gp_inputs so we
    # don't need a new persisted Project field. Mirrors `_bootstrap_if_ready`.
    tier: str | None = None
    gp_path = workspace / "golden_path_inputs.json"
    if gp_path.exists():
        from ortim.architecture import GoldenPathInputs, select_tier

        try:
            gp_inputs = GoldenPathInputs.model_validate_json(
                gp_path.read_text(encoding="utf-8")
            )
            tier = select_tier(gp_inputs).tier.value
        except Exception:
            tier = None

    # M3: load all skills once per execute/run-all invocation. The
    # resolver picks the right subset per task in the runner.
    from ortim.skills import load_all_skills

    skills = load_all_skills(_globals.REPO_ROOT)

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
    from ortim.executor import TaskStatus

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
    from ortim.architecture import (
        GoldenPathInputs,
        bootstrap_workspace_layout,
        select_tier,
    )
    from ortim.dialog import load_locked_stack

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
    from ortim.orchestrator import detect_schema_tasks

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
    project.save(_globals.WORKSPACE_ROOT)
    return True, list(evidence.task_ids)
def _maybe_open_budget_gate(project, audit) -> tuple[bool, float, float]:
    """G7 — when accumulated spend reaches `ORTIM_BUDGET_CAP_USD`
    and the project is still EXECUTING, transition to
    BUDGET_AWAITING_APPROVAL. Returns `(gated, spent_usd, cap_usd)`.

    G7 is the only HITL gate that Ortim_Architecture.md §8 marks
    override-able — a hard ceiling on cost is operationally wrong, but
    silent overrun is worse. The gate surfaces the breach + a
    standardized audit event; the operator decides whether to approve
    the overage or pause.

    No-ops when:
      * `ORTIM_BUDGET_CAP_USD` is unset or non-positive
      * project state is not EXECUTING (already gated or finalized)
    """
    cap_raw = env_get("ORTIM_BUDGET_CAP_USD")
    if not cap_raw:
        return False, 0.0, 0.0
    try:
        cap = float(cap_raw)
    except ValueError:
        return False, 0.0, 0.0
    if cap <= 0:
        return False, 0.0, 0.0
    if project.state != ProjectState.EXECUTING:
        return False, 0.0, cap

    from ortim.budget import BudgetTracker
    from ortim.orchestrator import detect_budget_breach

    evidence = detect_budget_breach(BudgetTracker(), project.id, cap)
    if not evidence.triggered:
        return False, evidence.spent_usd, cap

    project.transition(
        ProjectState.BUDGET_AWAITING_APPROVAL,
        actor="executor",
        note=(
            f"budget cap breached: "
            f"${evidence.spent_usd:.4f} >= ${cap:.4f}"
        ),
    )
    audit.log(
        "gate_budget_opened",
        project_id=project.id,
        spent_usd=evidence.spent_usd,
        cap_usd=cap,
        overage_pct=evidence.overage_pct,
    )
    project.save(_globals.WORKSPACE_ROOT)
    return True, evidence.spent_usd, cap
def _print_budget_gate_message(spent: float, cap: float) -> None:
    overage_pct = round((spent / cap) * 100, 1) if cap > 0 else 0.0
    console.print(
        f"[yellow]G7 — Budget cap breached.[/yellow] "
        f"Spent [bold]${spent:.4f}[/bold] / cap "
        f"[bold]${cap:.4f}[/bold] ({overage_pct}%)"
    )
    console.print("Two options:")
    console.print(
        "  [cyan]ortim advance <project-id> budget_approved[/cyan]  "
        "(approve this overage and continue)"
    )
    console.print(
        "  [cyan]ortim advance <project-id> paused[/cyan]  "
        "(halt and review)"
    )
    console.print(
        "[dim]Note: the cap is per-invocation. To raise it for future "
        "runs, set ORTIM_BUDGET_CAP_USD to a higher value or unset "
        "it entirely.[/dim]"
    )
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
    from ortim.executor import TaskStatus

    if not all(
        (rec := status_file.records.get(t.id)) and rec.status == TaskStatus.DONE
        for t in dag.tasks
    ):
        return False
    if project.state != ProjectState.EXECUTING:
        return False
    project.transition(ProjectState.DONE, actor="executor", note="all tasks done")
    project.save(_globals.WORKSPACE_ROOT)
    return True
def execute(
    task_id: str = typer.Argument(..., help="Task ID (T-...)"),
    max_attempts: int = typer.Option(3, help="Reject sonrasi max retry"),
    human_reviewed: bool = typer.Option(
        False,
        "--human-reviewed",
        help="Faz 1.5 — sensitive_categories tagged task'lari icin insan onayini "
        "bildirir. Bu olmadan auth/pii/payment kategorilerindeki task'lar "
        "reviewer'i gectikten sonra AWAITING_HITL'e dusurulur.",
    ),
    project_id: str = typer.Option(
        None,
        "--project",
        "-p",
        help="Workspace ID (pool legacy). Boş bırakılırsa cwd'den keşfedilir.",
    ),
) -> None:
    """Tek bir task'i Worker -> tests -> Reviewer pipeline'indan gecir.

    v0.5b: gercek kod + git branch (auto-on if `git` available) +
    ORTIM_TEST_CMD set ise test runner.

    Faz 1.5: sensitive task'lar (auth/pii/payment) icin --human-reviewed
    flag'i ile insan onayini sinyalle.
    """
    from ortim.executor import TaskStatus, execute_task

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
        project.save(_globals.WORKSPACE_ROOT)

    # G7 — re-check budget on every single-task execute as well. The
    # operator may invoke `ortim execute` after `budget_approved` to
    # advance the next task; if the previous overage was just barely
    # tolerated, the next call also gets a fresh decision point.
    budget_gated, spent, cap = _maybe_open_budget_gate(project, audit)
    if budget_gated:
        _print_budget_gate_message(spent, cap)
        raise typer.Exit(code=2)

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
            human_reviewed=human_reviewed,
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
def run_all(
    project_id: str = typer.Argument(
        None,
        help="Workspace ID. Boş bırakılırsa cwd'den keşfedilir.",
    ),
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
    phase: int = typer.Option(
        None,
        "--phase",
        help="Faz 1.1 — sadece phase <= N task'larini kostur. Omit=tum phaselar.",
    ),
) -> None:
    """DAG'i topolojik batch'lerde calistir.

    - sequential (default): tek tek, ana repo'da `task/<id>` checkout
    - parallel: batch icindeki task'lar ThreadPoolExecutor + git worktree
      ile paralel; merge'ler seri, status save lock altinda. Gerektirir:
      git PATH'te ve `ORTIM_GIT_ENABLED` 'false' degil.
    - --phase N: scope.json'da phase>N olarak isaretli task'lar atlanir
      (DAG'da kalir ama PENDING durur). Phase ayrimi ortim scope ile yapilir.
    """
    from ortim.concurrency import LockTimeout, file_lock
    from ortim.executor import GitNotAvailable, git_enabled

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
                    "(set ORTIM_GIT_ENABLED=auto or true)[/red]"
                )
                raise typer.Exit(1)
        except GitNotAvailable as e:
            console.print(f"[red]{e}[/red]")
            raise typer.Exit(1)

    batches = dag.topological_batches()
    tasks_by_id = {t.id: t for t in dag.tasks}

    # Faz 1.1 — phase filter. Empty batches (all tasks filtered out) are
    # dropped so the loop doesn't iterate placeholders. Tasks with
    # phase > limit stay in tasks_by_id (deps may reference them) but
    # never enter the batch loop, so they remain PENDING.
    if phase is not None:
        if phase < 1:
            console.print("[red]--phase must be >= 1[/red]")
            raise typer.Exit(1)
        filtered: list[list[str]] = []
        skipped = 0
        for batch in batches:
            keep = [tid for tid in batch if tasks_by_id[tid].phase <= phase]
            skipped += len(batch) - len(keep)
            if keep:
                filtered.append(keep)
        if skipped:
            console.print(
                f"[dim]--phase {phase}: skipping {skipped} task(s) with phase > {phase}[/dim]"
            )
        batches = filtered
        audit.log(
            "run_all_phase_filter",
            project_id=project.id,
            phase_limit=phase,
            kept=sum(len(b) for b in filtered),
            skipped=skipped,
        )

    if project.state == ProjectState.TASKS_READY:
        gated, gated_ids = _maybe_open_schema_gate(project, dag, audit)
        if gated:
            _print_schema_gate_message(gated_ids)
            raise typer.Exit(code=2)
        _bootstrap_if_ready(project, workspace, dag, app_class, audit)
        project.transition(
            ProjectState.EXECUTING, actor="executor", note="run-all start"
        )
        project.save(_globals.WORKSPACE_ROOT)

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
                from ortim.agents.documenter import DocumenterAgent
                from ortim.llm import client_for
                
                doc_llm = client_for("analyst")
                documenter = DocumenterAgent(doc_llm, memory, audit)

                prd_text = (workspace / "PRD.md").read_text(encoding="utf-8") if (workspace / "PRD.md").exists() else ""

                # M2: hand the locked stack to the documenter so README's
                # install / test / run commands match the agreed stack
                # exactly (no language-guessing).
                from ortim.dialog import load_locked_stack
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

    from ortim.executor import (
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

        # G7 — check budget cap after every batch. Single check per batch
        # is the right granularity: per-task is noisy, end-of-run is too
        # late (entire DAG could overrun before we notice).
        budget_gated, spent, cap = _maybe_open_budget_gate(project, audit)
        if budget_gated:
            _print_budget_gate_message(spent, cap)
            blocked = True
            break

        if blocked and stop_on_fail:
            break

    return blocked


def register(app: typer.Typer) -> None:
    """Wire execution-module commands onto the top-level Typer app."""
    skill_app.command("list")(skill_list)
    skill_app.command("show")(skill_show)
    app.add_typer(skill_app, name="skill")
    app.command()(tasks)
    app.command()(execute)
    app.command("run-all")(run_all)
