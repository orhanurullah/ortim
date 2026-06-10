# SPDX-License-Identifier: FSL-1.1-Apache-2.0
# Copyright (c) 2026 ortim.dev
"""`ortim init` backend — project mode workspace creation in cwd.

Replaces the legacy `ortim new` + `ortim new --from-existing` pair with a
single cwd-aware entry point that auto-detects brownfield vs greenfield
from the directory's contents.

Detection heuristic (any one matches → brownfield):
  - manifest file present: package.json, pyproject.toml, Cargo.toml,
    go.mod, pubspec.yaml, Gemfile, requirements.txt, setup.py
  - source-tree marker present: src/, lib/, app/

The greenfield path skips codebase scan + baseline capture; state machine
enters INTAKE and then BABEL_PROCESSING via `ortim run`. The brownfield
path scans cwd, writes `.ortim/.cache/codebase.json`, and transitions
INTAKE → PRD_DRAFTING (Babel skipped, user owns the PRD seed).
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from ortim.babel import app_class_from_brief
from ortim.orchestrator.project import Project
from ortim.orchestrator.state_machine import ProjectState
from ortim.workspace.resolver import WorkspaceLocation, WorkspaceMode
from ortim.workspace.store import ProjectStore

_VALID_APP_CLASSES = ("web", "mobile", "desktop")


_BROWNFIELD_MANIFEST_FILES = (
    "package.json",
    "pyproject.toml",
    "Cargo.toml",
    "go.mod",
    "pubspec.yaml",
    "Gemfile",
    "requirements.txt",
    "setup.py",
    "build.gradle",
    "build.gradle.kts",
    "pom.xml",
)
_BROWNFIELD_SOURCE_DIRS = ("src", "lib", "app")


class InitError(Exception):
    """Raised when `ortim init` cannot proceed."""


def detect_brownfield(cwd: Path) -> bool:
    """Heuristic check for an existing codebase in `cwd`.

    Returns True if a known manifest or source-tree marker is present.
    Order matters only for explanation — any single hit flips the bool.
    """
    for manifest in _BROWNFIELD_MANIFEST_FILES:
        if (cwd / manifest).exists():
            return True
    for source_dir in _BROWNFIELD_SOURCE_DIRS:
        if (cwd / source_dir).is_dir():
            return True
    return False


def _default_name_from_path(cwd: Path) -> str:
    """Use the cwd directory name as the project's short name."""
    name = cwd.name or "ortim-project"
    return name


def init_project(
    cwd: Path,
    brief: str,
    name: str | None = None,
    force_brownfield: bool | None = None,
    app_class_override: str | None = None,
) -> tuple[Project, WorkspaceLocation, bool]:
    """Initialize a project-mode workspace at `cwd`.

    Returns (project, location, is_brownfield). Raises InitError if `.ortim/`
    already exists (idempotency is the caller's job — pass `--force` upstream
    if reinitialization is intended; this helper refuses to overwrite).

    `force_brownfield` overrides auto-detection (True forces brownfield,
    False forces greenfield, None auto-detects).

    `app_class_override` (web|mobile|desktop) hard-locks app_class. When
    set, downstream Babel/LLM picks cannot flip it. When None, init scans
    the brief for explicit platform terms (`mobil uygulama`, `Android`,
    `desktop`, …) and seeds state.json with that hint — Babel can still
    refine later.
    """
    cwd = cwd.resolve()
    dot = cwd / ".ortim"
    if dot.exists():
        raise InitError(
            f".ortim/ already exists at {cwd}. Run `ortim status` to see "
            "current state, or remove it manually if you want to start over."
        )

    if app_class_override is not None and app_class_override not in _VALID_APP_CLASSES:
        raise InitError(
            f"--app-class must be one of {', '.join(_VALID_APP_CLASSES)}; "
            f"got '{app_class_override}'."
        )

    is_brownfield = (
        force_brownfield
        if force_brownfield is not None
        else detect_brownfield(cwd)
    )

    location = WorkspaceLocation(path=cwd, mode=WorkspaceMode.PROJECT)
    store = ProjectStore(location)

    # Decide initial app_class up-front so state.json carries the right
    # value from t0. Brownfield path may refine this from the codebase
    # scan in `_seed_brownfield_metadata`; the explicit override locks
    # the result regardless.
    if app_class_override is not None:
        initial_app_class = app_class_override
    else:
        initial_app_class = app_class_from_brief(brief) or "web"

    project = Project(
        name=name or _default_name_from_path(cwd),
        initial_brief_tr=brief,
        is_brownfield=is_brownfield,
        app_class=initial_app_class,
        app_class_explicit=app_class_override is not None,
        source_path=str(cwd) if is_brownfield else None,
    )

    if is_brownfield:
        _seed_brownfield_metadata(store, project, brief, cwd)
    else:
        store.save(project)

    return project, location, is_brownfield


def _seed_brownfield_metadata(
    store: ProjectStore,
    project: Project,
    brief: str,
    cwd: Path,
) -> None:
    """Scan cwd and write the brownfield bootstrap artifacts under `.ortim/`.

    Mirrors `bootstrap_brownfield` minus the materialize step — in project
    mode the user's code already lives at cwd, so we don't symlink or copy
    anywhere; we just scan it and write `.ortim/.cache/codebase.json`.

    On scan failure the workspace is still created (state.json exists) but
    the cache is missing; `ortim rescan` can repair it later.
    """
    from ortim.codebase import (
        capture_baseline,
        detect_test_cmd,
        scan_codebase,
        write_baseline,
    )

    cache_dir = store.metadata_dir / ".cache"
    cache_dir.mkdir(parents=True, exist_ok=True)

    try:
        summary = scan_codebase(cwd, cache_path=cache_dir / "codebase.json")
        (cache_dir / "codebase.json").write_text(
            summary.model_dump_json(indent=2), encoding="utf-8"
        )
        # Resolution order for brownfield app_class:
        #   1. user-locked override (already set on `project` by caller)
        #   2. codebase scan's app_class_hint (Flutter pubspec → mobile, etc.)
        #   3. brief-text heuristic (user wrote "mobil uygulama")
        #   4. existing value (defaults to "web")
        if not project.app_class_explicit:
            project.app_class = (
                summary.app_class_hint
                or app_class_from_brief(brief)
                or project.app_class
                or "web"
            )
    except (FileNotFoundError, NotADirectoryError):
        # Should not happen — we already validated cwd, but stay defensive.
        if not project.app_class_explicit:
            project.app_class = app_class_from_brief(brief) or "web"
        summary = None

    if summary is not None and detect_test_cmd(cwd):
        try:
            baseline = capture_baseline(cwd)
            write_baseline(cache_dir, baseline)
        except RuntimeError:
            pass  # detection raced with manifest removal; safe to skip

    # Babel skip — write a stub intent.json so downstream readers don't trip.
    intent = {
        "goal": "existing-codebase",
        "brief_tr": brief,
        "app_class": project.app_class,
    }
    store.write_json("intent.json", intent)

    project.transition(
        ProjectState.PRD_DRAFTING,
        actor="ortim_init",
        note=f"brownfield in-place at {cwd}",
    )
    store.save(project)
