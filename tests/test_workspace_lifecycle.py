# SPDX-License-Identifier: FSL-1.1-Apache-2.0
# Copyright (c) 2026 ortim.dev
"""Tests for `ortim.workspace.lifecycle`: archive, unarchive, cleanup, doctor.

Covers helper-level behavior (no CLI). CLI-level tests for the
`ortim workspace archive/cleanup/...` commands live in
test_cli_cwd_aware.py.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from ortim.orchestrator.project import Project
from ortim.workspace.lifecycle import (
    _age_days,
    archive_workspace,
    delete_workspace,
    doctor_scan,
    find_cleanup_candidates,
    unarchive_workspace,
)
from ortim.workspace.registry import Registry, register_workspace
from ortim.workspace.resolver import WorkspaceLocation, WorkspaceMode
from ortim.workspace.store import ProjectStore


@pytest.fixture(autouse=True)
def _isolate_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ORTIM_HOME", str(tmp_path / "ortim_home"))


def _make_project_workspace(
    tmp_path: Path,
    name: str = "todo",
    aged_days: int = 0,
) -> tuple[Path, WorkspaceLocation, ProjectStore, Project]:
    """Create a project-mode workspace under tmp_path/<name>/.ortim/.
    Optionally back-date its history so cleanup tests can match."""
    project_root = tmp_path / name
    project_root.mkdir(parents=True, exist_ok=True)
    location = WorkspaceLocation(
        path=project_root, mode=WorkspaceMode.PROJECT, id=f"{name}-id"
    )
    store = ProjectStore(location)
    project = Project(name=name, initial_brief_tr="x")
    if aged_days:
        # Use created_at to drive _last_active when history is empty
        old_ts = (
            datetime.now(timezone.utc) - timedelta(days=aged_days)
        ).isoformat()
        project = Project(
            name=name, initial_brief_tr="x", created_at=old_ts
        )
    store.save(project)
    register_workspace(location, name=name, state=project.state.value)
    return project_root, location, store, project


# ---------------- archive / unarchive ----------------


def test_archive_sets_timestamp_and_persists(tmp_path: Path) -> None:
    _, location, store, project = _make_project_workspace(tmp_path)
    assert project.archived_at is None
    archive_workspace(store, project)
    assert project.archived_at is not None

    # Reload from disk to confirm persistence
    fresh = store.load()
    assert fresh.archived_at is not None


def test_archive_is_idempotent(tmp_path: Path) -> None:
    _, _, store, project = _make_project_workspace(tmp_path)
    archive_workspace(store, project)
    first_ts = project.archived_at
    archive_workspace(store, project)
    assert project.archived_at == first_ts  # unchanged


def test_unarchive_clears_timestamp(tmp_path: Path) -> None:
    _, _, store, project = _make_project_workspace(tmp_path)
    archive_workspace(store, project)
    assert project.archived_at is not None
    unarchive_workspace(store, project)
    assert project.archived_at is None
    assert store.load().archived_at is None


def test_unarchive_is_idempotent_on_active(tmp_path: Path) -> None:
    _, _, store, project = _make_project_workspace(tmp_path)
    unarchive_workspace(store, project)
    assert project.archived_at is None  # still None, no error


# ---------------- find_cleanup_candidates ----------------


def test_no_candidates_when_workspaces_are_fresh(tmp_path: Path) -> None:
    _make_project_workspace(tmp_path, "fresh", aged_days=0)
    candidates = find_cleanup_candidates(older_than_days=30, archived_only=True)
    assert candidates == []


def test_old_archived_workspace_is_candidate(tmp_path: Path) -> None:
    _, _, store, project = _make_project_workspace(tmp_path, "old", aged_days=60)
    archive_workspace(store, project)
    candidates = find_cleanup_candidates(older_than_days=30, archived_only=True)
    assert len(candidates) == 1
    assert candidates[0].entry_id == "old-id"
    assert candidates[0].reason == "archived"


def test_old_active_workspace_skipped_when_archived_only(tmp_path: Path) -> None:
    """An old workspace that wasn't archived must NOT be picked up under
    the default safety filter."""
    _make_project_workspace(tmp_path, "old-active", aged_days=60)
    candidates = find_cleanup_candidates(older_than_days=30, archived_only=True)
    assert candidates == []


def test_old_active_workspace_picked_when_archived_only_false(tmp_path: Path) -> None:
    _make_project_workspace(tmp_path, "old-active", aged_days=60)
    candidates = find_cleanup_candidates(older_than_days=30, archived_only=False)
    assert len(candidates) == 1
    assert candidates[0].entry_id == "old-active-id"
    assert candidates[0].reason == "age-only"


def test_state_filter_narrows_results(tmp_path: Path) -> None:
    _, _, _, p1 = _make_project_workspace(tmp_path, "alpha", aged_days=60)
    _, _, _, p2 = _make_project_workspace(tmp_path, "beta", aged_days=60)
    # Both are at INTAKE; filter for "failed" → none match
    candidates = find_cleanup_candidates(
        older_than_days=30,
        archived_only=False,
        state_filter="failed",
    )
    assert candidates == []


# ---------------- delete_workspace ----------------


def test_delete_project_mode_removes_only_dot_ortim(tmp_path: Path) -> None:
    project_root, _, _, project = _make_project_workspace(
        tmp_path, "todo", aged_days=60
    )
    # User has their own code file outside .ortim/
    (project_root / "README.md").write_text("# user code", encoding="utf-8")
    archive_workspace(
        ProjectStore(
            WorkspaceLocation(
                path=project_root, mode=WorkspaceMode.PROJECT, id="todo-id"
            )
        ),
        project,
    )

    candidates = find_cleanup_candidates(older_than_days=30)
    assert candidates
    delete_workspace(candidates[0])

    # User's code survives
    assert (project_root / "README.md").exists()
    # ortim metadata gone
    assert not (project_root / ".ortim").exists()
    # Registry entry gone
    reg = Registry.load()
    assert "todo-id" not in reg.workspaces


def test_delete_pool_mode_removes_full_directory(tmp_path: Path) -> None:
    pool_dir = tmp_path / "workspaces" / "uuid-abc"
    pool_dir.mkdir(parents=True)
    (pool_dir / "state.json").write_text(
        Project(name="x", initial_brief_tr="x").model_dump_json(), encoding="utf-8"
    )
    pool_location = WorkspaceLocation(
        path=pool_dir, mode=WorkspaceMode.POOL, id="uuid-abc"
    )
    register_workspace(pool_location, name="x", state="intake")

    # Archive it via state.json
    store = ProjectStore(pool_location)
    project = store.load()
    archive_workspace(store, project)

    # Back-date to make eligible
    project.created_at = (
        datetime.now(timezone.utc) - timedelta(days=60)
    ).isoformat()
    store.save(project)

    candidates = find_cleanup_candidates(older_than_days=30)
    assert candidates
    delete_workspace(candidates[0])
    assert not pool_dir.exists()


# ---------------- doctor_scan ----------------


def test_doctor_reports_missing_path(tmp_path: Path) -> None:
    # Register a workspace whose path doesn't exist
    location = WorkspaceLocation(
        path=tmp_path / "vanished",
        mode=WorkspaceMode.PROJECT,
        id="vanished",
    )
    register_workspace(location, name="vanished")
    findings = doctor_scan()
    assert any(f.code == "path_missing" for f in findings)


def test_doctor_reports_orphan_pool(tmp_path: Path) -> None:
    pool = tmp_path / "workspaces"
    pool.mkdir()
    ws = pool / "orphan-id"
    ws.mkdir()
    (ws / "state.json").write_text(
        Project(name="x", initial_brief_tr="x").model_dump_json(), encoding="utf-8"
    )
    findings = doctor_scan(pool_root=pool)
    assert any(f.code == "pool_unregistered" for f in findings)


def test_doctor_reports_aged_archive(tmp_path: Path) -> None:
    _, _, store, project = _make_project_workspace(tmp_path, "old-arch")
    # Archive with an ancient timestamp
    project.archived_at = (
        datetime.now(timezone.utc) - timedelta(days=100)
    ).isoformat()
    store.save(project)
    findings = doctor_scan()
    assert any(f.code == "archived_aging" for f in findings)


def test_doctor_clean_returns_empty(tmp_path: Path) -> None:
    _make_project_workspace(tmp_path, "healthy")
    findings = doctor_scan()
    # No errors/warns; might have info-level entries if pool root exists,
    # but for a clean fixture should be empty
    errors = [f for f in findings if f.severity == "error"]
    assert errors == []


# ---------------- _age_days ----------------


def test_age_days_returns_zero_for_unparseable_timestamp() -> None:
    assert _age_days("not-an-iso") == 0.0


def test_age_days_handles_timezone_naive(monkeypatch: pytest.MonkeyPatch) -> None:
    iso = (datetime.now() - timedelta(days=5)).isoformat()
    # Should not raise; tz-naive timestamps get UTC assumed
    age = _age_days(iso)
    assert 4 < age < 6


# ---------------- migrate_pool_to_project ----------------


def test_migrate_separates_metadata_from_user_code(tmp_path: Path) -> None:
    """Locks the layout-split contract: known meta files go into .ortim/,
    everything else stays at the workspace root."""
    from ortim.workspace.lifecycle import migrate_pool_to_project

    # Build a realistic pool workspace
    pool = tmp_path / "workspaces" / "abc123uuid"
    pool.mkdir(parents=True)

    # metadata
    project = Project(name="todo", initial_brief_tr="x", id="abc123uuid")
    (pool / "state.json").write_text(project.model_dump_json(), encoding="utf-8")
    (pool / "PRD.md").write_text("# PRD", encoding="utf-8")
    (pool / "RFC.md").write_text("# RFC", encoding="utf-8")
    (pool / "task_dag.json").write_text("{}", encoding="utf-8")
    (pool / "intent.json").write_text("{}", encoding="utf-8")
    (pool / "T-001.log").write_text("log", encoding="utf-8")
    cache_dir = pool / ".cache"
    cache_dir.mkdir()
    (cache_dir / "codebase.json").write_text("{}", encoding="utf-8")

    # user code
    (pool / "package.json").write_text('{"name":"x"}', encoding="utf-8")
    src_dir = pool / "src"
    src_dir.mkdir()
    (src_dir / "index.ts").write_text("export {};", encoding="utf-8")

    dest = tmp_path / "todo-app"
    location = migrate_pool_to_project(pool, dest)

    # Metadata lives under .ortim/
    assert (dest / ".ortim" / "state.json").exists()
    assert (dest / ".ortim" / "PRD.md").exists()
    assert (dest / ".ortim" / "RFC.md").exists()
    assert (dest / ".ortim" / "task_dag.json").exists()
    assert (dest / ".ortim" / "intent.json").exists()
    assert (dest / ".ortim" / "T-001.log").exists()
    assert (dest / ".ortim" / ".cache" / "codebase.json").exists()

    # User code stays at root
    assert (dest / "package.json").exists()
    assert (dest / "src" / "index.ts").exists()

    # Location is project-mode
    assert location.mode == WorkspaceMode.PROJECT
    assert location.path == dest.resolve()

    # Pool path still exists (copy mode, not move)
    assert (pool / "state.json").exists()


def test_migrate_updates_registry_and_sets_current(tmp_path: Path) -> None:
    """After migration, registry should hold a project-mode entry and the
    `current` pointer should point at it."""
    from ortim.workspace.lifecycle import migrate_pool_to_project

    pool = tmp_path / "workspaces" / "old-uuid"
    pool.mkdir(parents=True)
    project = Project(name="x", initial_brief_tr="x", id="old-uuid")
    (pool / "state.json").write_text(project.model_dump_json(), encoding="utf-8")

    # Register as pool first (simulating an `ortim ls` scan that bumped it
    # into the registry under pool mode)
    register_workspace(
        WorkspaceLocation(path=pool, mode=WorkspaceMode.POOL, id="old-uuid"),
        name="x",
    )

    dest = tmp_path / "new-home"
    migrate_pool_to_project(pool, dest)

    reg = Registry.load()
    entry = reg.workspaces.get("old-uuid")
    assert entry is not None
    assert entry.mode == WorkspaceMode.PROJECT.value
    assert entry.path == str(dest.resolve())
    assert reg.current == "old-uuid"


def test_migrate_refuses_when_destination_dot_ortim_exists(tmp_path: Path) -> None:
    from ortim.workspace.lifecycle import MigrationError, migrate_pool_to_project

    pool = tmp_path / "workspaces" / "src"
    pool.mkdir(parents=True)
    (pool / "state.json").write_text(
        Project(name="x", initial_brief_tr="x").model_dump_json(),
        encoding="utf-8",
    )

    dest = tmp_path / "dest"
    (dest / ".ortim").mkdir(parents=True)
    with pytest.raises(MigrationError, match=r"already exists"):
        migrate_pool_to_project(pool, dest)


def test_migrate_refuses_when_pool_has_no_state_json(tmp_path: Path) -> None:
    from ortim.workspace.lifecycle import MigrationError, migrate_pool_to_project

    pool = tmp_path / "workspaces" / "empty"
    pool.mkdir(parents=True)
    dest = tmp_path / "dest"
    with pytest.raises(MigrationError, match=r"no state.json"):
        migrate_pool_to_project(pool, dest)


def test_migrate_move_removes_pool_dir(tmp_path: Path) -> None:
    """`move=True` should consume the pool side. Test platform-specifically:
    shutil.move semantics differ on Windows when cross-volume but tmp_path
    is single-volume."""
    from ortim.workspace.lifecycle import migrate_pool_to_project

    pool = tmp_path / "workspaces" / "to-move"
    pool.mkdir(parents=True)
    (pool / "state.json").write_text(
        Project(name="x", initial_brief_tr="x").model_dump_json(),
        encoding="utf-8",
    )
    (pool / "package.json").write_text("{}", encoding="utf-8")

    dest = tmp_path / "new-home"
    migrate_pool_to_project(pool, dest, move=True)

    # Files moved out of the pool dir
    assert not (pool / "state.json").exists()
    assert (dest / ".ortim" / "state.json").exists()
    assert (dest / "package.json").exists()
