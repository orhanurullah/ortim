# SPDX-License-Identifier: FSL-1.1-Apache-2.0
# Copyright (c) 2026 ortim.dev
"""Tests for `ortim.workspace.resolver`.

Locks the cwd-first discovery contract (git pattern), parent walk bounds,
registry lookup, and pool fallback semantics.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ortim.workspace.resolver import (
    WorkspaceLocation,
    WorkspaceMode,
    WorkspaceNotFound,
    discover_from_cwd,
    find_dot_ortim,
    resolve_workspace,
)


def _make_project_anchor(root: Path, state: dict | None = None) -> Path:
    """Create a `.ortim/state.json` anchor under `root`. Returns the workspace root."""
    state = state or {"id": "todo-app-7a3b", "name": "todo-app", "state": "intake"}
    dot = root / ".ortim"
    dot.mkdir(parents=True, exist_ok=True)
    (dot / "state.json").write_text(json.dumps(state), encoding="utf-8")
    return root


# ---------------- find_dot_ortim ----------------


def test_find_dot_ortim_returns_root_when_anchor_in_cwd(tmp_path: Path) -> None:
    _make_project_anchor(tmp_path)
    found = find_dot_ortim(tmp_path, stop_at_home=False)
    assert found == tmp_path.resolve()


def test_find_dot_ortim_walks_up_to_parent(tmp_path: Path) -> None:
    _make_project_anchor(tmp_path)
    nested = tmp_path / "src" / "deep" / "module"
    nested.mkdir(parents=True)
    found = find_dot_ortim(nested, stop_at_home=False)
    assert found == tmp_path.resolve()


def test_find_dot_ortim_returns_none_when_no_anchor(tmp_path: Path) -> None:
    nested = tmp_path / "empty"
    nested.mkdir()
    assert find_dot_ortim(nested, stop_at_home=False) is None


def test_find_dot_ortim_picks_nearest_anchor_when_nested(tmp_path: Path) -> None:
    outer = tmp_path
    inner = tmp_path / "inner"
    inner.mkdir()
    _make_project_anchor(outer, {"id": "outer", "name": "outer", "state": "intake"})
    _make_project_anchor(inner, {"id": "inner", "name": "inner", "state": "intake"})
    found = find_dot_ortim(inner, stop_at_home=False)
    assert found == inner.resolve()


def test_find_dot_ortim_anchor_without_state_json_does_not_match(tmp_path: Path) -> None:
    (tmp_path / ".ortim").mkdir()
    assert find_dot_ortim(tmp_path, stop_at_home=False) is None


# ---------------- discover_from_cwd ----------------


def test_discover_from_cwd_returns_location_when_anchor_present(tmp_path: Path) -> None:
    _make_project_anchor(tmp_path)
    nested = tmp_path / "src"
    nested.mkdir()
    loc = discover_from_cwd(nested)
    assert loc is not None
    assert loc.path == tmp_path.resolve()
    assert loc.mode is WorkspaceMode.PROJECT


def test_discover_from_cwd_returns_none_when_no_anchor(tmp_path: Path) -> None:
    assert discover_from_cwd(tmp_path) is None


# ---------------- WorkspaceLocation paths ----------------


def test_workspace_location_project_mode_state_file(tmp_path: Path) -> None:
    loc = WorkspaceLocation(path=tmp_path, mode=WorkspaceMode.PROJECT)
    assert loc.state_file == tmp_path / ".ortim" / "state.json"
    assert loc.metadata_dir == tmp_path / ".ortim"


def test_workspace_location_pool_mode_state_file(tmp_path: Path) -> None:
    loc = WorkspaceLocation(path=tmp_path, mode=WorkspaceMode.POOL, id="abc123")
    assert loc.state_file == tmp_path / "state.json"
    assert loc.metadata_dir == tmp_path


# ---------------- resolve_workspace (cwd-first) ----------------


def test_resolve_workspace_no_arg_uses_cwd_discovery(tmp_path: Path) -> None:
    _make_project_anchor(tmp_path)
    loc = resolve_workspace(arg=None, cwd=tmp_path)
    assert loc.mode is WorkspaceMode.PROJECT
    assert loc.path == tmp_path.resolve()


def test_resolve_workspace_no_arg_raises_when_no_anchor_and_no_registry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Isolate home so a real `~/.ortim/registry.json` doesn't bleed in.
    monkeypatch.setenv("ORTIM_HOME", str(tmp_path / "ortim_home"))
    with pytest.raises(WorkspaceNotFound):
        resolve_workspace(arg=None, cwd=tmp_path)


# ---------------- resolve_workspace (pool fallback) ----------------


def test_resolve_workspace_arg_finds_pool_workspace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pool_root = tmp_path / "workspaces"
    pool_root.mkdir()
    pool_ws = pool_root / "079fb8862112"
    pool_ws.mkdir()
    (pool_ws / "state.json").write_text(
        json.dumps({"id": "079fb8862112", "name": "x", "state": "intake"}),
        encoding="utf-8",
    )
    monkeypatch.setenv("WORKSPACE_ROOT", str(pool_root))
    monkeypatch.setenv("ORTIM_HOME", str(tmp_path / "ortim_home"))

    loc = resolve_workspace(arg="079fb8862112")
    assert loc.mode is WorkspaceMode.POOL
    assert loc.id == "079fb8862112"
    assert loc.path == pool_ws


def test_resolve_workspace_unknown_arg_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("WORKSPACE_ROOT", str(tmp_path / "workspaces"))
    monkeypatch.setenv("ORTIM_HOME", str(tmp_path / "ortim_home"))
    with pytest.raises(WorkspaceNotFound):
        resolve_workspace(arg="does-not-exist")


# ---------------- resolve_workspace (registry lookup) ----------------


def test_resolve_workspace_arg_finds_registry_entry_by_id(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "ortim_home"
    home.mkdir()
    project_dir = tmp_path / "todo-app"
    _make_project_anchor(project_dir)
    registry = {
        "version": 1,
        "current": None,
        "workspaces": {
            "todo-app-7a3b": {
                "id": "todo-app-7a3b",
                "name": "todo-app",
                "path": str(project_dir),
                "mode": "project",
            }
        },
    }
    (home / "registry.json").write_text(json.dumps(registry), encoding="utf-8")
    monkeypatch.setenv("ORTIM_HOME", str(home))

    loc = resolve_workspace(arg="todo-app-7a3b")
    assert loc.mode is WorkspaceMode.PROJECT
    assert loc.path == project_dir
    assert loc.id == "todo-app-7a3b"


def test_resolve_workspace_arg_finds_registry_entry_by_name(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "ortim_home"
    home.mkdir()
    project_dir = tmp_path / "todo-app"
    _make_project_anchor(project_dir)
    registry = {
        "version": 1,
        "current": None,
        "workspaces": {
            "todo-app-7a3b": {
                "id": "todo-app-7a3b",
                "name": "todo-app",
                "path": str(project_dir),
                "mode": "project",
            }
        },
    }
    (home / "registry.json").write_text(json.dumps(registry), encoding="utf-8")
    monkeypatch.setenv("ORTIM_HOME", str(home))

    loc = resolve_workspace(arg="todo-app")
    assert loc.id == "todo-app-7a3b"


def test_resolve_workspace_no_arg_uses_current_pointer_when_cwd_empty(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "ortim_home"
    home.mkdir()
    project_dir = tmp_path / "todo-app"
    _make_project_anchor(project_dir)
    registry = {
        "version": 1,
        "current": "todo-app-7a3b",
        "workspaces": {
            "todo-app-7a3b": {
                "id": "todo-app-7a3b",
                "name": "todo-app",
                "path": str(project_dir),
                "mode": "project",
            }
        },
    }
    (home / "registry.json").write_text(json.dumps(registry), encoding="utf-8")
    monkeypatch.setenv("ORTIM_HOME", str(home))

    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    loc = resolve_workspace(arg=None, cwd=elsewhere)
    assert loc.path == project_dir
    assert loc.id == "todo-app-7a3b"


def test_resolve_workspace_cwd_discovery_beats_registry_current(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When cwd has its own .ortim/ anchor, that wins over registry `current`."""
    home = tmp_path / "ortim_home"
    home.mkdir()
    here = tmp_path / "todo-app"
    elsewhere = tmp_path / "other-app"
    _make_project_anchor(here, {"id": "here", "name": "here", "state": "intake"})
    _make_project_anchor(
        elsewhere, {"id": "elsewhere", "name": "elsewhere", "state": "intake"}
    )
    registry = {
        "version": 1,
        "current": "elsewhere",
        "workspaces": {
            "elsewhere": {
                "id": "elsewhere",
                "name": "elsewhere",
                "path": str(elsewhere),
                "mode": "project",
            }
        },
    }
    (home / "registry.json").write_text(json.dumps(registry), encoding="utf-8")
    monkeypatch.setenv("ORTIM_HOME", str(home))

    loc = resolve_workspace(arg=None, cwd=here)
    assert loc.path == here.resolve()


def test_resolve_workspace_corrupt_registry_falls_through(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "ortim_home"
    home.mkdir()
    (home / "registry.json").write_text("{not json", encoding="utf-8")
    monkeypatch.setenv("ORTIM_HOME", str(home))
    monkeypatch.setenv("WORKSPACE_ROOT", str(tmp_path / "no-such-pool"))
    with pytest.raises(WorkspaceNotFound):
        resolve_workspace(arg="anything", cwd=tmp_path)


def test_resolve_workspace_skips_stale_current_pointer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """G-A1 regression: registry `current` points at a workspace whose
    state.json was deleted (temp-dir reaper, manual rm, drive change).
    Resolver must NOT return the broken location — falling through to
    the friendly `No project here` error beats opening a workspace at
    a path the OS already deleted."""
    home = tmp_path / "ortim_home"
    home.mkdir()
    ghost = tmp_path / "deleted-app"  # registry entry, but no anchor on disk
    registry = {
        "version": 1,
        "current": "deleted-7a3b",
        "workspaces": {
            "deleted-7a3b": {
                "id": "deleted-7a3b",
                "name": "deleted-app",
                "path": str(ghost),
                "mode": "project",
            }
        },
    }
    (home / "registry.json").write_text(json.dumps(registry), encoding="utf-8")
    monkeypatch.setenv("ORTIM_HOME", str(home))
    monkeypatch.setenv("WORKSPACE_ROOT", str(tmp_path / "no-such-pool"))

    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    with pytest.raises(WorkspaceNotFound):
        resolve_workspace(arg=None, cwd=elsewhere)


def test_resolve_workspace_falls_through_to_friendly_error_when_current_stale(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When the stale `current` is skipped, cwd discovery has also failed,
    AND there's no pool match — the user gets the standard `No project
    here` guidance, not an opaque FileNotFoundError from a downstream
    `ProjectStore.load()`."""
    home = tmp_path / "ortim_home"
    home.mkdir()
    registry = {
        "version": 1,
        "current": "ghost",
        "workspaces": {
            "ghost": {
                "id": "ghost",
                "name": "ghost",
                "path": str(tmp_path / "never-existed"),
                "mode": "project",
            }
        },
    }
    (home / "registry.json").write_text(json.dumps(registry), encoding="utf-8")
    monkeypatch.setenv("ORTIM_HOME", str(home))

    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    try:
        resolve_workspace(arg=None, cwd=elsewhere)
    except WorkspaceNotFound as exc:
        assert "ortim init" in str(exc)
        return
    raise AssertionError("expected WorkspaceNotFound, got success")
