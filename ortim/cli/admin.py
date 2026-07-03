"""CLI: admin commands — doctor, demo."""

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

def demo(
    brief: str = typer.Option(
        _DEMO_DEFAULT_BRIEF,
        "--brief",
        help="Custom demo brief (default: todo CLI in English)",
    ),
    execute_first: bool = typer.Option(
        False, "--execute",
        help="Also execute T-001 after planning (adds ~$0.05 LLM cost)",
    ),
    provider: str = typer.Option(
        None, "--provider",
        help="LLM provider for the whole chain (anthropic | deepseek | "
        "ollama). Propagates to every subprocess step via env.",
    ),
    model: str = typer.Option(
        None, "--model",
        help="Model id override for the whole chain.",
    ),
) -> None:
    """End-to-end planning demo — brief → PRD → RFC → DAG in one command.

    Disables dialog mode and auto-approves G1/G2 so the chain runs to
    `tasks_ready` without operator intervention. This is a non-production
    walkthrough; the auto-approve is recorded in audit log as
    `gate_prd_approved` / `gate_rfc_approved` with the demo note so the
    intent is never silent.

    Approximate cost on DeepSeek-only routing: $0.02-0.05 for planning,
    +$0.05 per task with --execute. With no API key configured at all,
    the demo falls back to the bundled **recorded replay** (a captured
    real run of this exact chain) so the walkthrough completes keyless;
    `ortim doctor` to verify env.
    """
    import subprocess
    import time

    # Apply CLI overrides FIRST so the key check below sees the right
    # provider's key (e.g. --provider ollama needs no key at all).
    _apply_invocation_overrides(provider=provider, model=model)

    # Check that the resolved provider has whatever credentials it needs.
    # Local providers (api_key_env=None, e.g. ollama) pass unconditionally.
    from ortim.llm.providers import resolve_provider
    try:
        active = resolve_provider()
    except Exception as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(code=1)
    replay_mode = False
    if active.api_key_env is not None and not os.environ.get(
        active.api_key_env, ""
    ).strip():
        if provider:
            # The operator explicitly asked for this provider — a silent
            # switch to replay would misrepresent what ran. Hard error.
            console.print(
                f"[red]{active.api_key_env} is not set[/red] "
                f"(resolved provider: '{active.name}').\n"
                f"Fix one of:\n"
                f"  - [cyan]ortim config init[/cyan] to configure a "
                f"provider once\n"
                f"  - export {active.api_key_env}=... or add to .env\n"
                f"  - rerun with [cyan]--provider ollama[/cyan] for a "
                f"local, key-free runtime"
            )
            raise typer.Exit(code=1)
        replay_mode = True

    if replay_mode and brief != _DEMO_DEFAULT_BRIEF:
        console.print(
            "[red]No API key configured — the recorded demo only covers "
            "the default brief.[/red]\n"
            "Fix one of:\n"
            "  - drop [cyan]--brief[/cyan] to watch the recorded default "
            "run\n"
            "  - [cyan]ortim config init[/cyan] to configure a provider "
            "for live runs"
        )
        raise typer.Exit(code=1)
    if replay_mode and execute_first:
        console.print(
            "[yellow]--execute needs a live provider; recorded demo runs "
            "the planning chain only. Skipping T-001 execution.[/yellow]"
        )
        execute_first = False

    if replay_mode:
        console.print(Panel(
            "[bold]Recorded demo[/bold] — no API key detected, so this run "
            "replays a captured real run of the same chain "
            "([yellow]not a live model[/yellow]). Every artifact you'll "
            "see (PRD, RFC, task DAG) came from an actual LLM run.\n"
            "For live runs: [cyan]ortim config init[/cyan]",
            border_style="yellow",
        ))

    _ensure_workspace_root()
    project_name = f"demo-{int(time.time())}"
    console.print(
        f"\n[bold]Ortim Demo[/bold] — workspace name: [cyan]{project_name}[/cyan]"
    )
    console.print(f"[dim]Brief: {brief[:80]}{'...' if len(brief) > 80 else ''}[/dim]")

    project = Project(name=project_name, initial_brief_tr=brief)
    project.save(_globals.WORKSPACE_ROOT)
    console.print(f"[dim]project_id: {project.id}[/dim]\n")

    # Dialog mode off for the demo run — restored on exit. Without this,
    # `run` routes through INTAKE_DIALOG / STACK_DIALOG / PRD_DIALOG and
    # demo would need to also drive `ortim discuss` interactions.
    # Clear both new and legacy names so the helper falls through to the
    # explicit `off` we set, regardless of operator's prior env.
    saved_new = os.environ.pop("ORTIM_DIALOG_MODE", None)
    saved_legacy = os.environ.pop("AI_FACTORY_DIALOG_MODE", None)
    os.environ["ORTIM_DIALOG_MODE"] = "off"

    # Chain subprocesses run with cwd=REPO_ROOT (site-packages on a pip
    # install), where a relative "./workspaces" would resolve somewhere
    # else than the parent's. Export the parent's resolved root so every
    # step operates on the project we just created.
    saved_ws_root = os.environ.get("WORKSPACE_ROOT")
    os.environ["WORKSPACE_ROOT"] = str(_globals.WORKSPACE_ROOT.resolve())

    # Replay mode pins EVERY role to the replay provider for the whole
    # subprocess chain — role-specific env (ARCHITECT_PROVIDER etc.) or
    # DEFAULT_MODEL from the operator's shell/.env must not punch through
    # to a live endpoint mid-replay. Saved + restored in the finally
    # block alongside the dialog-mode vars. The cursor state file makes
    # the fixture position survive across the chain's subprocesses.
    saved_replay_env: dict[str, str | None] = {}
    replay_state_file = None
    if replay_mode:
        from ortim.llm.replay import STATE_ENV
        from ortim.llm.router import KNOWN_ROLES

        replay_keys = ["LLM_PROVIDER", "DEFAULT_MODEL", STATE_ENV]
        for role in KNOWN_ROLES:
            replay_keys.append(f"{role.upper()}_PROVIDER")
            replay_keys.append(f"{role.upper()}_MODEL")
        for key in replay_keys:
            saved_replay_env[key] = os.environ.pop(key, None)

        replay_state_file = (
            _globals.WORKSPACE_ROOT / f".replay-state-{project.id}.json"
        )
        os.environ[STATE_ENV] = str(replay_state_file)
        os.environ["LLM_PROVIDER"] = "replay"
        for role in KNOWN_ROLES:
            os.environ[f"{role.upper()}_PROVIDER"] = "replay"

    def _step(args: list[str], label: str) -> int:
        console.print(f"[cyan]→ {label}[/cyan]")
        result = subprocess.run(
            [sys.executable, "-m", "ortim.main", *args],
            cwd=_globals.REPO_ROOT,
        )
        return result.returncode

    try:
        # 0.9.0 project-mode pivot moved advance/execute/extend to a single
        # positional arg + `--project / -p` flag for the workspace id. Demo
        # spawns subprocesses against the same CLI surface, so it must use
        # the flag form for those three commands. `run` and `scope` remain
        # positional cwd-aware (a pool id is still resolvable as the first
        # positional via the pool-fallback in `_resolve_project`).
        chain = [
            (["run", project.id], "Babel + Analyst (PRD draft)"),
            (
                ["scope", project.id, "--lock"],
                "MVP scope auto-lock (Faz 1.1 — accepts default phase split)",
            ),
            (
                ["advance", "prd_approved", "--project", project.id,
                 "--note", "demo auto-approve"],
                "G1 — auto-approve PRD",
            ),
            (["run", project.id], "Architect (RFC + tier selection)"),
            (
                ["advance", "rfc_approved", "--project", project.id,
                 "--note", "demo auto-approve"],
                "G2 — auto-approve RFC",
            ),
            (["run", project.id], "Orchestrator (DAG generation)"),
        ]
        if execute_first:
            chain.append(
                (["execute", "T-001", "--project", project.id],
                 "Worker + Reviewer (T-001)")
            )

        for args, label in chain:
            rc = _step(args, label)
            if rc != 0:
                # `execute` may fail at the last step without invalidating
                # the planning chain that already produced PRD/RFC/DAG —
                # surface the failure but still print the summary so the
                # operator can inspect the artifacts.
                if args[0] == "execute":
                    console.print(
                        f"[yellow]T-001 did not complete cleanly "
                        f"(exit {rc}); planning artifacts are still valid.[/yellow]"
                    )
                    break
                console.print(
                    f"[red]Step '{label}' failed (exit {rc}); aborting demo.[/red]"
                )
                raise typer.Exit(code=rc)
    finally:
        os.environ.pop("ORTIM_DIALOG_MODE", None)
        if saved_new is not None:
            os.environ["ORTIM_DIALOG_MODE"] = saved_new
        if saved_legacy is not None:
            os.environ["AI_FACTORY_DIALOG_MODE"] = saved_legacy
        if saved_ws_root is None:
            os.environ.pop("WORKSPACE_ROOT", None)
        else:
            os.environ["WORKSPACE_ROOT"] = saved_ws_root
        for key, value in saved_replay_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        if replay_state_file is not None:
            replay_state_file.unlink(missing_ok=True)

    workspace = project.current_metadata_dir(_globals.WORKSPACE_ROOT)
    if replay_mode:
        console.print(
            "\n[bold green]Demo complete.[/bold green] "
            "[yellow](recorded run — not a live model)[/yellow]"
        )
    else:
        console.print("\n[bold green]Demo complete.[/bold green]")
    console.print(f"Workspace: [cyan]{workspace}[/cyan]")
    console.print("\n[bold]Next steps:[/bold]")
    console.print(
        f"  [cyan]ortim status {project.id}[/cyan]      — state + history"
    )
    console.print(
        f"  [cyan]ortim tasks {project.id}[/cyan]       — generated DAG"
    )
    console.print(
        f"  [cyan]ortim retro {project.id}[/cyan]       — token + cost rollup"
    )
    console.print(
        f"  [cyan]ortim drift-check {project.id}[/cyan] — integrity check"
    )
    if not execute_first:
        console.print(
            f"  [cyan]ortim run-all {project.id}[/cyan]    "
            "— execute all tasks end-to-end"
        )
def doctor(
    as_json: bool = typer.Option(
        False, "--json",
        help="JSON output (for automation)",
    ),
) -> None:
    """Environment health check — keys, runtimes, prompts, templates.

    Read-only. Reports gaps + fix hints; does not modify anything.

    Exit codes:
      0 — clean (required + recommended ✓)
      2 — required ✓ but one or more recommended items missing
      3 — required missing (the system cannot even run basic commands)
    """
    import json as _json

    from ortim.doctor import run_all_checks, to_json_dict

    report = run_all_checks(
        workspace_root=_globals.WORKSPACE_ROOT,
        repo_root=_globals.REPO_ROOT,
        assets_root=_globals.ASSETS_ROOT,
    )

    if as_json:
        console.print_json(_json.dumps(to_json_dict(report)))
        raise typer.Exit(code=report.exit_code)

    table = Table(title="Ortim Doctor")
    table.add_column("Check", style="cyan")
    table.add_column("Status", justify="center")
    table.add_column("Detail")
    for c in report.checks:
        if c.status == "ok":
            status_cell = "[green]OK[/green]"
        elif c.status == "warning":
            status_cell = "[yellow]WARN[/yellow]"
        else:
            status_cell = (
                "[red]MISS[/red]" if c.category == "required"
                else "[yellow]MISS[/yellow]" if c.category == "recommended"
                else "[dim]--[/dim]"
            )
        table.add_row(c.name, status_cell, c.detail)
    console.print(table)

    req_ok = sum(
        1 for c in report.checks
        if c.category == "required" and c.status == "ok"
    )
    rec_ok = sum(
        1 for c in report.checks
        if c.category == "recommended" and c.status == "ok"
    )
    opt_ok = sum(
        1 for c in report.checks
        if c.category == "optional" and c.status == "ok"
    )
    req_total = sum(1 for c in report.checks if c.category == "required")
    rec_total = sum(1 for c in report.checks if c.category == "recommended")
    opt_total = sum(1 for c in report.checks if c.category == "optional")

    console.print(
        f"\nrequired: [green]{req_ok}/{req_total}[/green]  "
        f"recommended: "
        f"{'[green]' if rec_ok == rec_total else '[yellow]'}"
        f"{rec_ok}/{rec_total}[/]  "
        f"optional: {opt_ok}/{opt_total}"
    )

    fix_hints = [c for c in report.checks if c.fix_hint and c.status != "ok"]
    if fix_hints:
        console.print("\n[bold]Fix hints:[/bold]")
        for c in fix_hints:
            console.print(f"  [cyan]{c.name}[/cyan]: {c.fix_hint}")

    raise typer.Exit(code=report.exit_code)


def register(app: typer.Typer) -> None:
    """Wire admin-module commands onto the top-level Typer app."""
    app.command()(demo)
    app.command()(doctor)
