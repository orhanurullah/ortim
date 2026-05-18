# SPDX-License-Identifier: FSL-1.1-Apache-2.0
# Copyright (c) 2026 ortim.dev
"""Layout-agnostic Project state persistence.

`ProjectStore` reads and writes `state.json` for a workspace without the
caller having to know whether the layout is project mode (`.ortim/state.json`)
or legacy pool (`state.json` flat). All CLI command handlers should resolve
a `WorkspaceLocation` first, then go through this store rather than calling
`Project.load(id, root)` directly.

The legacy `Project.load(id, root)` API remains for backward compatibility —
test fixtures and pool-mode callers still use it. The store is a thin wrapper
that consolidates the two layouts under one read/write surface.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ortim.orchestrator.project import Project
from ortim.workspace.resolver import WorkspaceLocation, WorkspaceMode


class ProjectStore:
    """Mode-aware persistence for a single workspace.

    Construct with a `WorkspaceLocation`; reuse the same store instance for
    the lifetime of a CLI command. The store does not cache state across
    instances — each `load` re-reads from disk.
    """

    def __init__(self, location: WorkspaceLocation) -> None:
        self.location = location

    @property
    def metadata_dir(self) -> Path:
        return self.location.metadata_dir

    @property
    def state_file(self) -> Path:
        return self.location.state_file

    def artifact_path(self, filename: str) -> Path:
        """Resolve an artifact file (PRD.md, intent.json, task_dag.json, ...).

        Project mode → `<path>/.ortim/<filename>`
        Pool mode    → `<path>/<filename>` (legacy flat layout)
        """
        return self.metadata_dir / filename

    def audit_log_path(self) -> Path:
        """Per-project audit log path.

        Project mode → `<path>/.ortim/audit.jsonl`
        Pool mode    → `<path>/audit.jsonl` (legacy flat layout)
        """
        return self.metadata_dir / "audit.jsonl"

    def exists(self) -> bool:
        return self.state_file.exists()

    def load(self) -> Project:
        """Read state.json into a Project model.

        Binds the project's `_metadata_dir` to this store's metadata dir so
        downstream `project.save(WORKSPACE_ROOT)` calls land in the right
        place under both project mode and pool mode. The bind is harmless
        for pool mode (metadata_dir == workspace path → equivalent target).
        """
        if not self.state_file.exists():
            raise FileNotFoundError(
                f"No state.json at {self.state_file} "
                f"(mode={self.location.mode.value})"
            )
        project = Project.model_validate_json(
            self.state_file.read_text(encoding="utf-8")
        )
        project.bind_metadata_dir(self.metadata_dir)
        return project

    def save(self, project: Project) -> None:
        """Write state.json + ensure metadata dir exists."""
        self.metadata_dir.mkdir(parents=True, exist_ok=True)
        self.state_file.write_text(
            project.model_dump_json(indent=2), encoding="utf-8"
        )

    def write_artifact(self, filename: str, content: str) -> Path:
        """Write a text artifact (PRD.md, RFC.md, ...) inside the metadata dir."""
        self.metadata_dir.mkdir(parents=True, exist_ok=True)
        path = self.artifact_path(filename)
        path.write_text(content, encoding="utf-8")
        return path

    def write_json(self, filename: str, data: Any) -> Path:
        """Write a JSON artifact."""
        self.metadata_dir.mkdir(parents=True, exist_ok=True)
        path = self.artifact_path(filename)
        path.write_text(
            json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        return path

    def read_artifact(self, filename: str) -> str | None:
        """Read a text artifact; returns None when missing."""
        path = self.artifact_path(filename)
        if not path.exists():
            return None
        return path.read_text(encoding="utf-8")

    def read_json(self, filename: str) -> Any | None:
        """Read a JSON artifact; returns None when missing or invalid."""
        path = self.artifact_path(filename)
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    @classmethod
    def for_new_project_mode(cls, path: Path) -> "ProjectStore":
        """Construct a store anchored at `path` for a fresh project-mode workspace.

        Used by `ortim init` before any `.ortim/state.json` exists. The caller
        is responsible for actually invoking `save(project)` after building
        the Project model — this just sets up the location.
        """
        location = WorkspaceLocation(path=path.resolve(), mode=WorkspaceMode.PROJECT)
        return cls(location)
