# SPDX-License-Identifier: FSL-1.1-Apache-2.0
# Copyright (c) 2026 ortim.dev
"""Tests for `ortim.workspace.store.ProjectStore`.

Locks the contract that callers can persist/read Project state and artifacts
without knowing whether the layout is project mode (`.ortim/state.json`) or
legacy pool (`state.json` flat).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from ortim.orchestrator.project import Project
from ortim.workspace.resolver import WorkspaceLocation, WorkspaceMode
from ortim.workspace.store import ProjectStore


def _make_project(**overrides) -> Project:
    base: dict = {"name": "todo-app", "initial_brief_tr": "todo yöneticisi"}
    base.update(overrides)
    return Project(**base)


# ---------------- Project mode layout ----------------


def test_store_project_mode_writes_state_under_dot_ortim(tmp_path: Path) -> None:
    loc = WorkspaceLocation(path=tmp_path, mode=WorkspaceMode.PROJECT)
    store = ProjectStore(loc)
    project = _make_project()

    store.save(project)

    assert (tmp_path / ".ortim" / "state.json").exists()
    assert not (tmp_path / "state.json").exists()


def test_store_project_mode_artifact_path_under_dot_ortim(tmp_path: Path) -> None:
    loc = WorkspaceLocation(path=tmp_path, mode=WorkspaceMode.PROJECT)
    store = ProjectStore(loc)
    assert store.artifact_path("PRD.md") == tmp_path / ".ortim" / "PRD.md"


def test_store_project_mode_audit_log_path(tmp_path: Path) -> None:
    loc = WorkspaceLocation(path=tmp_path, mode=WorkspaceMode.PROJECT)
    store = ProjectStore(loc)
    assert store.audit_log_path() == tmp_path / ".ortim" / "audit.jsonl"


# ---------------- Pool mode layout (legacy) ----------------


def test_store_pool_mode_writes_state_at_root(tmp_path: Path) -> None:
    loc = WorkspaceLocation(path=tmp_path, mode=WorkspaceMode.POOL, id="abc123")
    store = ProjectStore(loc)
    project = _make_project()

    store.save(project)

    assert (tmp_path / "state.json").exists()
    assert not (tmp_path / ".ortim" / "state.json").exists()


def test_store_pool_mode_artifact_path_at_root(tmp_path: Path) -> None:
    loc = WorkspaceLocation(path=tmp_path, mode=WorkspaceMode.POOL, id="abc")
    store = ProjectStore(loc)
    assert store.artifact_path("PRD.md") == tmp_path / "PRD.md"


def test_store_pool_mode_audit_log_at_root(tmp_path: Path) -> None:
    loc = WorkspaceLocation(path=tmp_path, mode=WorkspaceMode.POOL, id="abc")
    store = ProjectStore(loc)
    assert store.audit_log_path() == tmp_path / "audit.jsonl"


# ---------------- Round-trip + artifacts ----------------


def test_store_round_trip_project_mode(tmp_path: Path) -> None:
    loc = WorkspaceLocation(path=tmp_path, mode=WorkspaceMode.PROJECT)
    store = ProjectStore(loc)
    project = _make_project()
    store.save(project)

    reloaded = store.load()
    assert reloaded.id == project.id
    assert reloaded.name == "todo-app"


def test_store_round_trip_pool_mode(tmp_path: Path) -> None:
    loc = WorkspaceLocation(path=tmp_path, mode=WorkspaceMode.POOL, id="abc")
    store = ProjectStore(loc)
    project = _make_project()
    store.save(project)

    reloaded = store.load()
    assert reloaded.id == project.id


def test_store_write_and_read_artifact(tmp_path: Path) -> None:
    loc = WorkspaceLocation(path=tmp_path, mode=WorkspaceMode.PROJECT)
    store = ProjectStore(loc)
    store.write_artifact("PRD.md", "# Goal\n\nFoo")
    assert store.read_artifact("PRD.md") == "# Goal\n\nFoo"


def test_store_write_and_read_json(tmp_path: Path) -> None:
    loc = WorkspaceLocation(path=tmp_path, mode=WorkspaceMode.PROJECT)
    store = ProjectStore(loc)
    store.write_json("intent.json", {"goal": "todo", "must_haves": []})
    data = store.read_json("intent.json")
    assert data == {"goal": "todo", "must_haves": []}


def test_store_read_artifact_missing_returns_none(tmp_path: Path) -> None:
    loc = WorkspaceLocation(path=tmp_path, mode=WorkspaceMode.PROJECT)
    store = ProjectStore(loc)
    assert store.read_artifact("nope.md") is None


def test_store_read_json_invalid_returns_none(tmp_path: Path) -> None:
    loc = WorkspaceLocation(path=tmp_path, mode=WorkspaceMode.PROJECT)
    store = ProjectStore(loc)
    (tmp_path / ".ortim").mkdir()
    (tmp_path / ".ortim" / "broken.json").write_text("{not json", encoding="utf-8")
    assert store.read_json("broken.json") is None


def test_store_load_raises_when_missing(tmp_path: Path) -> None:
    loc = WorkspaceLocation(path=tmp_path, mode=WorkspaceMode.PROJECT)
    store = ProjectStore(loc)
    with pytest.raises(FileNotFoundError):
        store.load()


def test_store_exists_returns_false_before_save(tmp_path: Path) -> None:
    loc = WorkspaceLocation(path=tmp_path, mode=WorkspaceMode.PROJECT)
    store = ProjectStore(loc)
    assert store.exists() is False


def test_store_exists_returns_true_after_save(tmp_path: Path) -> None:
    loc = WorkspaceLocation(path=tmp_path, mode=WorkspaceMode.PROJECT)
    store = ProjectStore(loc)
    store.save(_make_project())
    assert store.exists() is True


def test_for_new_project_mode_factory(tmp_path: Path) -> None:
    store = ProjectStore.for_new_project_mode(tmp_path)
    assert store.location.mode is WorkspaceMode.PROJECT
    assert store.location.path == tmp_path.resolve()
    assert store.state_file == tmp_path.resolve() / ".ortim" / "state.json"
