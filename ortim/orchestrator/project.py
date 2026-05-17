# SPDX-License-Identifier: FSL-1.1-Apache-2.0
# Copyright (c) 2026 ortim.dev
"""Project lifecycle - persistent state per workspace.

Multi-tenant readiness (M1 — Gun 0):

  * `tenant_id` is threaded through the path resolver, model, and load/save
    API. The default tenant ("default") preserves the legacy path layout
    `<root>/<project_id>/` so existing workspaces remain reachable. Non-default
    tenants nest under `<root>/<tenant_id>/<project_id>/`.
  * Authentication, authorization, per-tenant rate limits, and tenant-aware
    LLM key mapping are out of scope for the FSL core; they belong in
    `enterprise/` (M5+).
"""

from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from pydantic import BaseModel, Field

from ortim.orchestrator.state_machine import (
    HITL_GATES,
    ProjectState,
    validate_transition,
)

DEFAULT_TENANT = "default"


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


class StateEvent(BaseModel):
    timestamp: str
    from_state: ProjectState
    to_state: ProjectState
    actor: str
    note: str = ""


class Project(BaseModel):
    id: str = Field(default_factory=lambda: uuid4().hex[:12])
    name: str
    initial_brief_tr: str
    state: ProjectState = ProjectState.INTAKE
    history: list[StateEvent] = Field(default_factory=list)
    created_at: str = Field(default_factory=_utcnow)
    tenant_id: str = DEFAULT_TENANT

    # M1 brownfield extension. Default values reproduce the legacy greenfield
    # behavior — older state.json files load unchanged.
    is_brownfield: bool = False
    app_class: str = "web"
    source_path: str | None = None  # absolute path to user's repo, when brownfield

    @staticmethod
    def workspace_path(
        project_id: str,
        root: Path,
        tenant_id: str = DEFAULT_TENANT,
    ) -> Path:
        """Resolve the workspace path for a given (tenant, project) pair.

        Default tenant uses legacy layout so pre-tenant workspaces remain
        valid. Explicit tenants get an enclosing directory.
        """
        if tenant_id == DEFAULT_TENANT:
            return root / project_id
        return root / tenant_id / project_id

    @classmethod
    def load(
        cls,
        project_id: str,
        root: Path,
        tenant_id: str = DEFAULT_TENANT,
    ) -> "Project":
        path = cls.workspace_path(project_id, root, tenant_id) / "state.json"
        return cls.model_validate_json(path.read_text(encoding="utf-8"))

    def save(self, root: Path, tenant_id: str | None = None) -> None:
        """Persist state.json. If `tenant_id` is omitted, use `self.tenant_id`."""
        effective = tenant_id if tenant_id is not None else self.tenant_id
        ws = self.workspace_path(self.id, root, effective)
        ws.mkdir(parents=True, exist_ok=True)
        (ws / "state.json").write_text(
            self.model_dump_json(indent=2), encoding="utf-8"
        )

    def transition(self, target: ProjectState, actor: str, note: str = "") -> None:
        validate_transition(self.state, target)
        self.history.append(
            StateEvent(
                timestamp=_utcnow(),
                from_state=self.state,
                to_state=target,
                actor=actor,
                note=note,
            )
        )
        self.state = target

    def awaiting_human(self) -> str | None:
        return HITL_GATES.get(self.state)


def _link_or_copy(src: Path, dst: Path, link_mode: str) -> str:
    """Materialize `src` at `dst`. Returns the actual mode used.

    Symlink mode requires Windows Developer Mode (or admin); a typical
    Windows install fails with OSError([WinError 1314]). We catch and fall
    back to a recursive copy so brownfield bootstrap stays usable on default
    machines — the caller surfaces a warning.
    """
    if dst.exists():
        raise FileExistsError(f"destination already exists: {dst}")
    dst.parent.mkdir(parents=True, exist_ok=True)
    if link_mode == "copy":
        shutil.copytree(src, dst)
        return "copy"
    if link_mode != "symlink":
        raise ValueError(f"unknown link_mode {link_mode!r}; use 'symlink' or 'copy'")
    try:
        dst.symlink_to(src, target_is_directory=True)
        return "symlink"
    except (OSError, NotImplementedError):
        shutil.copytree(src, dst)
        return "copy-fallback"


def bootstrap_brownfield(
    name: str,
    brief_tr: str,
    source_path: Path,
    workspace_root: Path,
    tenant_id: str = DEFAULT_TENANT,
    link_mode: str = "symlink",
    capture_baseline_on_bootstrap: bool = True,
) -> tuple[Project, str]:
    """Create a new project from an existing codebase.

    Bootstrap order:
      1. Create the Project + workspace dir
      2. Materialize source_path → workspace/source (symlink or copy)
      3. scan_codebase → .cache/codebase.json
      4. baseline.capture (if a test command auto-detects) → .cache/baseline.json
      5. Detect app_class hint from the summary
      6. Write intent.json stub (Babel is skipped on this path)
      7. Transition INTAKE → PRD_DRAFTING

    Returns (project, materialization_mode) where `mode` is one of
    "symlink", "copy", "copy-fallback" — the caller surfaces this so the
    operator knows whether they got the fast or the safe path.
    """
    # Imported lazily because ortim.codebase imports pydantic schemas that
    # don't need to be loaded for greenfield CLI flows.
    from ortim.codebase import (
        capture_baseline,
        detect_test_cmd,
        scan_codebase,
        write_baseline,
    )

    src_resolved = Path(source_path).resolve()
    if not src_resolved.exists() or not src_resolved.is_dir():
        raise FileNotFoundError(
            f"source path does not exist or is not a directory: {src_resolved}"
        )

    project = Project(
        name=name,
        initial_brief_tr=brief_tr,
        is_brownfield=True,
        source_path=str(src_resolved),
        tenant_id=tenant_id,
    )
    workspace = Project.workspace_path(project.id, workspace_root, tenant_id)
    workspace.mkdir(parents=True, exist_ok=True)

    source_dst = workspace / "source"
    actual_mode = _link_or_copy(src_resolved, source_dst, link_mode)

    cache_dir = workspace / ".cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    summary = scan_codebase(source_dst, cache_path=cache_dir / "codebase.json")
    (cache_dir / "codebase.json").write_text(
        summary.model_dump_json(indent=2), encoding="utf-8"
    )

    if capture_baseline_on_bootstrap and detect_test_cmd(source_dst):
        try:
            baseline = capture_baseline(source_dst)
            write_baseline(cache_dir, baseline)
        except RuntimeError:
            # Detection found no command — already filtered by the if above,
            # but capture() may still raise if the manifest goes missing
            # between detect and capture (race). Skip baseline silently.
            pass

    project.app_class = summary.app_class_hint or "web"

    # Babel skip — write a stub intent.json so downstream readers don't
    # see a missing file. The schema mirrors what Babel would have produced.
    intent = {
        "goal": "existing-codebase",
        "brief_tr": brief_tr,
        "app_class": project.app_class,
    }
    (workspace / "intent.json").write_text(
        json.dumps(intent, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    project.transition(
        ProjectState.PRD_DRAFTING,
        actor="bootstrap_brownfield",
        note=f"source={src_resolved} mode={actual_mode}",
    )
    project.save(workspace_root, tenant_id)
    return project, actual_mode
