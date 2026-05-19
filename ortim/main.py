# SPDX-License-Identifier: FSL-1.1-Apache-2.0
# Copyright (c) 2026 ortim.dev
"""CLI entry point for Ortim.

Babel + Analyst + Architect + Orchestrator + Worker + Reviewer chain wired.
Command implementations live in `ortim.cli.*` modules; this file wires them
onto the top-level Typer app and re-exports the legacy symbols
(WORKSPACE_ROOT, helper functions) that tests + downstream code import
from `ortim.main`.
"""

from __future__ import annotations

import sys
from pathlib import Path

import typer
from dotenv import find_dotenv, load_dotenv
from rich.console import Console

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

# Walk up from the user's CWD, not from main.py's install location.
# PyPI installs put main.py in site-packages; walking up from there never
# reaches the user's project directory. `usecwd=True` makes `find_dotenv`
# start from `os.getcwd()` and walk up, which matches operator intent.
load_dotenv(find_dotenv(usecwd=True))

# Layer user config (`~/.ortim/config.toml`) on top of env vars. The
# config store only populates env vars that are currently unset, so
# shell/.env values always win. This lets PyPI users configure a
# provider once without needing a `.env` in every project directory.
from ortim.config import apply_to_env as _apply_user_config_to_env
from ortim.config import load as _load_user_config

_user_cfg = _load_user_config()
if _user_cfg is not None:
    _apply_user_config_to_env(_user_cfg)

# Backward-compat re-exports: tests + downstream callers import these from
# `ortim.main`. Canonical homes are `ortim.cli._globals` (globals/helpers)
# and `ortim.cli.{planning,execution,admin,workspace}` (private helpers).
from ortim.cli._globals import (  # noqa: F401, E402
    REPO_ROOT,
    WORKSPACE_ROOT,
    _apply_invocation_overrides,
    _block_if_archived,
    _ensure_workspace_root,
    _load_codebase_summary,
    _resolve_project,
)
from ortim.cli.admin import _DEMO_DEFAULT_BRIEF  # noqa: F401, E402
from ortim.cli.execution import (  # noqa: F401, E402
    _bootstrap_if_ready,
    _build_reviewer_chain,
    _load_for_execute,
    _maybe_finalize_done,
    _maybe_open_budget_gate,
    _maybe_open_schema_gate,
    _print_budget_gate_message,
    _print_schema_gate_message,
    _render_execution_result,
    _render_task_md,
    _run_all_loop,
)
from ortim.cli.planning import (  # noqa: F401, E402
    _draft_extend_rfc,
    _extension_feature_title,
    _extract_extension_section,
    _generate_extend_dag,
    _initiate_extend_prd,
    _list_extensions,
    _lock_intake,
    _lock_prd,
    _lock_stack,
)
from ortim.cli.workspace import _list_pool_projects  # noqa: F401, E402

app = typer.Typer(help="Ortim — agentic dev pipeline (v0.9.4)")
console = Console()

# Deprecation: the `ai-factory` CLI alias is kept for backwards
# compatibility but slated for removal in R7 (one minor release after
# the rename). Warn once per process when invoked under that name.
_argv0 = Path(sys.argv[0]).stem.lower() if sys.argv else ""
if _argv0 == "ai-factory":
    print(
        "WARNING: the `ai-factory` command is deprecated; use `ortim` instead "
        "(legacy alias will be removed in a future release)",
        file=sys.stderr,
    )

# `ortim config` — persistent provider/model/key config at ~/.ortim/.
# Mounted as a subapp so the wizard + show + setters live in their own
# module rather than ballooning main.py.
from ortim.config.cli import config_app as _config_app  # noqa: E402

app.add_typer(_config_app, name="config")

# Wire commands from each cli/ module onto the top-level app.
from ortim.cli import admin as _admin_cli  # noqa: E402
from ortim.cli import execution as _execution_cli  # noqa: E402
from ortim.cli import planning as _planning_cli  # noqa: E402
from ortim.cli import reporting as _reporting_cli  # noqa: E402
from ortim.cli import workspace as _workspace_cli  # noqa: E402

_workspace_cli.register(app)
_planning_cli.register(app)
_execution_cli.register(app)
_reporting_cli.register(app)
_admin_cli.register(app)


if __name__ == "__main__":
    app()
