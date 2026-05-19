# SPDX-License-Identifier: FSL-1.1-Apache-2.0
# Copyright (c) 2026 ortim.dev
"""Workspace location discovery.

Resolution order (cwd-first, git pattern):

  1. `<cwd>/.ortim/` — project mode anchor in current directory
  2. Parent walk — `<cwd>/../.ortim/`, `<cwd>/../../.ortim/`, ...
     stops at filesystem root, user home, or a `.git` boundary
  3. Registry `current` pointer — `~/.ortim/registry.json`
  4. Pool fallback — `WORKSPACE_ROOT/<arg>/state.json` (legacy)
  5. Registry name/id match — `arg` ↔ registry entry

The resolver returns a `WorkspaceLocation`; the caller (`ProjectStore`)
uses `mode` to pick the right path for `state.json` (project mode →
`location.path/.ortim/state.json`; pool mode → `location.path/state.json`).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from enum import Enum
from pathlib import Path


class WorkspaceMode(str, Enum):
    PROJECT = "project"
    POOL = "pool"


class WorkspaceNotFound(Exception):
    """Raised when discovery exhausts all resolution paths without a hit."""


@dataclass(frozen=True)
class WorkspaceLocation:
    """Physical location of a workspace + how to interpret its layout.

    `path` is the workspace root:
      * project mode → user's project dir; state.json lives at `path/.ortim/state.json`
      * pool mode    → legacy uuid dir;     state.json lives at `path/state.json`

    `id` is the workspace identifier (slug-hash6 for project mode, uuid-12
    for legacy pool). The resolver does NOT load state.json — callers do
    that via `ProjectStore.load_from_location`.
    """

    path: Path
    mode: WorkspaceMode
    id: str | None = None

    @property
    def state_file(self) -> Path:
        if self.mode is WorkspaceMode.PROJECT:
            return self.path / ".ortim" / "state.json"
        return self.path / "state.json"

    @property
    def metadata_dir(self) -> Path:
        """The directory where ortim writes its artifacts (PRD, RFC, audit, ...).

        Project mode → `<path>/.ortim/`
        Pool mode    → `<path>/`
        """
        if self.mode is WorkspaceMode.PROJECT:
            return self.path / ".ortim"
        return self.path


# Filenames inside `.ortim/` that signal project-mode anchor existence.
# `state.json` alone is enough — if a `.ortim/state.json` exists at any
# parent, that path is the workspace root.
_PROJECT_ANCHOR = "state.json"


def find_dot_ortim(start: Path, stop_at_home: bool = True) -> Path | None:
    """Walk up from `start` looking for a `.ortim/state.json` anchor.

    Returns the **workspace root** (the directory containing `.ortim/`),
    not the `.ortim/` dir itself. Stops at filesystem root or user home,
    whichever is reached first.

    `stop_at_home=False` lets tests probe across `tmp_path` without being
    bounded by the actual user home directory.
    """
    start = start.resolve()
    home = Path.home().resolve() if stop_at_home else None

    current = start if start.is_dir() else start.parent
    seen: set[Path] = set()
    while current not in seen:
        seen.add(current)
        anchor = current / ".ortim" / _PROJECT_ANCHOR
        if anchor.exists():
            return current
        if stop_at_home and home is not None and current == home:
            # Crossing user home upward usually means we left the user's
            # workspace tree; stop before we hit / or C:\ and walk the
            # entire filesystem.
            return None
        parent = current.parent
        if parent == current:
            return None
        current = parent
    return None


def discover_from_cwd(cwd: Path | None = None) -> WorkspaceLocation | None:
    """Find a project-mode workspace anchored at or above `cwd`.

    Pure discovery — no fallback to registry or pool. Returns None when
    no `.ortim/` is found in the walk. The caller decides whether to
    consult the registry next or surface a friendly error.
    """
    cwd = (cwd or Path.cwd()).resolve()
    root = find_dot_ortim(cwd)
    if root is None:
        return None
    return WorkspaceLocation(path=root, mode=WorkspaceMode.PROJECT)


def _registry_path() -> Path:
    """User-level registry path (`~/.ortim/registry.json`).

    Override via `ORTIM_HOME` for tests that need an isolated home dir.
    The directory is created lazily by the registry writer, not here —
    the resolver only reads.
    """
    home = os.getenv("ORTIM_HOME")
    if home:
        return Path(home) / "registry.json"
    return Path.home() / ".ortim" / "registry.json"


def _pool_root() -> Path:
    """Legacy pool root from `WORKSPACE_ROOT` env or `./workspaces`."""
    return Path(os.getenv("WORKSPACE_ROOT", "./workspaces"))


def _resolve_pool_id(arg: str) -> WorkspaceLocation | None:
    """Map a legacy uuid-style id to a pool workspace location.

    Pool workspaces live at `<pool_root>/<id>/state.json`. We only confirm
    the layout (state.json existence); the caller will load it.
    """
    candidate = _pool_root() / arg
    if (candidate / "state.json").exists():
        return WorkspaceLocation(
            path=candidate, mode=WorkspaceMode.POOL, id=arg
        )
    return None


def _resolve_registry(arg: str) -> WorkspaceLocation | None:
    """Look up `arg` in the user registry by id or name.

    Avoids importing the registry module to keep the resolver cycle-free —
    reads the JSON directly. If the registry doesn't exist, returns None.
    """
    reg_path = _registry_path()
    if not reg_path.exists():
        return None
    try:
        import json

        data = json.loads(reg_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    workspaces = data.get("workspaces") or {}
    # Exact id match wins
    if arg in workspaces:
        entry = workspaces[arg]
        return _entry_to_location(entry)
    # Fallback: name match (first hit wins; registry guarantees unique names
    # at insert time)
    for entry in workspaces.values():
        if entry.get("name") == arg:
            return _entry_to_location(entry)
    return None


def _entry_to_location(entry: dict) -> WorkspaceLocation | None:
    path = entry.get("path")
    mode_str = entry.get("mode", "project")
    wid = entry.get("id")
    if not path:
        return None
    try:
        mode = WorkspaceMode(mode_str)
    except ValueError:
        mode = WorkspaceMode.PROJECT
    return WorkspaceLocation(path=Path(path), mode=mode, id=wid)


def resolve_workspace(
    arg: str | None = None,
    cwd: Path | None = None,
) -> WorkspaceLocation:
    """Locate a workspace by user input (or cwd if no input given).

    Resolution order:
      arg is None:
        1. cwd discovery (parent walk for `.ortim/`)
        2. registry `current` pointer
        3. raise WorkspaceNotFound

      arg is given:
        1. registry lookup (id or name)
        2. legacy pool id lookup
        3. raise WorkspaceNotFound
    """
    if arg is None:
        loc = discover_from_cwd(cwd)
        if loc is not None:
            return loc
        current = _resolve_current_pointer()
        if current is not None:
            return current
        raise WorkspaceNotFound(
            "No project here. Run `ortim init \"<brief>\"` to start a new "
            "project, or `cd` into an existing one. See `ortim ls` for "
            "registered workspaces."
        )

    loc = _resolve_registry(arg)
    if loc is not None:
        return loc
    loc = _resolve_pool_id(arg)
    if loc is not None:
        return loc
    raise WorkspaceNotFound(
        f"Workspace '{arg}' not found. Searched: registry, pool "
        f"({_pool_root()}). Run `ortim ls` to see known workspaces."
    )


def _resolve_current_pointer() -> WorkspaceLocation | None:
    """Read `~/.ortim/registry.json::current` and resolve it.

    Returns None when the pointer is unset, when the registry entry was
    cleaned up, or — G-A1 — when the entry still exists but its path no
    longer does on disk (temp-dir reaper, manual delete, drive change).
    The resolver is read-only by contract: it does NOT auto-prune the
    stale entry. Run `ortim workspace doctor` to surface the mismatch
    and decide whether to migrate the workspace or remove the entry.
    Silently skipping here is the right symptom fix — falling through
    to the friendly `No project here` error beats opening a workspace
    at a path the operating system already deleted.
    """
    reg_path = _registry_path()
    if not reg_path.exists():
        return None
    try:
        import json

        data = json.loads(reg_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    current_id = data.get("current")
    if not current_id:
        return None
    loc = _resolve_registry(current_id)
    if loc is None:
        return None
    if not loc.state_file.exists():
        return None
    return loc
