# SPDX-License-Identifier: FSL-1.1-Apache-2.0
# Copyright (c) 2026 ortim.dev
"""Tests for `ortim.workspace.registry`.

Locks the registry I/O contract, upsert semantics, current pointer
behavior, and prune_missing self-healing.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ortim.workspace.registry import (
    Registry,
    WorkspaceEntry,
    register_workspace,
    registry_path,
    scan_pool_workspaces,
    touch_workspace,
)
from ortim.workspace.resolver import WorkspaceLocation, WorkspaceMode


@pytest.fixture(autouse=True)
def _isolate_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Every registry test gets its own `ORTIM_HOME`."""
    monkeypatch.setenv("ORTIM_HOME", str(tmp_path / "ortim_home"))


# ---------------- I/O ----------------


def test_load_returns_empty_when_file_missing(tmp_path: Path) -> None:
    reg = Registry.load()
    assert reg.workspaces == {}
    assert reg.current is None


def test_load_returns_empty_when_file_corrupt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ORTIM_HOME", str(tmp_path / "home"))
    (tmp_path / "home").mkdir()
    (tmp_path / "home" / "registry.json").write_text("{not json", encoding="utf-8")
    reg = Registry.load()
    assert reg.workspaces == {}


def test_save_creates_parent_dirs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ORTIM_HOME", str(tmp_path / "deep" / "home"))
    reg = Registry()
    path = reg.save()
    assert path.exists()
    assert path.parent.exists()


def test_round_trip_preserves_entries(tmp_path: Path) -> None:
    reg = Registry()
    loc = WorkspaceLocation(path=tmp_path / "todo", mode=WorkspaceMode.PROJECT, id="todo-7a3b")
    reg.upsert(loc, name="todo")
    reg.current = "todo-7a3b"
    reg.save()

    reg2 = Registry.load()
    assert "todo-7a3b" in reg2.workspaces
    assert reg2.current == "todo-7a3b"
    assert reg2.workspaces["todo-7a3b"].name == "todo"


# ---------------- upsert ----------------


def test_upsert_inserts_new_entry(tmp_path: Path) -> None:
    reg = Registry()
    loc = WorkspaceLocation(path=tmp_path / "x", mode=WorkspaceMode.PROJECT, id="x-1")
    entry = reg.upsert(loc, name="x", state="intake")
    assert entry.id == "x-1"
    assert entry.path == str(tmp_path / "x")
    assert entry.state == "intake"
    assert entry.kind == "active"


def test_upsert_updates_existing_entry_preserves_created_at(tmp_path: Path) -> None:
    reg = Registry()
    loc = WorkspaceLocation(path=tmp_path / "x", mode=WorkspaceMode.PROJECT, id="x-1")
    first = reg.upsert(loc, name="x", state="intake")
    second = reg.upsert(loc, name="x", state="executing")
    assert second.created_at == first.created_at  # creation time stays
    assert second.last_active >= first.last_active
    assert second.state == "executing"


def test_upsert_uses_name_as_id_when_location_id_missing(tmp_path: Path) -> None:
    loc = WorkspaceLocation(path=tmp_path / "x", mode=WorkspaceMode.PROJECT, id=None)
    reg = Registry()
    entry = reg.upsert(loc, name="fallback-name")
    assert entry.id == "fallback-name"


# ---------------- current ----------------


def test_set_current_raises_for_unknown_id() -> None:
    reg = Registry()
    with pytest.raises(KeyError):
        reg.set_current("does-not-exist")


def test_remove_clears_current_pointer(tmp_path: Path) -> None:
    reg = Registry()
    loc = WorkspaceLocation(path=tmp_path / "x", mode=WorkspaceMode.PROJECT, id="x-1")
    reg.upsert(loc, name="x")
    reg.current = "x-1"
    assert reg.remove("x-1") is True
    assert reg.current is None


# ---------------- queries ----------------


def test_get_by_id_then_by_name(tmp_path: Path) -> None:
    reg = Registry()
    loc = WorkspaceLocation(path=tmp_path / "x", mode=WorkspaceMode.PROJECT, id="x-1")
    reg.upsert(loc, name="display-name")
    assert reg.get("x-1").name == "display-name"
    assert reg.get("display-name").id == "x-1"
    assert reg.get("missing") is None


def test_entries_sorted_by_last_active_desc(tmp_path: Path) -> None:
    import time

    reg = Registry()
    loc1 = WorkspaceLocation(path=tmp_path / "a", mode=WorkspaceMode.PROJECT, id="a")
    reg.upsert(loc1, name="a")
    time.sleep(0.01)
    loc2 = WorkspaceLocation(path=tmp_path / "b", mode=WorkspaceMode.PROJECT, id="b")
    reg.upsert(loc2, name="b")
    ids = [e.id for e in reg.entries()]
    assert ids[0] == "b"  # most recently active first
    assert ids[1] == "a"


# ---------------- prune_missing ----------------


def test_prune_drops_entries_with_no_state_file(tmp_path: Path) -> None:
    reg = Registry()
    gone_path = tmp_path / "deleted_dir"
    live_path = tmp_path / "live_dir"
    (live_path / ".ortim").mkdir(parents=True)
    (live_path / ".ortim" / "state.json").write_text("{}", encoding="utf-8")

    reg.upsert(
        WorkspaceLocation(path=gone_path, mode=WorkspaceMode.PROJECT, id="dead"),
        name="dead",
    )
    reg.upsert(
        WorkspaceLocation(path=live_path, mode=WorkspaceMode.PROJECT, id="live"),
        name="live",
    )

    removed = reg.prune_missing()
    assert removed == ["dead"]
    assert "live" in reg.workspaces


def test_prune_drops_current_pointer_when_pointed_entry_is_stale(
    tmp_path: Path,
) -> None:
    reg = Registry()
    reg.upsert(
        WorkspaceLocation(path=tmp_path / "gone", mode=WorkspaceMode.PROJECT, id="g"),
        name="g",
    )
    reg.current = "g"
    reg.prune_missing()
    assert reg.current is None


def test_prune_pool_mode_checks_root_state_json(tmp_path: Path) -> None:
    """Pool mode entries: state.json lives at workspace root, not under .ortim/."""
    reg = Registry()
    pool_dir = tmp_path / "pool_ws"
    pool_dir.mkdir()
    (pool_dir / "state.json").write_text("{}", encoding="utf-8")
    reg.upsert(
        WorkspaceLocation(path=pool_dir, mode=WorkspaceMode.POOL, id="pool-id"),
        name="pool-name",
    )
    removed = reg.prune_missing()
    assert removed == []  # pool ws still has state.json at root


# ---------------- register_workspace + touch_workspace ----------------


def test_register_workspace_creates_and_sets_current(tmp_path: Path) -> None:
    loc = WorkspaceLocation(
        path=tmp_path / "todo", mode=WorkspaceMode.PROJECT, id="todo-1"
    )
    entry = register_workspace(loc, name="todo", state="intake")
    assert entry.id == "todo-1"

    reg = Registry.load()
    assert reg.current == "todo-1"
    assert "todo-1" in reg.workspaces


def test_register_workspace_set_current_false(tmp_path: Path) -> None:
    loc = WorkspaceLocation(
        path=tmp_path / "x", mode=WorkspaceMode.PROJECT, id="x"
    )
    register_workspace(loc, name="x", set_current=False)
    reg = Registry.load()
    assert reg.current is None


def test_touch_workspace_updates_last_active(tmp_path: Path) -> None:
    import time

    loc = WorkspaceLocation(
        path=tmp_path / "x", mode=WorkspaceMode.PROJECT, id="x"
    )
    register_workspace(loc, name="x")
    reg_before = Registry.load()
    first_active = reg_before.workspaces["x"].last_active

    time.sleep(0.01)
    touch_workspace("x")

    reg_after = Registry.load()
    assert reg_after.workspaces["x"].last_active > first_active


def test_touch_workspace_on_missing_id_is_noop() -> None:
    # Must not raise even if id is unknown
    touch_workspace("never-registered")


# ---------------- scan_pool_workspaces ----------------


def test_scan_pool_yields_dirs_with_state_json(tmp_path: Path) -> None:
    pool = tmp_path / "pool"
    pool.mkdir()
    a = pool / "aaa"
    a.mkdir()
    (a / "state.json").write_text("{}", encoding="utf-8")
    b = pool / "bbb"
    b.mkdir()
    # b has no state.json — should be skipped
    pairs = list(scan_pool_workspaces(pool))
    ids = [p[0] for p in pairs]
    assert "aaa" in ids
    assert "bbb" not in ids


def test_scan_pool_missing_root_returns_empty(tmp_path: Path) -> None:
    pairs = list(scan_pool_workspaces(tmp_path / "nonexistent"))
    assert pairs == []
