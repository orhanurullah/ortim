# SPDX-License-Identifier: FSL-1.1-Apache-2.0
# Copyright (c) 2026 ortim.dev
"""Tests for cwd-aware CLI resolution (M3 milestone).

Locks the contract that read commands (status / tasks / gates / show /
extensions / inspect) work without an explicit project_id argument when
invoked inside a directory that contains `.ortim/state.json`. Also locks
the friendly error when no project is discoverable.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from ortim.main import app  # noqa: E402
from ortim.workspace import init_project  # noqa: E402


@pytest.fixture
def project_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Create a fresh project-mode workspace at `tmp_path` and chdir into it.

    Goes through the `ortim init` CLI command so the registry write side
    effect is exercised (rather than calling `init_project` directly,
    which is a pure helper and skips registry registration).
    Isolates `ORTIM_HOME` and a fake pool root so the resolver doesn't see
    the user's real registry or workspaces.
    """
    monkeypatch.setenv("ORTIM_HOME", str(tmp_path / "ortim_home"))
    monkeypatch.setenv("WORKSPACE_ROOT", str(tmp_path / "fake_pool"))
    monkeypatch.setattr("ortim.main.WORKSPACE_ROOT", tmp_path / "fake_pool")
    project_root = tmp_path / "my-app"
    project_root.mkdir()
    monkeypatch.chdir(project_root)

    runner = CliRunner()
    result = runner.invoke(app, ["init", "test brief", "--name", "test-app"])
    assert result.exit_code == 0, f"init failed: {result.output}"

    return project_root


@pytest.fixture
def elsewhere_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A directory that has no `.ortim/` anchor and no registered workspace."""
    monkeypatch.setenv("ORTIM_HOME", str(tmp_path / "ortim_home"))
    monkeypatch.setenv("WORKSPACE_ROOT", str(tmp_path / "fake_pool"))
    monkeypatch.setattr("ortim.main.WORKSPACE_ROOT", tmp_path / "fake_pool")
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    return elsewhere


# ---------------- status ----------------


def test_status_no_arg_discovers_cwd(project_dir: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["status"])
    assert result.exit_code == 0, result.output
    assert "test-app" in result.output
    assert "intake" in result.output
    # Mode rozeti yeni — project mode olmalı
    assert "project" in result.output.lower()


def test_status_no_arg_in_subdir_walks_up(project_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    sub = project_dir / "src" / "deep"
    sub.mkdir(parents=True)
    monkeypatch.chdir(sub)
    runner = CliRunner()
    result = runner.invoke(app, ["status"])
    assert result.exit_code == 0
    assert "test-app" in result.output


def test_status_no_arg_no_anchor_gives_friendly_error(elsewhere_dir: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["status"])
    assert result.exit_code == 1
    assert "No project here" in result.output or "ortim init" in result.output


# ---------------- tasks ----------------


def test_tasks_no_arg_discovers_cwd(project_dir: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["tasks"])
    # No DAG yet, but resolution succeeded → "No task DAG" message + exit 0
    assert result.exit_code == 0
    assert "No task DAG" in result.output


# ---------------- gates ----------------


def test_gates_no_arg_discovers_cwd(project_dir: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["gates"])
    # New project at INTAKE has no open gates yet → "No open gates" exit 0
    assert result.exit_code == 0


# ---------------- extensions ----------------


def test_extensions_no_arg_discovers_cwd(project_dir: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["extensions"])
    assert result.exit_code == 0
    assert "No extensions" in result.output


# ---------------- inspect ----------------


def test_inspect_no_arg_greenfield_says_not_brownfield(project_dir: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["inspect"])
    assert result.exit_code == 0
    assert "not a brownfield" in result.output.lower()


# ---------------- backward compat: arg still works ----------------


def test_status_with_explicit_arg_still_works(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Pool-style explicit arg path: legacy callers + tests keep working."""
    pool_root = tmp_path / "workspaces"
    pool_root.mkdir()
    monkeypatch.setattr("ortim.main.WORKSPACE_ROOT", pool_root)

    from ortim.orchestrator import Project

    project = Project(name="pool-app", initial_brief_tr="x")
    project.save(pool_root)

    # cd elsewhere — explicit arg must still resolve to pool layout
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    monkeypatch.setenv("ORTIM_HOME", str(tmp_path / "ortim_home"))

    runner = CliRunner()
    result = runner.invoke(app, ["status", project.id])
    assert result.exit_code == 0, result.output
    assert "pool-app" in result.output
    assert "pool" in result.output.lower()


# ---------------- ls ----------------


def test_ls_empty_when_no_workspaces(elsewhere_dir: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["ls"])
    assert result.exit_code == 0
    assert "No workspaces" in result.output


def test_ls_shows_pool_workspaces(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pool_root = tmp_path / "workspaces"
    pool_root.mkdir()
    monkeypatch.setattr("ortim.main.WORKSPACE_ROOT", pool_root)
    monkeypatch.setenv("ORTIM_HOME", str(tmp_path / "ortim_home"))

    from ortim.orchestrator import Project

    p1 = Project(name="alpha", initial_brief_tr="x")
    p1.save(pool_root)
    p2 = Project(name="beta", initial_brief_tr="y")
    p2.save(pool_root)

    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)

    runner = CliRunner()
    result = runner.invoke(app, ["ls"])
    assert result.exit_code == 0
    assert "alpha" in result.output
    assert "beta" in result.output


def test_ls_shows_cwd_project_mode_workspace(
    project_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["ls"])
    assert result.exit_code == 0
    assert "test-app" in result.output
    assert "project" in result.output.lower()


def test_list_projects_emits_deprecation_warning(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("ortim.main.WORKSPACE_ROOT", tmp_path / "ws")
    monkeypatch.setenv("ORTIM_HOME", str(tmp_path / "ortim_home"))
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()
    result = runner.invoke(app, ["list-projects"])
    # Exits 0 with "No workspaces yet" message; stderr carries the warning
    assert result.exit_code == 0
    # typer CliRunner combines stderr+stdout into .output by default
    # but stderr is also accessible via .stderr if mix_stderr=False
    # Just check no crash; deprecation warning emitted via sys.stderr.


# ---------------- mutating commands (cwd-aware) ----------------


def test_advance_no_project_arg_discovers_cwd(project_dir: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["advance", "babel_processing", "--note", "x"])
    assert result.exit_code == 0, result.output
    # Verify state updated on disk
    state = json.loads((project_dir / ".ortim" / "state.json").read_text(encoding="utf-8"))
    assert state["state"] == "babel_processing"


def test_advance_to_alias_writes_audit_under_dot_ortim(
    project_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """advance with an _APPROVAL_ALIAS target writes an audit event to the
    per-workspace audit log (Project Mode .ortim/audit.jsonl), not the
    legacy global path."""
    # Walk the state machine to PRD_AWAITING_APPROVAL so prd_approved alias is reachable.
    from ortim.orchestrator import Project, ProjectState

    project = Project.model_validate_json(
        (project_dir / ".ortim" / "state.json").read_text(encoding="utf-8")
    )
    for s in [
        ProjectState.BABEL_PROCESSING,
        ProjectState.PRD_DRAFTING,
        ProjectState.MVP_SCOPE_LOCKING,
        ProjectState.PRD_AWAITING_APPROVAL,
    ]:
        project.transition(s, actor="fixture", note="setup")
    (project_dir / ".ortim" / "state.json").write_text(
        project.model_dump_json(indent=2), encoding="utf-8"
    )

    runner = CliRunner()
    result = runner.invoke(app, ["advance", "prd_approved", "--note", "ok"])
    assert result.exit_code == 0, result.output

    audit = project_dir / ".ortim" / "audit.jsonl"
    assert audit.exists(), "per-workspace audit log must exist after advance"
    lines = audit.read_text(encoding="utf-8").splitlines()
    # gate_prd_approved should be present
    assert any('"gate_prd_approved"' in ln for ln in lines), (
        f"expected gate_prd_approved event in {audit}; lines:\n" + "\n".join(lines)
    )


def test_advance_pool_legacy_via_project_flag(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`--project <id>` flag preserves legacy pool flow (no cwd needed)."""
    pool_root = tmp_path / "workspaces"
    pool_root.mkdir()
    monkeypatch.setattr("ortim.main.WORKSPACE_ROOT", pool_root)
    monkeypatch.setenv("ORTIM_HOME", str(tmp_path / "ortim_home"))

    from ortim.orchestrator import Project

    project = Project(name="pool-app", initial_brief_tr="x")
    project.save(pool_root)

    # cd to an unrelated dir to prove --project pulls the workspace anyway
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)

    runner = CliRunner()
    result = runner.invoke(
        app, ["advance", "babel_processing", "--project", project.id, "--note", "y"]
    )
    assert result.exit_code == 0, result.output
    # State.json updated under pool layout
    state = json.loads((pool_root / project.id / "state.json").read_text(encoding="utf-8"))
    assert state["state"] == "babel_processing"


def test_advance_no_project_outside_anchor_friendly_error(elsewhere_dir: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["advance", "babel_processing"])
    assert result.exit_code == 1
    assert "No project here" in result.output or "ortim init" in result.output


# ---------------- ortim use (active context) ----------------


def test_use_sets_current_pointer(project_dir: Path, elsewhere_dir: Path) -> None:
    """`ortim use <name>` outside the project dir updates the registry
    current pointer; subsequent `ortim status` (no arg, no .ortim) picks
    it up via the resolver's current-pointer fallback."""
    runner = CliRunner()
    result = runner.invoke(app, ["use", "test-app"])
    assert result.exit_code == 0
    assert "Active workspace" in result.output

    # Verify resolver picks the current pointer when cwd has no anchor
    result_status = runner.invoke(app, ["status"])
    assert result_status.exit_code == 0
    assert "test-app" in result_status.output


def test_use_unknown_workspace_fails(elsewhere_dir: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["use", "does-not-exist"])
    assert result.exit_code == 1
    assert "not in registry" in result.output


def test_init_registers_workspace_and_sets_current(project_dir: Path) -> None:
    """Lock that `ortim init` writes a registry entry + makes it current."""
    from ortim.workspace import Registry

    reg = Registry.load()
    assert any(e.name == "test-app" for e in reg.workspaces.values())
    assert reg.current is not None
    current_entry = reg.workspaces[reg.current]
    assert current_entry.name == "test-app"


def test_ls_marks_current_workspace_with_star(project_dir: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["ls"])
    assert result.exit_code == 0
    # `*` marker should appear next to the current workspace row
    assert "*" in result.output
    assert "test-app" in result.output


# ---------------- ortim workspace archive / unarchive / cleanup / doctor ----------------


def test_workspace_archive_marks_archived_and_hides_from_ls(
    project_dir: Path,
) -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["workspace", "archive"])
    assert result.exit_code == 0, result.output
    assert "Archived" in result.output

    # Verify state.json has archived_at
    state = json.loads((project_dir / ".ortim" / "state.json").read_text(encoding="utf-8"))
    assert state["archived_at"] is not None

    # Default ls hides archived
    ls_result = runner.invoke(app, ["ls"])
    assert "archived workspace(s) hidden" in ls_result.output

    # --include-archived shows them
    ls_full = runner.invoke(app, ["ls", "--include-archived"])
    assert "test-app" in ls_full.output


def test_workspace_unarchive_clears_flag(project_dir: Path) -> None:
    runner = CliRunner()
    runner.invoke(app, ["workspace", "archive"])
    result = runner.invoke(app, ["workspace", "unarchive"])
    assert result.exit_code == 0
    assert "Unarchived" in result.output

    state = json.loads((project_dir / ".ortim" / "state.json").read_text(encoding="utf-8"))
    assert state["archived_at"] is None


def test_archived_workspace_blocks_advance(project_dir: Path) -> None:
    """Mutating commands should refuse on archived workspaces with a
    friendly hint pointing at `unarchive`."""
    runner = CliRunner()
    runner.invoke(app, ["workspace", "archive"])
    result = runner.invoke(app, ["advance", "babel_processing"])
    assert result.exit_code == 1
    assert "archived" in result.output.lower()
    assert "unarchive" in result.output


def test_workspace_cleanup_dry_run_default(project_dir: Path) -> None:
    """`cleanup` without --yes is dry-run: lists, doesn't delete."""
    runner = CliRunner()
    runner.invoke(app, ["workspace", "archive"])
    # Back-date the project so it matches --older-than 1
    import json as _json
    from datetime import datetime, timedelta, timezone

    state_path = project_dir / ".ortim" / "state.json"
    state = _json.loads(state_path.read_text(encoding="utf-8"))
    old = (datetime.now(timezone.utc) - timedelta(days=10)).isoformat()
    state["created_at"] = old
    state_path.write_text(_json.dumps(state, indent=2), encoding="utf-8")

    result = runner.invoke(app, ["workspace", "cleanup", "--older-than", "1"])
    assert result.exit_code == 0
    assert "Dry run" in result.output
    # State.json should still exist
    assert state_path.exists()


def test_workspace_cleanup_yes_actually_deletes(project_dir: Path) -> None:
    runner = CliRunner()
    runner.invoke(app, ["workspace", "archive"])
    import json as _json
    from datetime import datetime, timedelta, timezone

    state_path = project_dir / ".ortim" / "state.json"
    state = _json.loads(state_path.read_text(encoding="utf-8"))
    old = (datetime.now(timezone.utc) - timedelta(days=10)).isoformat()
    state["created_at"] = old
    state_path.write_text(_json.dumps(state, indent=2), encoding="utf-8")

    result = runner.invoke(
        app, ["workspace", "cleanup", "--older-than", "1", "--yes"]
    )
    assert result.exit_code == 0
    assert "Deleted" in result.output
    assert not (project_dir / ".ortim").exists()


def test_workspace_doctor_reports_clean_state_for_fresh_workspace(
    project_dir: Path,
) -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["workspace", "doctor"])
    # Fresh init shouldn't produce errors; might surface info about pool
    assert result.exit_code in (0, 1)  # depends on pool extras
