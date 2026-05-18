# SPDX-License-Identifier: FSL-1.1-Apache-2.0
# Copyright (c) 2026 ortim.dev
"""Tests for `ortim.workspace.init.init_project` and brownfield auto-detection."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ortim.orchestrator.state_machine import ProjectState
from ortim.workspace.init import (
    InitError,
    detect_brownfield,
    init_project,
)


# ---------------- detect_brownfield ----------------


def test_detect_brownfield_empty_dir_returns_false(tmp_path: Path) -> None:
    assert detect_brownfield(tmp_path) is False


@pytest.mark.parametrize(
    "manifest",
    [
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
    ],
)
def test_detect_brownfield_manifest_files_trigger(tmp_path: Path, manifest: str) -> None:
    (tmp_path / manifest).write_text("{}", encoding="utf-8")
    assert detect_brownfield(tmp_path) is True


@pytest.mark.parametrize("source_dir", ["src", "lib", "app"])
def test_detect_brownfield_source_dirs_trigger(tmp_path: Path, source_dir: str) -> None:
    (tmp_path / source_dir).mkdir()
    assert detect_brownfield(tmp_path) is True


def test_detect_brownfield_readme_only_is_greenfield(tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text("# project", encoding="utf-8")
    assert detect_brownfield(tmp_path) is False


# ---------------- init_project — greenfield ----------------


def test_init_greenfield_creates_dot_ortim(tmp_path: Path) -> None:
    project, location, is_brownfield = init_project(
        cwd=tmp_path, brief="todo yöneticisi"
    )
    assert is_brownfield is False
    assert location.mode.value == "project"
    assert (tmp_path / ".ortim" / "state.json").exists()
    assert project.state == ProjectState.INTAKE  # no transition for greenfield
    assert project.name == tmp_path.name  # default name from cwd


def test_init_greenfield_uses_explicit_name(tmp_path: Path) -> None:
    project, _, _ = init_project(
        cwd=tmp_path, brief="todo", name="my-todo"
    )
    assert project.name == "my-todo"


def test_init_greenfield_no_intent_json_written(tmp_path: Path) -> None:
    init_project(cwd=tmp_path, brief="todo")
    # Greenfield path lets Babel write intent.json later — init does not seed.
    assert not (tmp_path / ".ortim" / "intent.json").exists()


# ---------------- init_project — brownfield ----------------


def test_init_brownfield_auto_detects_from_manifest(tmp_path: Path) -> None:
    (tmp_path / "package.json").write_text(
        json.dumps({"name": "todo-app"}), encoding="utf-8"
    )
    project, _, is_brownfield = init_project(cwd=tmp_path, brief="todo")
    assert is_brownfield is True
    assert project.is_brownfield is True
    assert project.source_path == str(tmp_path.resolve())
    assert project.state == ProjectState.PRD_DRAFTING  # transitioned past INTAKE


def test_init_brownfield_writes_intent_stub(tmp_path: Path) -> None:
    (tmp_path / "package.json").write_text("{}", encoding="utf-8")
    init_project(cwd=tmp_path, brief="todo brief")
    intent = json.loads((tmp_path / ".ortim" / "intent.json").read_text(encoding="utf-8"))
    assert intent["goal"] == "existing-codebase"
    assert intent["brief_tr"] == "todo brief"
    assert "app_class" in intent


def test_init_brownfield_writes_codebase_cache(tmp_path: Path) -> None:
    (tmp_path / "package.json").write_text(
        json.dumps({"name": "x"}), encoding="utf-8"
    )
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "index.js").write_text("export const x = 1;", encoding="utf-8")
    init_project(cwd=tmp_path, brief="todo")
    cache = tmp_path / ".ortim" / ".cache" / "codebase.json"
    assert cache.exists()


def test_init_force_brownfield_on_empty_dir(tmp_path: Path) -> None:
    project, _, is_brownfield = init_project(
        cwd=tmp_path, brief="todo", force_brownfield=True
    )
    assert is_brownfield is True
    # Codebase scan succeeded even though dir is essentially empty
    assert project.state == ProjectState.PRD_DRAFTING


def test_init_force_greenfield_when_manifest_present(tmp_path: Path) -> None:
    (tmp_path / "package.json").write_text("{}", encoding="utf-8")
    project, _, is_brownfield = init_project(
        cwd=tmp_path, brief="todo", force_brownfield=False
    )
    assert is_brownfield is False
    assert project.is_brownfield is False
    assert project.state == ProjectState.INTAKE


# ---------------- init_project — error paths ----------------


def test_init_refuses_when_dot_ortim_already_exists(tmp_path: Path) -> None:
    (tmp_path / ".ortim").mkdir()
    (tmp_path / ".ortim" / "state.json").write_text("{}", encoding="utf-8")
    with pytest.raises(InitError, match=r"already exists"):
        init_project(cwd=tmp_path, brief="x")


def test_init_audit_log_path_is_under_dot_ortim(tmp_path: Path) -> None:
    """Locks the per-project audit log location contract."""
    _, location, _ = init_project(cwd=tmp_path, brief="todo")
    expected = tmp_path / ".ortim" / "audit.jsonl"
    assert location.metadata_dir / "audit.jsonl" == expected
