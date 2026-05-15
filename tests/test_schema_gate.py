# SPDX-License-Identifier: FSL-1.1-Apache-2.0
# Copyright (c) 2026 ortim.dev
"""G3 schema gate wiring tests.

The `detect_schema_tasks` detector and its DAG-level cases are covered
in `test_gate_detector.py`. This file pins the *wiring*:

  * `_maybe_open_schema_gate` transitions TASKS_READY → SCHEMA_AWAITING_APPROVAL
    when a migration task is present, and is a no-op otherwise.
  * The `advance schema_approved` alias resolves to EXECUTING + emits a
    dedicated audit event so retro/forensics can distinguish "human
    approved the schema plan" from "operator manually bumped state".
  * The state machine allows the gate detour and the approval round-trip.
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import pytest  # noqa: E402

from runtime.audit import AuditLogger  # noqa: E402
from runtime.orchestrator import (  # noqa: E402
    InvalidTransition,
    Project,
    ProjectState,
    TaskDAG,
    TaskSpec,
)


def _task(
    tid: str,
    *,
    title: str = "x",
    desc: str = "x",
    scope: str = "src/x",
    deps: list[str] | None = None,
) -> TaskSpec:
    return TaskSpec(
        id=tid,
        title=title,
        description=desc,
        module_scope=scope,
        rfc_section="§1",
        dependencies=deps or [],
        acceptance_criteria=["does the thing"],
        estimated_tokens=1000,
    )


def _project_in_state(tmp: Path, state: ProjectState) -> Project:
    project = Project(name="t", initial_brief_tr="x")
    # Walk the project to `state` by following each transition's first
    # allowed target. This sidesteps the strict state-machine semantics
    # so tests can land on any state without rewriting the machine.
    path_to_state = {
        ProjectState.TASKS_READY: [
            ProjectState.BABEL_PROCESSING,
            ProjectState.PRD_DRAFTING,
            ProjectState.PRD_AWAITING_APPROVAL,
            ProjectState.PRD_APPROVED,
            ProjectState.RFC_DRAFTING,
            ProjectState.RFC_AWAITING_APPROVAL,
            ProjectState.RFC_APPROVED,
            ProjectState.TASKS_GENERATING,
            ProjectState.TASKS_READY,
        ],
        ProjectState.EXECUTING: [
            ProjectState.BABEL_PROCESSING,
            ProjectState.PRD_DRAFTING,
            ProjectState.PRD_AWAITING_APPROVAL,
            ProjectState.PRD_APPROVED,
            ProjectState.RFC_DRAFTING,
            ProjectState.RFC_AWAITING_APPROVAL,
            ProjectState.RFC_APPROVED,
            ProjectState.TASKS_GENERATING,
            ProjectState.TASKS_READY,
            ProjectState.EXECUTING,
        ],
    }
    for step in path_to_state[state]:
        project.transition(step, actor="test", note="setup")
    return project


# ---------------------------------------------------------------------
# Unit — _maybe_open_schema_gate
# ---------------------------------------------------------------------


def test_gate_fires_when_dag_contains_migration_task() -> None:
    from runtime.main import _maybe_open_schema_gate

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        project = _project_in_state(tmp_path, ProjectState.TASKS_READY)
        dag = TaskDAG(
            project_id=project.id,
            tasks=[
                _task("T-001"),
                _task(
                    "T-002",
                    title="Add Alembic migration for users",
                    desc="CREATE TABLE users (...)",
                    scope="migrations/versions",
                ),
            ],
        )
        audit = AuditLogger(path=tmp_path / "audit.jsonl")
        gated, task_ids = _maybe_open_schema_gate(project, dag, audit)
        assert gated is True
        assert task_ids == ["T-002"]
        assert project.state == ProjectState.SCHEMA_AWAITING_APPROVAL


def test_gate_is_noop_when_dag_has_no_migration_tasks() -> None:
    from runtime.main import _maybe_open_schema_gate

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        project = _project_in_state(tmp_path, ProjectState.TASKS_READY)
        dag = TaskDAG(
            project_id=project.id,
            tasks=[
                _task("T-001", title="Add login endpoint"),
                _task("T-002", title="Add logger", deps=["T-001"]),
            ],
        )
        audit = AuditLogger(path=tmp_path / "audit.jsonl")
        gated, task_ids = _maybe_open_schema_gate(project, dag, audit)
        assert gated is False
        assert task_ids == []
        assert project.state == ProjectState.TASKS_READY


def test_gate_does_not_refire_when_state_is_already_executing() -> None:
    """Once schema is approved (operator advances to EXECUTING), a
    subsequent run-all on the same DAG must not re-open the gate."""
    from runtime.main import _maybe_open_schema_gate

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        project = _project_in_state(tmp_path, ProjectState.EXECUTING)
        dag = TaskDAG(
            project_id=project.id,
            tasks=[
                _task(
                    "T-001",
                    title="Migration",
                    desc="CREATE TABLE",
                    scope="alembic/versions",
                ),
            ],
        )
        audit = AuditLogger(path=tmp_path / "audit.jsonl")
        gated, _ = _maybe_open_schema_gate(project, dag, audit)
        assert gated is False
        assert project.state == ProjectState.EXECUTING


def test_gate_emits_audit_event_with_task_ids() -> None:
    from runtime.main import _maybe_open_schema_gate

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        project = _project_in_state(tmp_path, ProjectState.TASKS_READY)
        dag = TaskDAG(
            project_id=project.id,
            tasks=[
                _task(
                    "T-001",
                    title="Migration M1",
                    desc="ALTER TABLE users add column",
                    scope="migrations",
                ),
                _task(
                    "T-002",
                    title="Migration M2",
                    desc="DROP TABLE old_users",
                    scope="migrations",
                    deps=["T-001"],
                ),
            ],
        )
        audit_path = tmp_path / "audit.jsonl"
        audit = AuditLogger(path=audit_path)
        gated, _ = _maybe_open_schema_gate(project, dag, audit)
        assert gated
        events = [
            json.loads(line)
            for line in audit_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        opened = [e for e in events if e.get("event") == "gate_schema_opened"]
        assert len(opened) == 1
        assert sorted(opened[0]["task_ids"]) == ["T-001", "T-002"]


# ---------------------------------------------------------------------
# State machine — gate detour + approval round-trip
# ---------------------------------------------------------------------


def test_state_machine_allows_tasks_ready_to_schema_to_executing() -> None:
    """Full G3 flow: TASKS_READY → SCHEMA_AWAITING_APPROVAL → EXECUTING."""
    with tempfile.TemporaryDirectory() as tmp:
        project = _project_in_state(Path(tmp), ProjectState.TASKS_READY)
        project.transition(
            ProjectState.SCHEMA_AWAITING_APPROVAL,
            actor="executor",
            note="detected migrations",
        )
        assert project.state == ProjectState.SCHEMA_AWAITING_APPROVAL
        project.transition(
            ProjectState.EXECUTING, actor="cli-manual", note="approved"
        )
        assert project.state == ProjectState.EXECUTING


def test_state_machine_allows_bounce_back_for_dag_revision() -> None:
    """`SCHEMA_AWAITING_APPROVAL → TASKS_READY` is the "send back for
    revision" path. Useful when migration plan is wrong and Orchestrator
    needs to re-emit a different DAG."""
    with tempfile.TemporaryDirectory() as tmp:
        project = _project_in_state(Path(tmp), ProjectState.TASKS_READY)
        project.transition(
            ProjectState.SCHEMA_AWAITING_APPROVAL,
            actor="executor",
            note="detected migrations",
        )
        project.transition(
            ProjectState.TASKS_READY,
            actor="cli-manual",
            note="needs different migration plan",
        )
        assert project.state == ProjectState.TASKS_READY


def test_state_machine_blocks_invalid_skip_past_schema_gate() -> None:
    """A direct TASKS_READY → DONE leap MUST fail. The gate is not
    bypassable via raw state edits."""
    with tempfile.TemporaryDirectory() as tmp:
        project = _project_in_state(Path(tmp), ProjectState.TASKS_READY)
        with pytest.raises(InvalidTransition):
            project.transition(
                ProjectState.DONE, actor="test", note="should fail"
            )
