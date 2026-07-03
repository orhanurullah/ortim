"""CLI: workspace commands — init, new, ls, use + workspace/* subcommands."""

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
    _ensure_workspace_root, _load_codebase_summary, _print_next_action,
    _resolve_project,
)
from ortim.env import env_get
from ortim.orchestrator import InvalidTransition, Project, ProjectState

workspace_app = typer.Typer(
    help="Workspace lifecycle: list, archive, cleanup, migrate, doctor.",
    no_args_is_help=True,
)

def init(
    brief: str = typer.Argument(..., help="Project brief (any language)"),
    name: str = typer.Option(
        None,
        "--name",
        help="Short project name (default: cwd directory name).",
    ),
    greenfield: bool = typer.Option(
        False,
        "--greenfield",
        help="Force-skip brownfield auto-detection (treat as an empty directory).",
    ),
    brownfield: bool = typer.Option(
        False,
        "--brownfield",
        help="Force brownfield mode (scan the codebase even without a manifest file).",
    ),
    app_class: str = typer.Option(
        None,
        "--app-class",
        help=(
            "Lock the app class up front: web|mobile|desktop. If set, "
            "Babel/LLM hints cannot change it later. If unset, the brief "
            "text is scanned for terms like 'mobile app', 'Android', "
            "'desktop' (Babel may still override later)."
        ),
    ),
) -> None:
    """Initialize an Ortim project in the current directory (creates .ortim/).

    If a manifest file (package.json, pyproject.toml, Cargo.toml, ...) exists,
    brownfield mode is selected automatically; otherwise greenfield. Use
    --greenfield or --brownfield to override manually.

    First: `cd ~/dev/todo-app && ortim init "task manager"`
    Then: `ortim status`, `ortim run`, `ortim run-all` — all discover from cwd.
    """
    from ortim.workspace import InitError, init_project

    if greenfield and brownfield:
        console.print(
            "[red]--greenfield and --brownfield cannot be used together.[/red]"
        )
        raise typer.Exit(1)

    if app_class is not None:
        app_class = app_class.lower().strip()
        if app_class not in ("web", "mobile", "desktop"):
            console.print(
                "[red]--app-class must be one of: web, mobile, desktop "
                f"(got '{app_class}').[/red]"
            )
            raise typer.Exit(1)

    force = True if brownfield else (False if greenfield else None)
    cwd = Path.cwd()

    try:
        project, location, is_brownfield = init_project(
            cwd=cwd,
            brief=brief,
            name=name,
            force_brownfield=force,
            app_class_override=app_class,
        )
    except InitError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)

    from ortim.audit import AuditLogger
    from ortim.workspace import register_workspace

    audit = AuditLogger(path=location.metadata_dir / "audit.jsonl")
    audit.log(
        "project_init",
        project_id=project.id,
        name=project.name,
        is_brownfield=is_brownfield,
        app_class=project.app_class,
        app_class_explicit=project.app_class_explicit,
        path=str(location.path),
    )

    # Register in user-level index so `ortim ls` and arg-based lookups find
    # this workspace from anywhere. Also marks it as `current`. The init
    # location carries no id (resolver doesn't know it yet); we substitute
    # the project's freshly-minted id so the entry is keyed correctly.
    from ortim.workspace import WorkspaceLocation as _WL

    register_workspace(
        _WL(path=location.path, mode=location.mode, id=project.id),
        name=project.name,
        state=project.state.value,
    )

    mode_label = "brownfield" if is_brownfield else "greenfield"
    console.print(
        f"[green]Initialized[/green] [bold]{project.id}[/bold] "
        f"([cyan]{project.name}[/cyan], {mode_label})"
    )
    console.print(f"Path: [cyan]{location.path}[/cyan]")
    console.print(f"State: [cyan]{project.state.value}[/cyan]")
    lock_suffix = " [dim](locked)[/dim]" if project.app_class_explicit else ""
    console.print(
        f"App class: [cyan]{project.app_class}[/cyan]{lock_suffix}"
    )
    if is_brownfield:
        console.print(
            f"\nNext: [cyan]ortim run[/cyan] (Architect skips Babel, "
            "drafts PRD from existing code)."
        )
    else:
        console.print(
            "\nNext: [cyan]ortim run[/cyan] "
            "(Babel + Analyst; requires ANTHROPIC_API_KEY or DEEPSEEK_API_KEY)"
        )
def new(
    brief: str = typer.Argument(..., help="Project brief (any language)"),
    name: str = typer.Option("untitled", help="Short project name"),
    from_existing: Path = typer.Option(
        None,
        "--from-existing",
        help="Brownfield: existing project directory. Babel is skipped; the codebase is scanned.",
    ),
    link_mode: str = typer.Option(
        "symlink",
        help="For --from-existing: symlink (fast, requires dev mode) or copy",
    ),
) -> None:
    """[DEPRECATED] Create a new project in the pool layout. Use `ortim init`."""
    print(
        "WARNING: `ortim new` is deprecated; use `ortim init \"<brief>\"` from "
        "inside your project directory. Pool layout will be removed in v1.0.",
        file=sys.stderr,
    )
    _ensure_workspace_root()

    if from_existing is not None:
        try:
            project, mode = bootstrap_brownfield(
                name=name,
                brief_tr=brief,
                source_path=from_existing,
                workspace_root=_globals.WORKSPACE_ROOT,
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
            f"Workspace: {project.workspace_path(project.id, _globals.WORKSPACE_ROOT)}"
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
    project.save(_globals.WORKSPACE_ROOT)
    console.print(f"[green]Created[/green] [bold]{project.id}[/bold] ({name})")
    console.print(f"State: [cyan]{project.state.value}[/cyan]")
    console.print(f"Workspace: {project.workspace_path(project.id, _globals.WORKSPACE_ROOT)}")
    console.print(
        f"\nNext: [cyan]ortim run {project.id}[/cyan] "
        "(Babel + Analyst, requires ANTHROPIC_API_KEY)"
    )
def status(
    project_id: str = typer.Argument(
        None,
        help="Workspace ID. If omitted, discovered from cwd (project mode).",
    ),
) -> None:
    """Show project details (discovered from cwd when no arg is given)."""
    project, _, location = _resolve_project(project_id)

    table = Table(title=f"Project {project.id}")
    table.add_column("Field", style="cyan")
    table.add_column("Value")
    table.add_row("Name", project.name)
    table.add_row("State", project.state.value)
    table.add_row("Path", str(location.path))
    table.add_row("Mode", location.mode.value)
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
    _print_next_action(project)
def inspect(
    project_id: str = typer.Argument(
        None,
        help="Workspace ID. If omitted, discovered from cwd.",
    ),
) -> None:
    """Show the brownfield project's codebase scan summary."""
    project, store, _ = _resolve_project(project_id)
    if not project.is_brownfield:
        console.print(
            f"[yellow]{project.id} is not a brownfield project (no codebase scan).[/yellow]"
        )
        return

    cache = store.metadata_dir / ".cache" / "codebase.json"
    if not cache.exists():
        console.print(
            f"[yellow]No codebase.json at {cache}. Try `ortim rescan`.[/yellow]"
        )
        raise typer.Exit(1)

    from ortim.codebase import CodebaseSummary

    summary = CodebaseSummary.model_validate_json(cache.read_text(encoding="utf-8"))
    table = Table(title=f"Codebase summary — {project.id}")
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
def rescan(
    project_id: str = typer.Argument(
        None,
        help="Workspace ID. If omitted, discovered from cwd.",
    ),
) -> None:
    """Re-scan the brownfield project's codebase summary."""
    from ortim.codebase import scan_codebase
    from ortim.workspace import WorkspaceMode

    project, store, location = _resolve_project(project_id)
    if not project.is_brownfield:
        console.print(
            f"[yellow]{project.id} is not a brownfield project; nothing to rescan.[/yellow]"
        )
        raise typer.Exit(1)

    # Pool layout puts the user's code in `<workspace>/source/`; project
    # mode has it at the workspace root itself. Picking the right scan
    # target keeps the two layouts on the same rescan flow.
    if location.mode is WorkspaceMode.PROJECT:
        source = location.path
    else:
        source = location.path / "source"

    cache_dir = store.metadata_dir / ".cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_path = cache_dir / "codebase.json"
    summary = scan_codebase(source, cache_path=cache_path)
    cache_path.write_text(summary.model_dump_json(indent=2), encoding="utf-8")
    console.print(
        f"[green]Rescanned[/green] {summary.file_count} files; "
        f"app_class hint: [cyan]{summary.app_class_hint or 'unknown'}[/cyan]"
    )
def baseline(
    project_id: str = typer.Argument(
        None,
        help="Workspace ID. If omitted, discovered from cwd.",
    ),
    recapture: bool = typer.Option(False, "--recapture", help="Re-run the test suite"),
    override: int = typer.Option(
        -1, "--override", help="Manual passing-count override (when the parser falls short)"
    ),
) -> None:
    """Show or recapture the brownfield project's test baseline."""
    from ortim.codebase import (
        TestBaseline,
        capture_baseline,
        load_baseline,
        write_baseline,
    )
    from ortim.workspace import WorkspaceMode

    project, store, location = _resolve_project(project_id)
    if not project.is_brownfield:
        console.print(f"[yellow]{project.id} is not a brownfield project.[/yellow]")
        raise typer.Exit(1)

    if location.mode is WorkspaceMode.PROJECT:
        source = location.path
    else:
        source = location.path / "source"
    cache_dir = store.metadata_dir / ".cache"

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
    table = Table(title=f"Baseline — {project.id}")
    table.add_column("Field", style="cyan")
    table.add_column("Value")
    table.add_row("Cmd", existing.cmd)
    table.add_row("Captured at", existing.captured_at)
    table.add_row("Passing", str(existing.passing))
    table.add_row("Skipped", str(existing.skipped))
    table.add_row("Failed", str(existing.failed))
    console.print(table)
def _list_pool_projects() -> list[Project]:
    """Scan WORKSPACE_ROOT for pool-mode workspaces. Used by `ls` until M5
    introduces the registry-backed lookup."""
    projects: list[Project] = []
    if not _globals.WORKSPACE_ROOT.exists():
        return projects
    for path in _globals.WORKSPACE_ROOT.iterdir():
        if not path.is_dir():
            continue
        if not (path / "state.json").exists():
            continue
        try:
            projects.append(Project.load(path.name, _globals.WORKSPACE_ROOT))
        except Exception as e:
            console.print(f"[red]Failed to load {path.name}:[/red] {e}")
    return projects
def ls(
    prune: bool = typer.Option(
        False,
        "--prune",
        help="Remove deleted workspace entries from the registry.",
    ),
    include_pool: bool = typer.Option(
        True,
        "--include-pool/--no-pool",
        help="Also list unregistered workspaces in the pool layout.",
    ),
    include_archived: bool = typer.Option(
        False,
        "--include-archived/--no-archived",
        help="Also show archived workspaces (default: hidden).",
    ),
) -> None:
    """List all known workspaces (registry + pool layout).

    Source: `~/.ortim/registry.json` (project-mode entries) + optional
    `WORKSPACE_ROOT/` scan (pool legacy). The active workspace is marked
    with `*`.
    """
    from ortim.workspace import Registry, scan_pool_workspaces

    reg = Registry.load()

    if prune:
        removed = reg.prune_missing()
        if removed:
            reg.save()
            console.print(
                f"[yellow]Pruned {len(removed)} stale entrie(s):[/yellow] "
                + ", ".join(removed)
            )

    # Pool workspaces that are NOT in the registry (legacy untracked).
    pool_ids_in_registry = {
        e.id for e in reg.workspaces.values() if e.mode == "pool"
    }
    pool_extras: list[tuple[str, str, str, str]] = []  # id, name, state, path
    if include_pool:
        for pool_id, ws_path in scan_pool_workspaces(_globals.WORKSPACE_ROOT):
            if pool_id in pool_ids_in_registry:
                continue
            try:
                proj = Project.load(pool_id, _globals.WORKSPACE_ROOT)
                pool_extras.append(
                    (proj.id, proj.name, proj.state.value, str(ws_path))
                )
            except Exception:
                continue

    if not reg.workspaces and not pool_extras:
        console.print("[yellow]No workspaces yet.[/yellow]")
        console.print(
            "Run [cyan]ortim init \"<brief>\"[/cyan] inside a project directory to start."
        )
        return

    table = Table(title="Workspaces")
    table.add_column(" ", style="green", width=1)  # current marker
    table.add_column("ID", style="cyan")
    table.add_column("Name")
    table.add_column("State")
    table.add_column("Mode")
    table.add_column("Last active", style="dim")
    table.add_column("Path", style="dim")

    archived_hidden = 0
    for entry in reg.entries():
        # Resolve archived flag from the live state.json — registry only
        # caches `state`, not `archived_at`.
        is_archived = False
        try:
            from ortim.workspace import ProjectStore, WorkspaceLocation, WorkspaceMode
            loc = WorkspaceLocation(
                path=Path(entry.path),
                mode=WorkspaceMode(entry.mode),
                id=entry.id,
            )
            store = ProjectStore(loc)
            if store.exists():
                is_archived = store.load().archived_at is not None
        except Exception:
            pass

        if is_archived and not include_archived:
            archived_hidden += 1
            continue

        marker = "*" if entry.id == reg.current else ""
        state_display = entry.state or ""
        if is_archived:
            state_display += " [dim](archived)[/dim]"
        table.add_row(
            marker,
            entry.id,
            entry.name,
            state_display,
            entry.mode,
            entry.last_active[:19] if entry.last_active else "",
            entry.path,
        )

    for pool_id, name, state, path in pool_extras:
        table.add_row("", pool_id, name, state, "pool (untracked)", "", path)

    console.print(table)
    if archived_hidden:
        console.print(
            f"\n[dim]{archived_hidden} archived workspace(s) hidden. "
            "Use [cyan]ortim ls --include-archived[/cyan] to see them.[/dim]"
        )
    if pool_extras:
        console.print(
            f"\n[dim]{len(pool_extras)} pool workspace(s) not in registry. "
            "`ortim workspace migrate <id>` to lift them into project mode.[/dim]"
        )
def use(
    workspace: str = typer.Argument(..., help="Workspace ID or name"),
) -> None:
    """Set the active workspace (registry `current` pointer).

    Subsequent `ortim status` / `ortim run` calls fall back to this pointer
    when no `.ortim/` is found in cwd. Analogous to git's `HEAD`.
    """
    from ortim.workspace import Registry

    reg = Registry.load()
    entry = reg.get(workspace)
    if entry is None:
        console.print(
            f"[red]Workspace '{workspace}' not in registry.[/red] "
            "Run [cyan]ortim ls[/cyan] to see registered workspaces."
        )
        raise typer.Exit(1)
    reg.current = entry.id
    reg.save()
    console.print(
        f"[green]Active workspace:[/green] [cyan]{entry.id}[/cyan] "
        f"([dim]{entry.name}[/dim])"
    )
    console.print(f"Path: {entry.path}")
def list_projects() -> None:
    """[DEPRECATED] Use `ortim ls`. Scans the pool layout."""
    print(
        "WARNING: `ortim list-projects` is deprecated; use `ortim ls` instead. "
        "Will be removed in v1.0.",
        file=sys.stderr,
    )
    ls()


@workspace_app.command("list")
def workspace_list(
    prune: bool = typer.Option(
        False, "--prune", help="Remove stale registry entries."
    ),
    include_pool: bool = typer.Option(
        True, "--include-pool/--no-pool",
        help="Also show unregistered workspaces in the pool layout.",
    ),
    include_archived: bool = typer.Option(
        False, "--include-archived/--no-archived",
        help="Also show archived workspaces.",
    ),
) -> None:
    """Alias for top-level `ortim ls`."""
    ls(prune=prune, include_pool=include_pool, include_archived=include_archived)


@workspace_app.command("use")
def workspace_use(
    workspace: str = typer.Argument(..., help="Workspace ID or name"),
) -> None:
    """Alias for top-level `ortim use`."""
    use(workspace=workspace)


@workspace_app.command("show")
def workspace_show(
    project_id: str = typer.Argument(
        None,
        help="Workspace ID. If omitted, discovered from cwd.",
    ),
) -> None:
    """Workspace metadata (alias for status; registry + state.json)."""
    status(project_id=project_id)


@workspace_app.command("archive")
def workspace_archive(
    project_id: str = typer.Argument(
        None,
        help="Workspace ID. If omitted, discovered from cwd.",
    ),
) -> None:
    """Mark the workspace as archived. Hidden from listings, mutating
    commands are rejected, but the file structure is untouched."""
    from ortim.audit import AuditLogger
    from ortim.workspace import archive_workspace

    project, store, _ = _resolve_project(project_id)
    if project.archived_at is not None:
        console.print(
            f"[yellow]{project.id} is already archived "
            f"({project.archived_at[:19]}).[/yellow]"
        )
        return

    archive_workspace(store, project)
    AuditLogger(path=store.audit_log_path()).log(
        "workspace_archived",
        project_id=project.id,
        archived_at=project.archived_at,
    )
    console.print(
        f"[green]Archived[/green] [cyan]{project.id}[/cyan] "
        f"([dim]{project.name}[/dim]) at {project.archived_at[:19]}"
    )


@workspace_app.command("unarchive")
def workspace_unarchive(
    project_id: str = typer.Argument(
        None,
        help="Workspace ID. If omitted, discovered from cwd.",
    ),
) -> None:
    """Clear the workspace's archived flag."""
    from ortim.audit import AuditLogger
    from ortim.workspace import unarchive_workspace

    project, store, _ = _resolve_project(project_id)
    if project.archived_at is None:
        console.print(f"[yellow]{project.id} is not archived.[/yellow]")
        return

    unarchive_workspace(store, project)
    AuditLogger(path=store.audit_log_path()).log(
        "workspace_unarchived", project_id=project.id
    )
    console.print(
        f"[green]Unarchived[/green] [cyan]{project.id}[/cyan] "
        f"([dim]{project.name}[/dim])"
    )


@workspace_app.command("cleanup")
def workspace_cleanup(
    older_than: int = typer.Option(
        ...,
        "--older-than",
        help="Target workspaces with no activity for this many days (required).",
    ),
    archived_only: bool = typer.Option(
        True,
        "--archived-only/--include-active",
        help="Default: archived workspaces only. With --include-active you "
        "can also delete active workspaces (risky).",
    ),
    state_filter: str = typer.Option(
        None, "--state",
        help="Only those in a specific state (e.g. 'failed').",
    ),
    yes: bool = typer.Option(
        False, "--yes", "-y",
        help="Actually delete. Without the flag, dry-run: lists what would be deleted.",
    ),
) -> None:
    """Physically delete old workspaces (dry-run by default).

    Safe by default: without `--yes` it only prints a list. In project mode
    only `.ortim/` is deleted (user code stays); in pool mode the whole
    workspace directory goes.
    """
    from ortim.audit import AuditLogger
    from ortim.workspace import delete_workspace, find_cleanup_candidates

    candidates = find_cleanup_candidates(
        older_than_days=older_than,
        archived_only=archived_only,
        state_filter=state_filter,
        pool_root=_globals.WORKSPACE_ROOT if _globals.WORKSPACE_ROOT.exists() else None,
    )

    if not candidates:
        console.print(
            f"[green]No workspaces matched the filter "
            f"(older_than={older_than}d, archived_only={archived_only}, "
            f"state={state_filter}).[/green]"
        )
        return

    table = Table(title="Cleanup candidates")
    table.add_column("ID", style="cyan")
    table.add_column("Name")
    table.add_column("Mode")
    table.add_column("Age (days)", justify="right")
    table.add_column("Reason")
    table.add_column("Path", style="dim")
    for c in candidates:
        table.add_row(
            c.entry_id,
            c.name,
            c.mode,
            f"{c.age_days:.1f}",
            c.reason,
            str(c.path),
        )
    console.print(table)

    if not yes:
        console.print(
            f"\n[yellow]Dry run.[/yellow] {len(candidates)} workspace(s) would be "
            "deleted. Add [cyan]--yes[/cyan] to apply."
        )
        return

    audit = AuditLogger()
    deleted = 0
    for c in candidates:
        try:
            delete_workspace(c)
            audit.log(
                "workspace_deleted",
                project_id=c.entry_id,
                path=str(c.path),
                age_days=c.age_days,
                reason=c.reason,
            )
            deleted += 1
        except OSError as e:
            console.print(f"[red]Failed to delete {c.entry_id}:[/red] {e}")

    console.print(f"\n[green]Deleted {deleted} workspace(s).[/green]")


@workspace_app.command("migrate")
def workspace_migrate(
    pool_id: str = typer.Argument(..., help="Workspace ID in the pool layout (uuid)"),
    to: Path = typer.Option(
        ...,
        "--to",
        help="Target project directory. Created if missing; errors if .ortim/ exists.",
    ),
    move: bool = typer.Option(
        False, "--move/--copy",
        help="--move relocates the pool (irreversible); default --copy copies.",
    ),
) -> None:
    """Migrate a pool-layout workspace into project mode.

    The contents of `<WORKSPACE_ROOT>/<pool_id>/` are split as follows:
      * ortim metadata (state.json/PRD.md/RFC.md/task_dag.json/.cache/...)
        → `<to>/.ortim/`
      * user code (auth/, cli/, src/, package.json, ...)
        → `<to>/` (root)

    The default `--copy` leaves the pool untouched; if anything goes wrong
    no original data is lost. `--move` is structurally identical but deletes
    the pool directory (verify cleanup afterwards with `ortim ls --no-pool`).
    """
    from ortim.audit import AuditLogger
    from ortim.workspace import MigrationError, migrate_pool_to_project

    pool_path = _globals.WORKSPACE_ROOT / pool_id
    try:
        location = migrate_pool_to_project(pool_path, to.resolve(), move=move)
    except MigrationError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1)
    except FileNotFoundError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1)

    # Per-workspace audit log (the migrated state.json now lives under .ortim/)
    AuditLogger(path=location.metadata_dir / "audit.jsonl").log(
        "workspace_migrated",
        project_id=pool_id,
        from_path=str(pool_path),
        to_path=str(location.path),
        mode=("move" if move else "copy"),
    )

    console.print(
        f"[green]Migrated[/green] [cyan]{pool_id}[/cyan] → "
        f"[cyan]{location.path}[/cyan] ({'move' if move else 'copy'})"
    )
    console.print(f"Metadata: {location.metadata_dir}")
    if not move:
        console.print(
            f"\n[dim]Pool workspace left intact at {pool_path}. "
            "Delete manually once you're confident.[/dim]"
        )


@workspace_app.command("doctor")
def workspace_doctor() -> None:
    """Health scan: registry/fs mismatches, unregistered pools, aging archives."""
    from ortim.workspace import doctor_scan

    findings = doctor_scan(pool_root=_globals.WORKSPACE_ROOT if _globals.WORKSPACE_ROOT.exists() else None)
    if not findings:
        console.print("[green]Workspace health: OK[/green] (no findings)")
        return

    table = Table(title="Workspace doctor")
    table.add_column("Severity")
    table.add_column("Code", style="cyan")
    table.add_column("Entity")
    table.add_column("Message")
    sev_colors = {"error": "[red]ERROR[/red]", "warn": "[yellow]WARN[/yellow]", "info": "[dim]INFO[/dim]"}
    for f in findings:
        table.add_row(
            sev_colors.get(f.severity, f.severity),
            f.code,
            f.entity or "",
            f.message,
        )
    console.print(table)
    errors = sum(1 for f in findings if f.severity == "error")
    if errors > 0:
        raise typer.Exit(code=1)


def register(app: typer.Typer) -> None:
    """Wire workspace-module commands onto the top-level Typer app."""
    app.command()(init)
    app.command()(new)
    app.command()(status)
    app.command()(inspect)
    app.command()(rescan)
    app.command()(baseline)
    app.command()(ls)
    app.command()(use)
    app.command("list-projects")(list_projects)
    app.add_typer(workspace_app, name="workspace")
