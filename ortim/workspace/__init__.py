# SPDX-License-Identifier: FSL-1.1-Apache-2.0
# Copyright (c) 2026 ortim.dev
"""Workspace identity, discovery, and storage.

Two layout modes live side by side:

* **project mode** (v0.9+) — metadata under `<user-dir>/.ortim/`. Generated
  user code stays at the workspace root. Discovered via cwd + parent walk
  (git pattern). Created by `ortim init`.

* **pool mode** (legacy v0.8 and earlier) — metadata flat at
  `<repo>/workspaces/<uuid>/state.json`, alongside generated user code.
  Created by the deprecated `ortim new` command. Existing 196 workspaces
  continue to work; `ortim workspace migrate <id> --to <path>` lifts a
  pool workspace into project mode.

The `resolver` module locates a workspace given (optional CLI arg, cwd,
registry pointer). The `store` module reads/writes Project state.json
agnostic of mode, hiding the layout difference from CLI command handlers.
"""

from __future__ import annotations

from ortim.workspace.init import InitError, detect_brownfield, init_project
from ortim.workspace.lifecycle import (
    ArchiveError,
    CleanupCandidate,
    DoctorFinding,
    MigrationError,
    archive_workspace,
    delete_workspace,
    doctor_scan,
    find_cleanup_candidates,
    migrate_pool_to_project,
    unarchive_workspace,
)
from ortim.workspace.registry import (
    Registry,
    WorkspaceEntry,
    register_workspace,
    registry_path,
    scan_pool_workspaces,
    touch_workspace,
)
from ortim.workspace.resolver import (
    WorkspaceLocation,
    WorkspaceMode,
    WorkspaceNotFound,
    discover_from_cwd,
    find_dot_ortim,
    resolve_workspace,
)
from ortim.workspace.store import ProjectStore

__all__ = [
    "ArchiveError",
    "CleanupCandidate",
    "DoctorFinding",
    "InitError",
    "MigrationError",
    "ProjectStore",
    "Registry",
    "WorkspaceEntry",
    "WorkspaceLocation",
    "WorkspaceMode",
    "WorkspaceNotFound",
    "archive_workspace",
    "delete_workspace",
    "detect_brownfield",
    "discover_from_cwd",
    "doctor_scan",
    "find_cleanup_candidates",
    "find_dot_ortim",
    "init_project",
    "migrate_pool_to_project",
    "register_workspace",
    "registry_path",
    "resolve_workspace",
    "scan_pool_workspaces",
    "touch_workspace",
    "unarchive_workspace",
]
