# SPDX-License-Identifier: FSL-1.1-Apache-2.0
# Copyright (c) 2026 ortim.dev
"""User-level workspace registry.

A single JSON file at `~/.ortim/registry.json` (override via `ORTIM_HOME`)
indexes every known workspace by id → (path, mode, kind, state, name).
The registry is **not** authoritative for state — the workspace's own
`state.json` is. The registry is an index for global listing (`ortim ls`),
arg-based lookup (`ortim status <name>`), and active context tracking
(`current` pointer).

Concurrency: writes are not locked. Two parallel `ortim init` invocations
could race here — accepted because a registry collision surfaces as a
duplicate entry the user can clean up, while file locking would impose
cross-process overhead on every CLI call.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from pydantic import BaseModel, Field

from ortim.workspace.resolver import WorkspaceLocation, WorkspaceMode

REGISTRY_VERSION = 1


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def registry_path() -> Path:
    """Resolve the user-level registry path.

    `ORTIM_HOME` env var override is the test injection point; missing
    var falls back to `~/.ortim/`. The path is computed on every call so
    test monkeypatching takes effect mid-process.
    """
    home = os.getenv("ORTIM_HOME")
    if home:
        return Path(home) / "registry.json"
    return Path.home() / ".ortim" / "registry.json"


class WorkspaceEntry(BaseModel):
    """A single row in the registry. Mirrors what `ortim ls` needs to render."""

    id: str
    name: str
    path: str  # absolute path; resolver re-resolves to Path on read
    mode: str = WorkspaceMode.PROJECT.value
    kind: str = "active"
    state: str | None = None
    created_at: str = Field(default_factory=_utcnow)
    last_active: str = Field(default_factory=_utcnow)


class Registry(BaseModel):
    """In-memory registry image. Write back via `save()`."""

    version: int = REGISTRY_VERSION
    current: str | None = None
    workspaces: dict[str, WorkspaceEntry] = Field(default_factory=dict)

    # ---------- I/O ----------

    @classmethod
    def load(cls) -> "Registry":
        """Read `~/.ortim/registry.json`. Returns empty registry if missing
        or corrupt — the caller never has to think about file-not-found.
        """
        path = registry_path()
        if not path.exists():
            return cls()
        try:
            return cls.model_validate_json(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return cls()

    def save(self) -> Path:
        """Write the registry to disk. Creates parent dirs if needed."""
        path = registry_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.model_dump_json(indent=2), encoding="utf-8")
        return path

    # ---------- mutations ----------

    def upsert(
        self,
        location: WorkspaceLocation,
        name: str,
        state: str | None = None,
        kind: str = "active",
    ) -> WorkspaceEntry:
        """Insert or update an entry for `location`. Returns the new entry.

        Identity: project-mode uses `location.id` if set, else falls back
        to `name` (slug). Pool-mode entries use `location.id` (uuid).
        """
        entry_id = location.id or name
        existing = self.workspaces.get(entry_id)
        entry = WorkspaceEntry(
            id=entry_id,
            name=name,
            path=str(location.path),
            mode=location.mode.value,
            kind=existing.kind if existing else kind,
            state=state,
            created_at=existing.created_at if existing else _utcnow(),
            last_active=_utcnow(),
        )
        self.workspaces[entry_id] = entry
        return entry

    def remove(self, entry_id: str) -> bool:
        """Drop an entry. Returns True if it existed."""
        gone = self.workspaces.pop(entry_id, None) is not None
        if self.current == entry_id:
            self.current = None
        return gone

    def set_current(self, entry_id: str) -> None:
        """Mark `entry_id` as the active workspace.

        Raises KeyError if the id is not registered — caller should add it
        first via `upsert`.
        """
        if entry_id not in self.workspaces:
            raise KeyError(f"workspace {entry_id!r} not in registry")
        self.current = entry_id

    def touch(self, entry_id: str) -> None:
        """Update `last_active` for an existing entry. No-op if missing."""
        entry = self.workspaces.get(entry_id)
        if entry is None:
            return
        # Pydantic models are immutable by default; clone with override.
        self.workspaces[entry_id] = entry.model_copy(update={"last_active": _utcnow()})

    # ---------- queries ----------

    def get(self, key: str) -> WorkspaceEntry | None:
        """Lookup by id first, then by name."""
        if key in self.workspaces:
            return self.workspaces[key]
        for entry in self.workspaces.values():
            if entry.name == key:
                return entry
        return None

    def entries(self) -> list[WorkspaceEntry]:
        """All registered entries, sorted by `last_active` descending."""
        return sorted(
            self.workspaces.values(),
            key=lambda e: e.last_active,
            reverse=True,
        )

    def prune_missing(self) -> list[str]:
        """Drop entries whose path or state.json no longer exists.

        Returns the list of removed ids so the caller can surface them in
        `ortim ls` output (similar to git's "branch -v --no-merged" hint).
        """
        removed: list[str] = []
        for entry_id, entry in list(self.workspaces.items()):
            workspace_path = Path(entry.path)
            state_file = (
                workspace_path / ".ortim" / "state.json"
                if entry.mode == WorkspaceMode.PROJECT.value
                else workspace_path / "state.json"
            )
            if not state_file.exists():
                removed.append(entry_id)
                self.workspaces.pop(entry_id, None)
                if self.current == entry_id:
                    self.current = None
        return removed


def register_workspace(
    location: WorkspaceLocation,
    name: str,
    state: str | None = None,
    kind: str = "active",
    set_current: bool = True,
) -> WorkspaceEntry:
    """Top-level convenience: load registry, upsert, optionally set current,
    save. Used by `ortim init` and other workspace-creating commands."""
    reg = Registry.load()
    entry = reg.upsert(location, name=name, state=state, kind=kind)
    if set_current:
        reg.current = entry.id
    reg.save()
    return entry


def touch_workspace(entry_id: str) -> None:
    """Bump `last_active` for an entry (best-effort, swallows errors)."""
    try:
        reg = Registry.load()
        reg.touch(entry_id)
        reg.save()
    except Exception:
        pass


def scan_pool_workspaces(pool_root: Path) -> Iterable[tuple[str, Path]]:
    """Yield (id, workspace_path) for every legacy pool workspace.

    Used by `ortim ls` to surface unregistered pool entries alongside
    registered ones until the user runs `ortim workspace migrate` for them.
    """
    if not pool_root.exists() or not pool_root.is_dir():
        return
    for child in pool_root.iterdir():
        if not child.is_dir():
            continue
        if not (child / "state.json").exists():
            continue
        yield child.name, child
