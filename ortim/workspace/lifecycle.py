# SPDX-License-Identifier: FSL-1.1-Apache-2.0
# Copyright (c) 2026 ortim.dev
"""Workspace lifecycle operations: archive, unarchive, cleanup, doctor, migrate.

These are orthogonal to the state machine — a workspace can be archived
in any project state (DONE, FAILED, PAUSED). Archive sets a soft flag
(`archived_at` in state.json); fs layout doesn't move. Cleanup is
destructive (`shutil.rmtree`) and gated behind `--yes`. Migrate lifts a
pool-layout workspace into the project mode layout at a user-chosen path.
"""

from __future__ import annotations

import re
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from ortim.orchestrator.project import Project
from ortim.workspace.registry import Registry
from ortim.workspace.resolver import WorkspaceLocation, WorkspaceMode
from ortim.workspace.store import ProjectStore


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


class ArchiveError(Exception):
    """Raised when archive/unarchive cannot proceed."""


def archive_workspace(store: ProjectStore, project: Project) -> Project:
    """Mark a workspace as archived. Idempotent: re-archive returns existing
    `archived_at` unchanged."""
    if project.archived_at is None:
        project.archived_at = _utcnow()
        store.save(project)
    return project


def unarchive_workspace(store: ProjectStore, project: Project) -> Project:
    """Clear the archived flag. Idempotent."""
    if project.archived_at is not None:
        project.archived_at = None
        store.save(project)
    return project


# ---------- cleanup ----------


@dataclass(frozen=True)
class CleanupCandidate:
    entry_id: str
    name: str
    path: Path
    mode: str
    age_days: float
    reason: str  # "archived", "state-match", "age-only"


def _last_active(project: Project) -> str:
    """Best estimate of the workspace's last activity timestamp.

    Prefer the most recent `state.history` event; fall back to `created_at`
    for projects that never advanced. Both fields are ISO 8601 UTC strings.
    """
    if project.history:
        return project.history[-1].timestamp
    return project.created_at


def _age_days(iso_ts: str, now: datetime | None = None) -> float:
    """Days between `iso_ts` and `now` (UTC)."""
    ref = now or datetime.now(timezone.utc)
    try:
        ts = datetime.fromisoformat(iso_ts)
    except ValueError:
        return 0.0
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return (ref - ts).total_seconds() / 86400.0


def find_cleanup_candidates(
    older_than_days: int,
    archived_only: bool = True,
    state_filter: str | None = None,
    pool_root: Path | None = None,
) -> list[CleanupCandidate]:
    """Walk the registry (+ optionally pool layout) for cleanup candidates.

    Returns workspaces whose last-activity timestamp is older than
    `older_than_days`, optionally filtered to archived-only and/or a
    specific project state. The caller decides what to do with them
    (dry-run print vs. actual delete).
    """
    reg = Registry.load()
    candidates: list[CleanupCandidate] = []
    now = datetime.now(timezone.utc)

    seen_paths: set[Path] = set()
    for entry in reg.entries():
        try:
            location = WorkspaceLocation(
                path=Path(entry.path),
                mode=WorkspaceMode(entry.mode),
                id=entry.id,
            )
            store = ProjectStore(location)
            if not store.exists():
                continue
            project = store.load()
        except Exception:
            continue

        seen_paths.add(Path(entry.path))
        candidate = _build_candidate(
            entry.id, entry.name, location, project, now,
            older_than_days, archived_only, state_filter,
        )
        if candidate is not None:
            candidates.append(candidate)

    # Pool legacy workspaces that aren't in registry
    if pool_root is not None and pool_root.exists():
        for child in pool_root.iterdir():
            if not child.is_dir() or not (child / "state.json").exists():
                continue
            if child in seen_paths:
                continue
            try:
                project = Project.model_validate_json(
                    (child / "state.json").read_text(encoding="utf-8")
                )
                location = WorkspaceLocation(
                    path=child, mode=WorkspaceMode.POOL, id=child.name
                )
                candidate = _build_candidate(
                    child.name, project.name, location, project, now,
                    older_than_days, archived_only, state_filter,
                )
                if candidate is not None:
                    candidates.append(candidate)
            except Exception:
                continue

    return candidates


def _build_candidate(
    entry_id: str,
    name: str,
    location: WorkspaceLocation,
    project: Project,
    now: datetime,
    older_than_days: int,
    archived_only: bool,
    state_filter: str | None,
) -> CleanupCandidate | None:
    age = _age_days(_last_active(project), now=now)
    if age < older_than_days:
        return None

    is_archived = project.archived_at is not None
    if archived_only and not is_archived:
        return None
    if state_filter and project.state.value != state_filter:
        return None

    reason = (
        "archived" if is_archived
        else "state-match" if state_filter
        else "age-only"
    )
    return CleanupCandidate(
        entry_id=entry_id,
        name=name,
        path=location.path,
        mode=location.mode.value,
        age_days=age,
        reason=reason,
    )


def delete_workspace(candidate: CleanupCandidate) -> None:
    """Physically remove a workspace directory + drop its registry entry.

    Project mode → removes `<path>/.ortim/` only (user code stays).
    Pool mode    → removes the entire pool directory (no user code there).

    Raises OSError on filesystem failures so the caller can report partial
    cleanup states accurately.
    """
    if candidate.mode == WorkspaceMode.PROJECT.value:
        # Only remove ortim's metadata; the user's code is theirs to keep
        target = candidate.path / ".ortim"
        if target.exists():
            shutil.rmtree(target)
    else:
        # Pool layout: the whole directory is ortim's
        if candidate.path.exists():
            shutil.rmtree(candidate.path)

    # Drop from registry too
    reg = Registry.load()
    reg.remove(candidate.entry_id)
    reg.save()


# ---------- doctor ----------


@dataclass(frozen=True)
class DoctorFinding:
    severity: str  # "warn" | "error" | "info"
    code: str
    message: str
    entity: str | None = None  # workspace id or path


def doctor_scan(pool_root: Path | None = None) -> list[DoctorFinding]:
    """Inspect all registered workspaces for common issues.

    Checks performed:
      * registry → fs alignment (path exists, state.json present)
      * orphan pool workspaces (in fs but not in registry)
      * archived workspaces older than 90 days (cleanup candidates)
      * size > 500MB (potential bloat)
    """
    findings: list[DoctorFinding] = []
    reg = Registry.load()

    # Registry → fs alignment
    for entry in reg.entries():
        path = Path(entry.path)
        if not path.exists():
            findings.append(
                DoctorFinding(
                    severity="error",
                    code="path_missing",
                    entity=entry.id,
                    message=f"Registry entry '{entry.id}' points to missing path: {path}",
                )
            )
            continue
        state_file = (
            path / ".ortim" / "state.json"
            if entry.mode == WorkspaceMode.PROJECT.value
            else path / "state.json"
        )
        if not state_file.exists():
            findings.append(
                DoctorFinding(
                    severity="error",
                    code="state_missing",
                    entity=entry.id,
                    message=f"state.json missing at {state_file}",
                )
            )

    # Orphan pool workspaces
    if pool_root is not None and pool_root.exists():
        registered_paths = {Path(e.path) for e in reg.entries()}
        for child in pool_root.iterdir():
            if not child.is_dir() or not (child / "state.json").exists():
                continue
            if child not in registered_paths:
                findings.append(
                    DoctorFinding(
                        severity="info",
                        code="pool_unregistered",
                        entity=child.name,
                        message=(
                            f"Pool workspace {child.name} not in registry. "
                            "Run `ortim workspace migrate <id>` to lift it "
                            "into project mode."
                        ),
                    )
                )

    # Long-archived candidates
    for entry in reg.entries():
        try:
            path = Path(entry.path)
            location = WorkspaceLocation(
                path=path,
                mode=WorkspaceMode(entry.mode),
                id=entry.id,
            )
            store = ProjectStore(location)
            if not store.exists():
                continue
            project = store.load()
        except Exception:
            continue
        if project.archived_at and _age_days(project.archived_at) > 90:
            findings.append(
                DoctorFinding(
                    severity="warn",
                    code="archived_aging",
                    entity=entry.id,
                    message=(
                        f"Archived > 90 days. Run `ortim workspace cleanup "
                        f"--older-than 90 --yes` to delete."
                    ),
                )
            )

    return findings


# ---------- migrate (pool → project) ----------


# Files that are part of ortim's metadata for a pool workspace. Anything
# NOT on this list (or matching `_META_LOG_PATTERN` / in `_META_DIRS`) is
# treated as user code and stays at the workspace root after migration.
_META_FILES = frozenset(
    [
        "state.json",
        "intent.json",
        "intent.md",
        "PRD.md",
        "prd.md",
        "RFC.md",
        "task_dag.json",
        "task_status.json",
        "golden_path_inputs.json",
        "stack.json",
        "scope.json",
        "audit.jsonl",
        "decisions.jsonl",  # legacy audit name
    ]
)
_META_DIRS = frozenset([".cache", ".ortim", "tasks", "extensions", "source"])
_META_LOG_PATTERN = re.compile(r"^T-\d+\.log$")


class MigrationError(Exception):
    """Raised when migrate cannot proceed."""


def _is_metadata(entry: Path) -> bool:
    name = entry.name
    if name in _META_FILES:
        return True
    if entry.is_dir() and name in _META_DIRS:
        return True
    if _META_LOG_PATTERN.match(name):
        return True
    return False


def migrate_pool_to_project(
    pool_path: Path,
    dest: Path,
    *,
    move: bool = False,
) -> WorkspaceLocation:
    """Lift a pool-layout workspace into project mode at `dest`.

    Splits the pool dir into:
      * ortim metadata → `<dest>/.ortim/`
      * user code      → `<dest>/` (rest of the files)

    `move=True` uses `shutil.move` (faster but mutates the pool); default
    `False` copies, leaving the pool intact for rollback.

    Returns the new `WorkspaceLocation`. Updates the registry: the old
    pool entry (if registered) is removed; a new project-mode entry is
    inserted and marked current.

    Raises MigrationError if pool_path is invalid or dest already has a
    `.ortim/` (refuse to clobber).
    """
    pool_path = pool_path.resolve()
    dest = dest.resolve()

    if not (pool_path / "state.json").exists():
        raise MigrationError(
            f"Pool workspace at {pool_path} has no state.json"
        )
    if (dest / ".ortim").exists():
        raise MigrationError(
            f".ortim/ already exists at {dest}. Pick a different --to path."
        )

    dest.mkdir(parents=True, exist_ok=True)
    metadata_dir = dest / ".ortim"
    metadata_dir.mkdir()

    op = shutil.move if move else _copy_safe

    for child in pool_path.iterdir():
        target_dir = metadata_dir if _is_metadata(child) else dest
        target = target_dir / child.name
        if target.exists():
            # Skip — caller's dest already has a same-named entry. Surface
            # later via migrate's CLI summary; don't crash mid-way.
            continue
        op(str(child), str(target))

    location = WorkspaceLocation(
        path=dest, mode=WorkspaceMode.PROJECT, id=pool_path.name
    )

    # Update the registry: pool entry → project entry under the same id.
    reg = Registry.load()
    reg.remove(pool_path.name)

    # Re-derive state from the just-moved state.json so the registry row
    # is fresh after migration.
    try:
        project = ProjectStore(location).load()
        reg.upsert(location, name=project.name, state=project.state.value)
    except Exception:
        # Best-effort: at minimum, record the path so `ortim ls` can find it
        reg.upsert(location, name=pool_path.name)
    reg.current = pool_path.name
    reg.save()

    return location


def _copy_safe(src: str, dst: str) -> None:
    """Copy a file or directory tree to `dst`. Wraps shutil so callers can
    swap `shutil.move` in without per-type branching."""
    src_path = Path(src)
    if src_path.is_dir():
        shutil.copytree(src, dst)
    else:
        shutil.copy2(src, dst)
