"""CLI: planning commands — run, advance, gates, extend, scope, dialog."""

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

from ortim.cli.execution import _render_task_md

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
def advance(
    target: str = typer.Argument(..., help="Target state or alias (intake, prd_drafting, schema_approved, ...)"),
    note: str = typer.Option("", help="Note for the state change"),
    project_id: str = typer.Option(
        None,
        "--project",
        "-p",
        help="Workspace ID (pool legacy). If omitted, discovered from cwd.",
    ),
) -> None:
    """Manually advance the project state (HITL approvals + emergencies)."""
    from ortim.audit import AuditLogger

    project, store, _ = _resolve_project(project_id)
    _block_if_archived(project, action="advance")

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

    store.save(project)
    if audit_event:
        # Surface the alias intent so `ortim retro` and downstream audit
        # tooling can distinguish "schema approval" from a bare state
        # bump that happened to land on EXECUTING.
        AuditLogger(path=store.audit_log_path()).log(
            audit_event,
            project_id=project.id,
            note=note,
            target_state=target_state.value,
        )
    console.print(f"[green]{project.id}[/green] -> [cyan]{target_state.value}[/cyan]")
    if gate := project.awaiting_human():
        console.print(f"[yellow]HITL gate:[/yellow] {gate}")
def gates(
    project_id: str = typer.Argument(
        None,
        help="Workspace ID. If omitted, discovered from cwd.",
    ),
) -> None:
    """Open HITL gates for a project (G1–G7)."""
    from ortim.budget import BudgetTracker
    from ortim.orchestrator import (
        HITL_GATES,
        TaskDAG,
        detect_budget_breach,
        detect_schema_tasks,
    )

    project, store, _ = _resolve_project(project_id)

    table = Table(title=f"Gates for {project.id}")
    table.add_column("Gate", style="cyan")
    table.add_column("Status")
    table.add_column("Detail")

    # Project-level gate (current state)
    gate_label = HITL_GATES.get(project.state)
    if gate_label:
        table.add_row(gate_label, "[yellow]OPEN[/yellow]", "current project state")

    # G3 — schema (DAG-derived, advisory if not in SCHEMA_AWAITING_APPROVAL)
    dag_path = store.artifact_path("task_dag.json")
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
    cap = env_get("ORTIM_BUDGET_CAP_USD")
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
def states() -> None:
    """List all states and transitions."""
    from ortim.orchestrator.state_machine import HITL_GATES, TRANSITIONS

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
def run(
    project_id: str = typer.Argument(
        None,
        help="Workspace ID. If omitted, discovered from cwd.",
    ),
    step: str = typer.Option(
        "auto", help="babel | analyst | architect | orchestrator | auto"
    ),
    provider: str = typer.Option(
        None, "--provider",
        help="LLM provider override (anthropic | deepseek | ollama). "
        "Applies to every role this invocation; equivalent to exporting "
        "LLM_PROVIDER for this command only.",
    ),
    model: str = typer.Option(
        None, "--model",
        help="Model id override (e.g. claude-opus-4-7). Applies globally "
        "this invocation; per-role env vars still win.",
    ),
) -> None:
    """Move the project forward one or more states (via agent calls)."""
    from ortim.agents import AnalystAgent, ArchitectAgent, OrchestratorAgent
    from ortim.audit import AuditLogger
    from ortim.babel import BabelLayer, StructuredIntent
    from ortim.llm import client_for
    from ortim.memory import MemoryLoader

    # CLI flags layer ABOVE env: setting them here overrides whatever
    # config/.env supplied, but per-role vars (BABEL_PROVIDER etc.) the
    # router consults still take precedence — matches operator intent
    # when they pin a role and override the global with a flag.
    _apply_invocation_overrides(provider=provider, model=model)

    project, store, _ = _resolve_project(project_id)
    _block_if_archived(project, action="run agents")

    memory = MemoryLoader(_globals.ASSETS_ROOT)
    audit = AuditLogger(path=store.audit_log_path())
    workspace = store.metadata_dir

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
            project.save(_globals.WORKSPACE_ROOT)
        else:
            console.print("[yellow]Resuming Babel from BABEL_PROCESSING.[/yellow]")

        console.print("[cyan]Babel:[/cyan] extracting intent...")
        intent = babel.extract(project.initial_brief_tr, project.id)
        intent_path.write_text(intent.model_dump_json(indent=2), encoding="utf-8")
        console.print(f"[green]Intent saved:[/green] {intent_path}")

        console.print("[cyan]Babel:[/cyan] round-trip validation...")
        summary = babel.round_trip(
            intent, project.id, brief=project.initial_brief_tr
        )
        console.print(f"\n[bold]What I understood:[/bold]\n{summary}\n")

        # M2: route through INTAKE_DIALOG when ORTIM_DIALOG_MODE=on
        # (default). Legacy direct-to-PRD_DRAFTING path is preserved for
        # ORTIM_DIALOG_MODE=off + older fixtures.
        from ortim.dialog import (
            append_dialog_turn,
            dialog_mode_on,
            save_intent_md,
        )

        if dialog_mode_on():
            from ortim.agents import IntentAnalyst

            project.transition(
                ProjectState.INTAKE_DIALOG,
                actor="babel-layer",
                note="intent extracted; entering INTAKE_DIALOG",
            )
            project.save(_globals.WORKSPACE_ROOT)

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
            project.save(_globals.WORKSPACE_ROOT)

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

        # Faz 1.1 — legacy (dialog-off) path also lands at MVP_SCOPE_LOCKING,
        # not directly at G1. Seed scope.json so the next-step UX has
        # something for `ortim scope` to render.
        from ortim.scope import save_scope, scope_path, suggest_initial_scope

        if not scope_path(workspace).exists():
            seeded = suggest_initial_scope(
                project_id=project.id,
                must_have_features=intent.must_have_features,
                nice_to_have_features=intent.nice_to_have_features,
            )
            save_scope(workspace, seeded)
            audit.log(
                "scope_seeded",
                project_id=project.id,
                feature_count=len(seeded.features),
                phase_1_count=len(seeded.phase_1_features()),
                deferred_count=len(seeded.deferred_features()),
            )

        project.transition(
            ProjectState.MVP_SCOPE_LOCKING,
            actor="analyst",
            note="PRD drafted; entering scope dialog before G1",
        )
        project.save(_globals.WORKSPACE_ROOT)
        console.print(
            f"\n[yellow]Next:[/yellow] assign a phase to each feature, then proceed to G1:"
        )
        console.print(
            f"  ortim scope {project.id}            "
            "(interactive)\n"
            f"  ortim scope {project.id} --lock     "
            "(skip-edit + advance to G1)"
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
            project.save(_globals.WORKSPACE_ROOT)
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
        from ortim.architecture import GoldenPathInputs
        from ortim.dialog import load_locked_stack

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

            # Faz 1.2 B-5 fix — deterministic override of LLM-inferred
            # app_class when the user's brief explicitly named a non-web
            # framework. Architect Call 1 silently defaults to "web" when
            # the PRD has no mobile/desktop signal even though Babel
            # captured "Flutter" / "Tauri" in user_stack_hints. Proof-point
            # 45ed19809dec: Flutter habit tracker → tier T2 BaaS. After
            # this gate, the same brief should land at M1 (mobile).
            from ortim.architecture import AppClass
            from ortim.babel import app_class_from_hints

            # Hard lock when user passed `--app-class` at init time. No
            # downstream signal (LLM pick, Babel hints) is allowed to flip
            # this — the user made an explicit, durable choice.
            if project.app_class_explicit:
                if gp_inputs.app_class.value != project.app_class:
                    audit.log(
                        "app_class_locked_from_init",
                        project_id=project.id,
                        llm_picked=gp_inputs.app_class.value,
                        locked_value=project.app_class,
                    )
                    console.print(
                        f"[dim]app_class locked at init "
                        f"([cyan]{project.app_class}[/cyan]); LLM pick "
                        f"'{gp_inputs.app_class.value}' ignored.[/dim]"
                    )
                    gp_inputs.app_class = AppClass(project.app_class)
            else:
                # Init-time brief scan already seeded a non-web app_class
                # (e.g. user wrote "mobil uygulama"). Carry it forward when
                # the LLM silently defaulted to web.
                if (
                    project.app_class != "web"
                    and gp_inputs.app_class.value == "web"
                ):
                    audit.log(
                        "app_class_carried_from_init_brief",
                        project_id=project.id,
                        from_init=project.app_class,
                    )
                    console.print(
                        f"[dim]app_class from init brief scan: "
                        f"[cyan]{project.app_class}[/cyan][/dim]"
                    )
                    gp_inputs.app_class = AppClass(project.app_class)

            intent_path = workspace / "intent.json"
            if intent_path.exists():
                try:
                    _intent = StructuredIntent.model_validate_json(
                        intent_path.read_text(encoding="utf-8")
                    )
                    # Faz 1.2 B-1 — forward hints to tier scorer so it can
                    # disqualify T2 BaaS when user named self-hosted infra.
                    gp_inputs.user_stack_hints = list(_intent.user_stack_hints)
                    if not project.app_class_explicit:
                        override = app_class_from_hints(_intent.user_stack_hints)
                        if override and override != gp_inputs.app_class.value:
                            audit.log(
                                "app_class_overridden_from_hints",
                                project_id=project.id,
                                llm_picked=gp_inputs.app_class.value,
                                deterministic_override=override,
                                hints=list(_intent.user_stack_hints),
                            )
                            console.print(
                                f"[yellow]app_class override:[/yellow] LLM said "
                                f"'{gp_inputs.app_class.value}', user hints "
                                f"({', '.join(_intent.user_stack_hints)}) → "
                                f"'{override}'"
                            )
                            gp_inputs.app_class = AppClass(override)
                except Exception:
                    # Best-effort override; never block the chain.
                    pass

            # Mirror the final pick onto the Project so downstream reads
            # (status, audit, etc.) see what was actually used for tier
            # selection — not the init-time guess.
            if project.app_class != gp_inputs.app_class.value:
                project.app_class = gp_inputs.app_class.value
                project.save(_globals.WORKSPACE_ROOT)

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
        # Faz 1.1 — pass the locked scope so RFC §7 can emit a two-tier
        # module table. None for pre-1.1 workspaces or projects that
        # skipped MVP_SCOPE_LOCKING (advance-by-alias path).
        from ortim.scope import load_scope, scope_path

        scope_manifest = (
            load_scope(workspace) if scope_path(workspace).exists() else None
        )

        # Faz 1.2 B-2 — when there's no locked_stack (legacy/dialog-off
        # path), read the user_stack_hints captured by Babel and forward
        # them so the Architect honors user-named tech over tier defaults.
        intent_path = workspace / "intent.json"
        user_hints: list[str] = []
        if locked_stack is None and intent_path.exists():
            try:
                _intent = StructuredIntent.model_validate_json(
                    intent_path.read_text(encoding="utf-8")
                )
                user_hints = list(_intent.user_stack_hints)
            except Exception:
                user_hints = []

        rfc = architect.draft_rfc(
            prd_text,
            tier_score,
            project.name,
            project.id,
            app_class=gp_inputs.app_class.value,
            codebase=codebase_summary,
            locked_stack=locked_stack,
            scope=scope_manifest,
            user_stack_hints=user_hints,
        )
        rfc_path = workspace / "RFC.md"
        rfc_path.write_text(rfc, encoding="utf-8")
        console.print(f"[green]RFC drafted:[/green] {rfc_path}")

        project.transition(
            ProjectState.RFC_AWAITING_APPROVAL,
            actor="architect",
            note=f"tier={tier_score.tier.value}",
        )
        project.save(_globals.WORKSPACE_ROOT)
        console.print(
            f"\n[yellow]HITL Gate G2:[/yellow] review the RFC; to approve, run:"
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
            project.save(_globals.WORKSPACE_ROOT)
        else:
            console.print("[yellow]Resuming Orchestrator from TASKS_GENERATING.[/yellow]")

        try:
            orchestrator_llm = client_for("orchestrator")
        except RuntimeError as e:
            console.print(f"[red]{e}[/red]")
            raise typer.Exit(1)
        orchestrator_agent = OrchestratorAgent(orchestrator_llm, memory, audit)
        console.print("[cyan]Orchestrator:[/cyan] generating task DAG (with retry on validation failure)...")
        # Faz 1.1 — feed scope into Orchestrator so each TaskSpec carries
        # a `phase` field. Falls back to None when scope.json is absent
        # (pre-1.1 or advance-by-alias path); all tasks default to phase=1.
        from ortim.scope import load_scope as _load_scope
        from ortim.scope import scope_path as _scope_path

        orch_scope = (
            _load_scope(workspace) if _scope_path(workspace).exists() else None
        )
        try:
            dag = orchestrator_agent.generate_dag(
                rfc_text, project.id, scope=orch_scope
            )
        except RuntimeError as e:
            console.print(f"[red]{e}[/red]")
            project.transition(
                ProjectState.FAILED, actor="orchestrator", note=str(e)[:200]
            )
            project.save(_globals.WORKSPACE_ROOT)
            raise typer.Exit(1)

        # Faz 1.5 — tag tasks with sensitive categories (auth/pii/payment).
        # The runner consults this list after reviewers approve and gates
        # the merge on human sign-off when any category fires.
        from ortim.security import detect_sensitive_categories

        sensitive_tagged: list[tuple[str, list[str]]] = []
        for task in dag.tasks:
            cats = detect_sensitive_categories(task)
            if cats:
                task.sensitive_categories = cats
                sensitive_tagged.append((task.id, cats))
        if sensitive_tagged:
            audit.log(
                "dag_sensitive_categories_tagged",
                project_id=project.id,
                tagged_count=len(sensitive_tagged),
                tagged=[
                    {"task_id": tid, "categories": cats}
                    for tid, cats in sensitive_tagged
                ],
            )
            console.print(
                f"[yellow]Security gate:[/yellow] {len(sensitive_tagged)} "
                f"task(s) tagged for human review after reviewers pass: "
                + ", ".join(
                    f"{tid}({'/'.join(cats)})" for tid, cats in sensitive_tagged
                )
            )

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
        project.save(_globals.WORKSPACE_ROOT)

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
                f"review the new `## Extension {cycle}` section in RFC.md; "
                "to approve, run:\n"
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

def _dialog_setup(project_id: str | None):
    """Shared bootstrap for the dialog CLI commands: load project,
    workspace, audit, and memory. Returns a tuple of those plus an
    early-exit flag if the state is not a dialog state."""
    from ortim.audit import AuditLogger
    from ortim.memory import MemoryLoader

    project, store, _ = _resolve_project(project_id)
    workspace = store.metadata_dir
    return project, workspace, AuditLogger(path=store.audit_log_path()), MemoryLoader(_globals.ASSETS_ROOT)
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
def refine(
    feedback: str = typer.Argument(
        ..., help="Feedback. E.g. 'add tagging to must-have features'"
    ),
    force: bool = typer.Option(
        False, "--force", help="Deliberately continue past the turn cap."
    ),
    project_id: str = typer.Option(
        None,
        "--project",
        "-p",
        help="Workspace ID (pool legacy). If omitted, discovered from cwd.",
    ),
) -> None:
    """Re-invoke the active dialog state's agent with feedback."""
    from ortim.babel import StructuredIntent
    from ortim.dialog import (
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
    from ortim.llm import client_for

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
        from ortim.agents import IntentAnalyst

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
        from ortim.agents import StackAnalyst
        from ortim.architecture import GoldenPathInputs, select_tier

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
        from ortim.agents import PRDAnalyst

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
def show(
    project_id: str = typer.Argument(
        None,
        help="Workspace ID. If omitted, discovered from cwd.",
    ),
    artifact: str = typer.Option(
        "current",
        "--artifact",
        "-a",
        help="intent | stack | prd | scope | current",
    ),
) -> None:
    """Print the active (or selected) dialog artifact to the console."""
    from ortim.dialog import load_intent_md, load_locked_stack, load_prd_md

    project, store, _ = _resolve_project(project_id)
    workspace = store.metadata_dir

    requested = artifact.lower()
    if requested == "current":
        if project.state == ProjectState.INTAKE_DIALOG:
            requested = "intent"
        elif project.state == ProjectState.STACK_DIALOG:
            requested = "stack"
        elif project.state == ProjectState.PRD_DIALOG:
            requested = "prd"
        elif project.state == ProjectState.MVP_SCOPE_LOCKING:
            requested = "scope"
        else:
            console.print(
                f"[yellow]Project is in '{project.state.value}', not a dialog "
                "state. Pass --artifact intent|stack|prd|scope explicitly.[/yellow]"
            )
            raise typer.Exit(1)

    if requested == "intent":
        md = load_intent_md(workspace)
    elif requested == "stack":
        stack = load_locked_stack(workspace)
        md = stack.to_markdown() if stack is not None else None
    elif requested == "prd":
        md = load_prd_md(workspace)
    elif requested == "scope":
        from ortim.scope import load_scope, scope_path

        if not scope_path(workspace).exists():
            md = None
        else:
            md = load_scope(workspace).to_markdown()
    else:
        console.print(f"[red]Unknown artifact '{artifact}'[/red]")
        raise typer.Exit(1)

    if md is None:
        console.print(f"[yellow]No {requested}.md yet for {project.id}.[/yellow]")
        raise typer.Exit(1)
    console.print(md)
def lock(
    project_id: str = typer.Argument(
        None,
        help="Workspace ID. If omitted, discovered from cwd.",
    ),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation prompts."),
) -> None:
    """Lock the active dialog state and move to the next. Show a diff, confirm,
    and generate the next state's first draft (if any)."""
    import difflib

    from rich.panel import Panel

    from ortim.dialog import (
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
    from ortim.agents import ArchitectAgent, StackAnalyst
    from ortim.dialog import (
        append_dialog_turn,
        load_intent_md,
        save_locked_stack,
    )
    from ortim.llm import client_for

    intent_md = load_intent_md(workspace)
    if intent_md is None:
        console.print("[red]intent.md missing — cannot advance.[/red]")
        raise typer.Exit(1)

    project.transition(
        ProjectState.STACK_DIALOG,
        actor="lock",
        note="intent locked; entering stack dialog",
    )
    project.save(_globals.WORKSPACE_ROOT)

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
    from ortim.agents import PRDAnalyst
    from ortim.dialog import (
        append_dialog_turn,
        load_intent_md,
        load_locked_stack,
        save_prd_md,
    )
    from ortim.llm import client_for

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
    project.save(_globals.WORKSPACE_ROOT)

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
    from ortim.architecture import LockedStack
    from ortim.babel import BabelLayer
    from ortim.extend import (
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
    project.save(_globals.WORKSPACE_ROOT)

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
    project.save(_globals.WORKSPACE_ROOT)
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
    from ortim.architecture import LockedStack
    from ortim.extend import (
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
    project.save(_globals.WORKSPACE_ROOT)

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
    project.save(_globals.WORKSPACE_ROOT)
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
    from ortim.agents import OrchestratorAgent
    from ortim.extend import (
        DagDelta,
        section_cycles_in,
    )
    from ortim.orchestrator import TaskDAG

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
    project.save(_globals.WORKSPACE_ROOT)

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
        project.save(_globals.WORKSPACE_ROOT)
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
    project.save(_globals.WORKSPACE_ROOT)
    return cycle, len(delta_dag.tasks)
def _list_extensions(workspace: Path) -> list[tuple[int, str]]:
    """Return [(cycle, header_line), ...] for every extension in PRD.md.
    `header_line` is the full `## Extension N — Title` line as it appears
    in the file. Used by `ortim extensions <id>` for the table render."""
    from ortim.extend import section_cycles_in

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
def extend_cmd(
    brief: str = typer.Argument(..., help="Brief for the new feature (any language)"),
    project_id: str = typer.Option(
        None,
        "--project",
        "-p",
        help="Workspace ID (pool legacy). If omitted, discovered from cwd.",
    ),
) -> None:
    """M3.1 — Add a new feature delta to a DONE project.

    The project must be in the DONE state. Runs Babel + ExtenderAgent,
    appends an `## Extension <N>` section to PRD.md, and stops at the
    G1 (cycle N) HITL gate. If ExtenderAgent emits a BLOCKED-STACK
    marker, no section is written and the user is informed."""
    from ortim.audit import AuditLogger
    from ortim.llm import client_for
    from ortim.memory import MemoryLoader

    project, store, _ = _resolve_project(project_id)
    _block_if_archived(project, action="extend")

    if project.state != ProjectState.DONE:
        console.print(
            f"[red]extend requires DONE state; project is "
            f"{project.state.value}[/red]"
        )
        raise typer.Exit(1)

    memory = MemoryLoader(_globals.ASSETS_ROOT)
    audit = AuditLogger(path=store.audit_log_path())
    workspace = store.metadata_dir

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
        f"review the new `## Extension {cycle}` section in PRD.md; "
        "to approve, run:\n"
        f"  [cyan]ortim advance {project.id} extend_prd_approved "
        "--note 'reviewed'[/cyan]"
    )
def extensions_cmd(
    project_id: str = typer.Argument(
        None,
        help="Workspace ID. If omitted, discovered from cwd.",
    ),
) -> None:
    """M3.1 — List the project's extend-cycle history (reads PRD.md)."""
    project, store, _ = _resolve_project(project_id)
    rows = _list_extensions(store.metadata_dir)
    if not rows:
        console.print(
            f"No extensions yet for [bold]{project.id}[/bold]. Use "
            f"[cyan]ortim extend \"<feature brief>\"[/cyan] "
            "to add one (project must be DONE)."
        )
        return

    table = Table(title=f"Extensions for {project.id}")
    table.add_column("Cycle", style="cyan")
    table.add_column("Header line")
    for cycle, header in rows:
        table.add_row(str(cycle), header)
    console.print(table)
def _lock_prd(project, workspace, audit, memory) -> None:
    """PRD_DIALOG → MVP_SCOPE_LOCKING. Faz 1.1: PRD draft is locked but
    G1 is not yet open; the user must first walk each feature through
    `ortim scope <id>` and assign a phase. `_lock_prd` seeds scope.json
    from the StructuredIntent feature lists so the scope command has
    something to show on first invocation."""
    from ortim.babel import StructuredIntent
    from ortim.scope import save_scope, scope_path, suggest_initial_scope

    intent_path = workspace / "intent.json"
    if not intent_path.exists():
        console.print(
            f"[red]intent.json missing at {intent_path} — cannot seed scope.[/red]"
        )
        raise typer.Exit(1)

    # Seed scope.json only on the first PRD lock — re-locks preserve the
    # user's edits. Re-seeding would silently overwrite phase assignments.
    if not scope_path(workspace).exists():
        try:
            structured = StructuredIntent.model_validate_json(
                intent_path.read_text(encoding="utf-8")
            )
            seeded = suggest_initial_scope(
                project_id=project.id,
                must_have_features=structured.must_have_features,
                nice_to_have_features=structured.nice_to_have_features,
            )
        except Exception:
            # Brownfield stub intent.json (no must_have_features) — seed
            # an empty scope; user adds features manually via `ortim scope`.
            from ortim.scope import ScopeManifest

            seeded = ScopeManifest(project_id=project.id, features=[])
        save_scope(workspace, seeded)
        audit.log(
            "scope_seeded",
            project_id=project.id,
            feature_count=len(seeded.features),
            phase_1_count=len(seeded.phase_1_features()),
            deferred_count=len(seeded.deferred_features()),
        )

    project.transition(
        ProjectState.MVP_SCOPE_LOCKING,
        actor="lock",
        note="PRD locked; entering scope dialog before G1",
    )
    project.save(_globals.WORKSPACE_ROOT)
    audit.log(
        "dialog_lock",
        project_id=project.id,
        from_state=ProjectState.PRD_DIALOG.value,
        to_state=ProjectState.MVP_SCOPE_LOCKING.value,
    )
    console.print(
        f"[green]PRD locked.[/green] State: "
        f"[cyan]{project.state.value}[/cyan]\n"
        f"\n[yellow]Next:[/yellow] assign a phase to each feature, then proceed to G1:\n"
        f"  [cyan]ortim scope {project.id}[/cyan]"
    )
def scope(
    project_id: str = typer.Argument(
        None,
        help="Workspace ID. If omitted, discovered from cwd.",
    ),
    show: bool = typer.Option(
        False, "--show", help="Only show the current scope.json as a table; no editing."
    ),
    lock_now: bool = typer.Option(
        False, "--lock", help="Skip interactive editing; lock the current scope and proceed to G1."
    ),
    reset: bool = typer.Option(
        False, "--reset", help="Re-seed scope.json from intent.json (user edits are discarded)."
    ),
    set_phase: list[str] = typer.Option(
        None,
        "--set",
        help="Non-interactive phase assignment: --set '<feature substring>=<phase>'. Repeatable.",
    ),
) -> None:
    """Phase 1.1 — MVP scope locking. Assign a phase + priority to each feature.

    Workflow:
      1. `ortim lock` → state moves to MVP_SCOPE_LOCKING; scope.json is seeded
      2. `ortim scope <id>` → show the table + prompt a phase for each feature
      3. `ortim scope <id> --lock` → scope locks, proceed to G1

    Headless (CI or power users):
      ortim scope <id> --set "auth=1" --set "social login=2" --lock
    """
    from ortim.scope import load_scope, save_scope, scope_path, suggest_initial_scope

    project, store, _ = _resolve_project(project_id)
    workspace = store.metadata_dir

    if project.state != ProjectState.MVP_SCOPE_LOCKING:
        console.print(
            f"[red]Project is in '{project.state.value}', not MVP_SCOPE_LOCKING.[/red]\n"
            "Run `ortim lock <id>` from PRD_DIALOG first, or `ortim advance "
            f"{project.id} mvp_scope_locking` if you've already passed G1."
        )
        raise typer.Exit(1)

    sp = scope_path(workspace)

    if reset:
        from ortim.babel import StructuredIntent

        intent_path = workspace / "intent.json"
        if not intent_path.exists():
            console.print("[red]intent.json missing — cannot reset.[/red]")
            raise typer.Exit(1)
        structured = StructuredIntent.model_validate_json(
            intent_path.read_text(encoding="utf-8")
        )
        manifest = suggest_initial_scope(
            project_id=project.id,
            must_have_features=structured.must_have_features,
            nice_to_have_features=structured.nice_to_have_features,
        )
        save_scope(workspace, manifest)
        console.print("[green]scope.json reset from intent.json[/green]")
    else:
        if not sp.exists():
            console.print(
                f"[red]scope.json missing at {sp}.[/red]\n"
                "Re-run `ortim lock` from PRD_DIALOG to seed it, or pass --reset."
            )
            raise typer.Exit(1)
        manifest = load_scope(workspace)

    # Render the current scope as a table.
    table = Table(title=f"Scope — {project.id}")
    table.add_column("#", style="dim", width=3)
    table.add_column("Phase", style="cyan", width=5)
    table.add_column("Priority", width=8)
    table.add_column("Source", style="dim", width=7)
    table.add_column("Description")
    for i, f in enumerate(manifest.features, 1):
        table.add_row(str(i), str(f.phase), f.priority, f.source, f.description)
    console.print(table)

    if show:
        return

    # Non-interactive --set assignments (CI / power-user mode).
    if set_phase:
        for spec in set_phase:
            if "=" not in spec:
                console.print(
                    f"[red]--set expects '<substring>=<phase>', got '{spec}'.[/red]"
                )
                raise typer.Exit(1)
            substr, phase_str = spec.rsplit("=", 1)
            try:
                new_phase = int(phase_str.strip())
            except ValueError:
                console.print(f"[red]Phase must be int, got '{phase_str}'.[/red]")
                raise typer.Exit(1)
            substr_l = substr.strip().lower()
            matched = 0
            for f in manifest.features:
                if substr_l in f.description.lower():
                    f.phase = new_phase
                    f.priority = "must" if new_phase == 1 else "later"
                    matched += 1
            if matched == 0:
                console.print(
                    f"[yellow]--set '{substr}': no feature matched (skipped).[/yellow]"
                )
            else:
                console.print(
                    f"[green]--set '{substr}' → phase {new_phase} "
                    f"({matched} feature matched)[/green]"
                )
        save_scope(workspace, manifest)

    # Interactive phase prompt (skipped when --lock or --set is supplied).
    elif not lock_now:
        console.print(
            "\n[bold]Enter a phase for each feature (1=MVP, 2+=later). "
            "Enter = keep the current value.[/bold]\n"
        )
        for f in manifest.features:
            prompt = (
                f"  '{f.description}' [phase={f.phase}]: "
            )
            raw = typer.prompt(prompt, default=str(f.phase), show_default=False)
            try:
                new_phase = int(raw.strip())
            except ValueError:
                console.print(f"[red]'{raw}' is not an integer — skipped.[/red]")
                continue
            if new_phase < 1:
                console.print("[red]phase must be >= 1 — skipped.[/red]")
                continue
            f.phase = new_phase
            f.priority = "must" if new_phase == 1 else "later"
        save_scope(workspace, manifest)
        console.print(f"\n[green]scope.json saved.[/green]")
        # Re-render so user sees the final assignments.
        table2 = Table(title="Updated scope")
        table2.add_column("Phase", style="cyan", width=5)
        table2.add_column("Description")
        for f in manifest.features:
            table2.add_row(str(f.phase), f.description)
        console.print(table2)

    # Optional advance to G1.
    should_lock = lock_now
    if not should_lock and not show:
        should_lock = typer.confirm(
            "\nLock the scope and proceed to G1 (PRD review)?", default=True
        )

    if should_lock:
        from ortim.audit import AuditLogger

        manifest.lock()
        save_scope(workspace, manifest)
        project.transition(
            ProjectState.PRD_AWAITING_APPROVAL,
            actor="scope-lock",
            note=f"scope locked at {manifest.locked_at}",
        )
        project.save(_globals.WORKSPACE_ROOT)
        AuditLogger().log(
            "scope_locked",
            project_id=project.id,
            phase_1_count=len(manifest.phase_1_features()),
            deferred_count=len(manifest.deferred_features()),
            max_phase=manifest.max_phase(),
        )
        console.print(
            f"\n[green]Scope locked.[/green] State: "
            f"[cyan]{project.state.value}[/cyan]\n"
            f"\n[yellow]HITL Gate G1:[/yellow] review the PRD; to approve, run:\n"
            f"  [cyan]ortim advance {project.id} prd_approved --note 'reviewed'[/cyan]"
        )


def register(app: typer.Typer) -> None:
    """Wire planning-module commands onto the top-level Typer app."""
    app.command()(advance)
    app.command()(gates)
    app.command()(states)
    app.command()(run)
    app.command()(refine)
    app.command()(show)
    app.command()(lock)
    app.command("extend")(extend_cmd)
    app.command("extensions")(extensions_cmd)
    app.command()(scope)
