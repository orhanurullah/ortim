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

# ORTIM_REPO_ROOT: PyPI kurulumunda `agents/`, `docs/`, `skills/` dizinlerinin
# nerede aranacağını belirler. Dev kurulumda gerek yok — __file__.parent.parent
# zaten repo kökünü gösterir. PyPI kurulumunda `site-packages/ortim/main.py`
# olduğundan parent.parent = site-packages → yanlış. Kullanıcı .env'e
# `ORTIM_REPO_ROOT=<repo_yolu>` yazarak override edebilir.
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
