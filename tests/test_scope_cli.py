# SPDX-License-Identifier: FSL-1.1-Apache-2.0
# Copyright (c) 2026 ortim.dev
"""Tests for `ortim scope` CLI flow — Faz 1.1 MVP_SCOPE_LOCKING.

Covers:
  * `_lock_prd` seeds scope.json from intent.json and transitions PRD_DIALOG
    → MVP_SCOPE_LOCKING (NOT PRD_AWAITING_APPROVAL — that comes after scope
    is locked).
  * `ortim scope --set <substr>=<phase>` non-interactively rewrites phase
    + priority on matching features and saves scope.json.
  * `ortim scope --lock` advances MVP_SCOPE_LOCKING → PRD_AWAITING_APPROVAL.
  * Re-locking the PRD does NOT clobber an existing scope.json (user edits
    survive a re-draft cycle).
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

import pytest
from typer.testing import CliRunner

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from runtime.audit import AuditLogger  # noqa: E402
from runtime.babel import StructuredIntent  # noqa: E402
from runtime.main import _lock_prd, app  # noqa: E402
from runtime.memory import MemoryLoader  # noqa: E402
from runtime.orchestrator import Project, ProjectState  # noqa: E402
from runtime.scope import ScopeManifest, ScopedFeature, load_scope, save_scope  # noqa: E402
from runtime.scope.schema import scope_path  # noqa: E402


def _project_at_prd_dialog(workspace_root: Path) -> tuple[Project, Path]:
    """Walk a Project from INTAKE through STACK_DIALOG to PRD_DIALOG and
    write a synthetic intent.json so `_lock_prd` can seed the scope."""
    project = Project(name="todo-fixture", initial_brief_tr="todo istiyorum")
    project.save(workspace_root)
    workspace = Project.workspace_path(project.id, workspace_root)

    intent = StructuredIntent(
        goal="todo app",
        must_have_features=["task creation", "task listing", "task completion"],
        nice_to_have_features=["tagging", "search"],
    )
    (workspace / "intent.json").write_text(
        intent.model_dump_json(indent=2), encoding="utf-8"
    )

    for s in [
        ProjectState.BABEL_PROCESSING,
        ProjectState.INTAKE_DIALOG,
        ProjectState.STACK_DIALOG,
        ProjectState.PRD_DIALOG,
    ]:
        project.transition(s, actor="fixture", note="setup")
    project.save(workspace_root)
    return project, workspace


def test_lock_prd_seeds_scope_and_transitions_to_scope_locking(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        monkeypatch.setattr("runtime.main.WORKSPACE_ROOT", root)

        project, workspace = _project_at_prd_dialog(root)
        audit_path = workspace / "audit.jsonl"
        audit_path.touch()
        audit = AuditLogger(path=audit_path)
        memory = MemoryLoader(REPO_ROOT)

        _lock_prd(project, workspace, audit, memory)

        assert project.state == ProjectState.MVP_SCOPE_LOCKING
        assert scope_path(workspace).exists()
        manifest = load_scope(workspace)
        assert {f.description for f in manifest.phase_1_features()} == {
            "task creation",
            "task listing",
            "task completion",
        }
        assert {f.description for f in manifest.deferred_features()} == {
            "tagging",
            "search",
        }
        assert manifest.locked_at is None  # not yet locked — needs `scope --lock`


def test_re_lock_prd_does_not_clobber_existing_scope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Once the user has edited scope.json (e.g. moved a feature to
    phase 2), running `_lock_prd` again must NOT silently re-seed."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        monkeypatch.setattr("runtime.main.WORKSPACE_ROOT", root)

        project, workspace = _project_at_prd_dialog(root)
        audit = AuditLogger(path=workspace / "audit.jsonl")
        memory = MemoryLoader(REPO_ROOT)
        _lock_prd(project, workspace, audit, memory)

        # Simulate the user editing — promote "tagging" into Phase 1 and
        # add a manual feature. Then back-step to PRD_DIALOG and re-lock.
        manifest = load_scope(workspace)
        for f in manifest.features:
            if f.description == "tagging":
                f.phase = 1
                f.priority = "must"
        manifest.features.append(
            ScopedFeature(description="manual extra", source="manual", phase=1)
        )
        save_scope(workspace, manifest)
        edited_count = len(manifest.features)

        project.transition(
            ProjectState.PRD_DIALOG, actor="test", note="back-step for re-lock"
        )
        _lock_prd(project, workspace, audit, memory)

        # User edits must survive — same feature count, "tagging" still
        # promoted to phase 1, "manual extra" still present.
        reloaded = load_scope(workspace)
        assert len(reloaded.features) == edited_count
        by_desc = {f.description: f for f in reloaded.features}
        assert by_desc["tagging"].phase == 1
        assert by_desc["manual extra"].source == "manual"


def test_scope_set_flag_rewrites_phase_and_locks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`ortim scope <id> --set "tagging=2" --lock` is the headless
    path — sets phase from CLI and advances to PRD_AWAITING_APPROVAL."""
    runner = CliRunner()
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        monkeypatch.setattr("runtime.main.WORKSPACE_ROOT", root)

        project, workspace = _project_at_prd_dialog(root)
        audit = AuditLogger(path=workspace / "audit.jsonl")
        memory = MemoryLoader(REPO_ROOT)
        _lock_prd(project, workspace, audit, memory)

        result = runner.invoke(
            app,
            [
                "scope",
                project.id,
                "--set",
                "tagging=1",  # promote tagging into MVP
                "--set",
                "search=3",  # park search even later
                "--lock",
            ],
        )
        assert result.exit_code == 0, result.output

        manifest = load_scope(workspace)
        by_desc = {f.description: f for f in manifest.features}
        assert by_desc["tagging"].phase == 1
        assert by_desc["tagging"].priority == "must"
        assert by_desc["search"].phase == 3
        assert by_desc["search"].priority == "later"
        assert manifest.locked_at is not None

        reloaded_project = Project.load(project.id, root)
        assert reloaded_project.state == ProjectState.PRD_AWAITING_APPROVAL


def test_scope_command_rejects_wrong_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = CliRunner()
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        monkeypatch.setattr("runtime.main.WORKSPACE_ROOT", root)

        # Project still in PRD_DIALOG — scope command must refuse.
        project, _ = _project_at_prd_dialog(root)
        result = runner.invoke(app, ["scope", project.id, "--show"])
        assert result.exit_code == 1
        assert "MVP_SCOPE_LOCKING" in result.output
