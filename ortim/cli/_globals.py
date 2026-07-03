# SPDX-License-Identifier: FSL-1.1-Apache-2.0
# Copyright (c) 2026 ortim.dev
"""Shared globals and helpers used across all CLI modules.

All CLI modules import from here rather than from main.py so that
REPO_ROOT, WORKSPACE_ROOT, console, and shared helpers remain
in a single, testable location.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import typer
from rich.console import Console

from ortim.env import env_get
from ortim.orchestrator import InvalidTransition, Project, ProjectState

# ---------------------------------------------------------------------------
# Global singletons
# ---------------------------------------------------------------------------

WORKSPACE_ROOT = Path(os.getenv("WORKSPACE_ROOT", "./workspaces"))

# Two separate concepts, previously conflated as REPO_ROOT:
#
#   ASSETS_ROOT — where bundled markdown assets live (agents/, skills/,
#     principles/, glossary/, golden-paths/). Always resolves to a
#     directory inside the installed wheel (`<ortim>/_assets/`), which
#     is also the location in the source repo when editable-installed.
#     This is the path MemoryLoader / load_all_skills / doctor checks read.
#
#   REPO_ROOT — repository / project root, used for things written or
#     read relative to the operator's working tree (audit logs, tier
#     bootstrap scripts, repo-rooted helpers). For PyPI installs this
#     resolves to `site-packages/` which is rarely meaningful — callers
#     should prefer ASSETS_ROOT when they want bundled data, and the
#     user's cwd / WORKSPACE_ROOT for their own files.
#
# ORTIM_REPO_ROOT env var still overrides REPO_ROOT for legacy setups.
from ortim import ASSETS_ROOT  # noqa: E402  (re-export so CLI imports stay terse)

REPO_ROOT = (
    Path(os.getenv("ORTIM_REPO_ROOT", "")).resolve()
    if os.getenv("ORTIM_REPO_ROOT")
    else Path(__file__).resolve().parent.parent.parent  # cli/ → ortim/ → repo root
)

console = Console()

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _ensure_workspace_root() -> None:
    WORKSPACE_ROOT.mkdir(parents=True, exist_ok=True)


# State → the single most useful next command, printed as a trailing
# "Next:" line by run/show/status/advance. Templates take `{id}`.
# Transient states (babel_processing, prd_drafting, ...) map to `run`
# because re-running resumes them; terminal FAILED points at triage.
_NEXT_ACTIONS: dict[ProjectState, tuple[str, str]] = {
    ProjectState.INTAKE: ("ortim run {id}", "start the pipeline (Babel intake)"),
    ProjectState.BABEL_PROCESSING: ("ortim run {id}", "resume Babel"),
    ProjectState.INTAKE_DIALOG: (
        "ortim lock {id}",
        'lock the intent — or iterate: ortim refine "<feedback>" -p {id}',
    ),
    ProjectState.STACK_DIALOG: (
        "ortim lock {id}",
        'lock the stack — or iterate: ortim refine "<feedback>" -p {id}',
    ),
    ProjectState.PRD_DIALOG: (
        "ortim lock {id}",
        'lock the PRD draft — or iterate: ortim refine "<feedback>" -p {id}',
    ),
    ProjectState.PRD_DRAFTING: ("ortim run {id}", "resume PRD drafting"),
    ProjectState.MVP_SCOPE_LOCKING: (
        "ortim scope {id} --lock",
        "review + lock the MVP phase split",
    ),
    ProjectState.PRD_AWAITING_APPROVAL: (
        "ortim advance prd_approved -p {id} --note 'reviewed'",
        "G1 — approve after reading PRD.md",
    ),
    ProjectState.PRD_APPROVED: ("ortim run {id}", "Architect drafts the RFC"),
    ProjectState.RFC_DRAFTING: ("ortim run {id}", "resume RFC drafting"),
    ProjectState.RFC_AWAITING_APPROVAL: (
        "ortim advance rfc_approved -p {id} --note 'reviewed'",
        "G2 — approve after reading RFC.md",
    ),
    ProjectState.RFC_APPROVED: ("ortim run {id}", "Orchestrator generates the task DAG"),
    ProjectState.TASKS_GENERATING: ("ortim run {id}", "resume DAG generation"),
    ProjectState.TASKS_READY: (
        "ortim run-all {id}",
        "execute every task — or inspect first: ortim tasks {id}",
    ),
    ProjectState.SCHEMA_AWAITING_APPROVAL: (
        "ortim advance schema_approved -p {id}",
        "G3 — approve the schema/migration plan",
    ),
    ProjectState.EXECUTING: (
        "ortim run-all {id}",
        "continue executing remaining tasks — progress: ortim tasks {id}",
    ),
    ProjectState.BUDGET_AWAITING_APPROVAL: (
        "ortim advance budget_approved -p {id}",
        "G7 — accept the overage / raise the cap",
    ),
    ProjectState.DEPLOY_AWAITING_APPROVAL: (
        "ortim advance deploy_approved -p {id}",
        "G6 — approve the deploy",
    ),
    ProjectState.DONE: (
        "ortim retro {id}",
        'cost + token rollup — or keep building: ortim extend {id} "<brief>"',
    ),
    ProjectState.FAILED: (
        "ortim status {id}",
        "inspect history; see docs/runbook/failure-recovery.md",
    ),
    ProjectState.PAUSED: (
        "ortim advance <state> -p {id}",
        "resume — legal targets: ortim states",
    ),
    ProjectState.EXTEND_DIALOG: (
        "ortim lock {id}",
        'lock the extension intent — or iterate: ortim refine "<feedback>" -p {id}',
    ),
    ProjectState.EXTEND_PRD_DIALOG: (
        "ortim lock {id}",
        'lock the extension PRD — or iterate: ortim refine "<feedback>" -p {id}',
    ),
    ProjectState.EXTEND_PRD_AWAITING_APPROVAL: (
        "ortim advance extend_prd_approved -p {id} --note 'reviewed'",
        "G1 (extension) — approve the delta PRD",
    ),
    ProjectState.EXTEND_PRD_APPROVED: ("ortim run {id}", "draft the delta RFC"),
    ProjectState.EXTEND_RFC_DRAFTING: ("ortim run {id}", "resume delta RFC drafting"),
    ProjectState.EXTEND_RFC_AWAITING_APPROVAL: (
        "ortim advance extend_rfc_approved -p {id} --note 'reviewed'",
        "G2 (extension) — approve the delta RFC",
    ),
    ProjectState.EXTEND_RFC_APPROVED: (
        "ortim run {id}",
        "generate the extension task DAG",
    ),
}


def _print_next_action(project: "Project") -> None:
    """Print a single "Next: <command>" hint for the project's state.

    The state machine already knows the legal next steps; this surfaces
    the most useful one so no command output leaves the operator at a
    dead end. Silent for states with no mapping.
    """
    action = _NEXT_ACTIONS.get(project.state)
    if action is None:
        return
    command, why = action
    console.print(
        f"[bold]Next:[/bold] [cyan]{command.format(id=project.id)}[/cyan]"
        f"[dim] — {why.format(id=project.id)}[/dim]"
    )


def _resolve_project(arg: str | None):
    """Resolve a workspace + load its Project for a CLI command.

    Returns `(project, store, location)`. Side effect: sets
    `AUDIT_LOG_PATH` env var to the resolved per-workspace audit log so
    downstream `AuditLogger()` constructions (in helpers, agents, hooks)
    automatically write to the right place — no need to thread an audit
    instance through every internal function.

    Resolution order:
      1. If `arg` is given AND `<WORKSPACE_ROOT>/<arg>/state.json` exists →
         load as pool-mode legacy workspace (backward-compat for existing
         tests + scripts that pass UUID-style ids).
      2. Else delegate to `resolve_workspace(arg, cwd)` — cwd parent walk
         for project-mode, registry lookup for explicit args.

    Exits cleanly (typer.Exit) with a friendly message on resolution
    failure or missing state.json — the caller can assume a valid Project.
    """
    from ortim.workspace import (
        ProjectStore,
        WorkspaceLocation,
        WorkspaceMode,
        WorkspaceNotFound,
        resolve_workspace,
    )

    if arg is not None:
        pool_candidate = WORKSPACE_ROOT / arg
        if (pool_candidate / "state.json").exists():
            location = WorkspaceLocation(
                path=pool_candidate, mode=WorkspaceMode.POOL, id=arg
            )
            store = ProjectStore(location)
            project = store.load()
            os.environ["AUDIT_LOG_PATH"] = str(store.audit_log_path())
            return project, store, location

    try:
        location = resolve_workspace(arg=arg)
    except WorkspaceNotFound as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1)

    store = ProjectStore(location)
    try:
        project = store.load()
    except FileNotFoundError:
        console.print(
            f"[red]Workspace state not found at {location.state_file}[/red]"
        )
        raise typer.Exit(1)
    os.environ["AUDIT_LOG_PATH"] = str(store.audit_log_path())
    return project, store, location


def _apply_invocation_overrides(
    provider: str | None = None,
    model: str | None = None,
) -> None:
    """Promote `--provider`/`--model` flags into env for this process."""
    if provider:
        os.environ["LLM_PROVIDER"] = provider.strip().lower()
    if model:
        os.environ["DEFAULT_MODEL"] = model.strip()


def _block_if_archived(project, action: str = "modify") -> None:
    """Refuse mutating actions on archived workspaces."""
    if project.archived_at is not None:
        console.print(
            f"[red]Workspace {project.id} is archived "
            f"(at {project.archived_at[:19]}).[/red]\n"
            f"Cannot {action}. Run "
            f"[cyan]ortim workspace unarchive {project.id}[/cyan] first."
        )
        raise typer.Exit(1)


def _load_codebase_summary(project: "Project", workspace: Path):
    """Load the cached codebase summary for a brownfield project, or None."""
    if not project.is_brownfield:
        return None
    cache = workspace / ".cache" / "codebase.json"
    if not cache.exists():
        return None
    from ortim.codebase import CodebaseSummary

    try:
        return CodebaseSummary.model_validate_json(cache.read_text(encoding="utf-8"))
    except Exception:
        return None
