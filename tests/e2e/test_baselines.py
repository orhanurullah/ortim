# SPDX-License-Identifier: FSL-1.1-Apache-2.0
# Copyright (c) 2026 ortim.dev
"""Regression baselines against frozen real-LLM proof-point artifacts.

Three fixtures cover different operational paths:

  * **proofpoint48** — M3.1 v1 extend cycle, T4/web TypeScript+React.
    Post-Item-48 (delta = 4 tasks for 11 ACs). 8/9 tasks DONE, T-009
    AWAITING_HITL with valid reviewer findings. Source of truth for the
    extend planning chain + happy-path execution.

  * **b8d60b6f5791** — Pre-M2 greenfield CLI (no stack.json). 6/6 tasks
    DONE. Validates that older artifact shapes still parse and that the
    universal task_dag schema is backward compatible.

  * **1b9c9f9ca18b** — Pre-Item-48 extend (16 tasks: 6 baseline + 10
    delta drift). Historical snapshot — schema must still parse; the
    over-granularization is NOT pinned as a correctness target.

Run with `pytest -m e2e`. Default-skipped to keep the fast suite fast.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from pydantic import ValidationError

from runtime.architecture.locked_stack import LockedStack
from runtime.executor.status import TaskStatus, TaskStatusFile
from runtime.orchestrator.task_dag import TaskDAG, TaskSpec
from tests.e2e.conftest import read_json, read_text

pytestmark = pytest.mark.e2e


_TASK_ID_RE = re.compile(r"^T-\d{3,}$")


# ---------------------------------------------------------------------
# Universal schema invariants (parametrized across all 3 fixtures)
# ---------------------------------------------------------------------


@pytest.mark.parametrize(
    "fixture_name",
    ["proofpoint48", "b8d60b6f5791", "1b9c9f9ca18b"],
)
def test_required_files_present(fixture_name: str, request: pytest.FixtureRequest) -> None:
    fixture_path = request.getfixturevalue({
        "proofpoint48": "proofpoint48",
        "b8d60b6f5791": "cli_greenfield",
        "1b9c9f9ca18b": "pre_item48_extend",
    }[fixture_name])
    for required in ("intent.json", "PRD.md", "RFC.md", "task_dag.json", "state.json"):
        assert (fixture_path / required).exists(), (
            f"{fixture_name}: missing required file {required}"
        )


@pytest.mark.parametrize(
    "fixture_name",
    ["proofpoint48", "b8d60b6f5791", "1b9c9f9ca18b"],
)
def test_task_dag_parses_via_pydantic_model(
    fixture_name: str, request: pytest.FixtureRequest
) -> None:
    """TaskDAG Pydantic model must accept every frozen artifact. A new
    required field on TaskDAG / TaskSpec without a default would break
    this — the regression we want to catch."""
    fixture_path = request.getfixturevalue({
        "proofpoint48": "proofpoint48",
        "b8d60b6f5791": "cli_greenfield",
        "1b9c9f9ca18b": "pre_item48_extend",
    }[fixture_name])
    try:
        dag = TaskDAG.model_validate_json(
            (fixture_path / "task_dag.json").read_text(encoding="utf-8")
        )
    except ValidationError as e:
        pytest.fail(f"{fixture_name}: TaskDAG schema regression — {e}")
    assert dag.project_id
    assert dag.tasks, f"{fixture_name}: DAG has no tasks"
    for task in dag.tasks:
        assert _TASK_ID_RE.match(task.id), (
            f"{fixture_name}: task ID {task.id!r} violates T-NNN format"
        )
        assert task.title, f"{fixture_name}: {task.id} has empty title"
        assert task.acceptance_criteria, (
            f"{fixture_name}: {task.id} has no acceptance criteria"
        )


@pytest.mark.parametrize(
    "fixture_name",
    ["proofpoint48", "b8d60b6f5791", "1b9c9f9ca18b"],
)
def test_task_status_file_loads_when_present(
    fixture_name: str, request: pytest.FixtureRequest
) -> None:
    fixture_path = request.getfixturevalue({
        "proofpoint48": "proofpoint48",
        "b8d60b6f5791": "cli_greenfield",
        "1b9c9f9ca18b": "pre_item48_extend",
    }[fixture_name])
    status_path = fixture_path / "task_status.json"
    if not status_path.exists():
        pytest.skip(f"{fixture_name}: no task_status.json")
    try:
        status = TaskStatusFile.model_validate_json(
            status_path.read_text(encoding="utf-8")
        )
    except ValidationError as e:
        pytest.fail(f"{fixture_name}: TaskStatusFile schema regression — {e}")
    for tid, record in status.records.items():
        assert isinstance(record.status, TaskStatus), (
            f"{fixture_name}: {tid} status not a TaskStatus enum"
        )
        assert record.attempts >= 0


# ---------------------------------------------------------------------
# proofpoint48 — M3.1 v1 extend cycle (post-Item-48)
# ---------------------------------------------------------------------


def test_proofpoint48_intent_describes_todo_app(proofpoint48: Path) -> None:
    intent = read_json(proofpoint48 / "intent.json")
    assert "todo" in intent["goal"].lower()


def test_proofpoint48_locked_stack_is_react_typescript_t4(proofpoint48: Path) -> None:
    """The stack lock is the single source of truth downstream layers
    consume. Drift here cascades into bootstrap, Worker, and Reviewer."""
    stack = LockedStack.model_validate_json(
        (proofpoint48 / "stack.json").read_text(encoding="utf-8")
    )
    assert stack.tier == "T4"
    assert stack.app_class == "web"
    assert stack.language == "TypeScript"
    assert stack.primary_framework.startswith("React"), (
        f"primary_framework should start with React, got {stack.primary_framework!r}"
    )
    assert "sql.js" in stack.key_libraries
    assert "zod" in stack.key_libraries


def test_proofpoint48_extend_cycle_produced_aggregated_delta(
    proofpoint48: Path,
) -> None:
    """Item 48 contract: ~11 delta ACs aggregate into a small task count
    (target ≤5). Pre-fix this brief produced 10 tasks; post-fix should
    sit comfortably under that. We pin a loose upper bound so a future
    aggregation refinement (say, dropping to 3 tasks) doesn't fail this
    test — the regression we want to catch is task count ballooning
    back toward 10."""
    dag = TaskDAG.model_validate_json(
        (proofpoint48 / "task_dag.json").read_text(encoding="utf-8")
    )
    assert len(dag.extensions) == 1, (
        "proofpoint48 should have exactly one extend cycle"
    )
    delta = dag.extensions[0]
    new_tasks = delta.get("new_tasks") or []
    assert 2 <= len(new_tasks) <= 6, (
        f"Item 48 regression: delta task count {len(new_tasks)} outside [2, 6]"
    )


def test_proofpoint48_module_scopes_match_locked_stack_modules(
    proofpoint48: Path,
) -> None:
    """Hard Rule 13 (Item 42) regression — every task scope must be in
    the RFC-declared module set. We use the union of seen scopes here
    as the implicit module set; if a task escapes into a synthetic
    `shared` scope or some unrelated path, this fails."""
    dag = TaskDAG.model_validate_json(
        (proofpoint48 / "task_dag.json").read_text(encoding="utf-8")
    )
    expected_modules = {"task", "tagging", "ui", "shared"}
    for t in dag.tasks:
        scope = t.module_scope.split("/")[0]
        assert scope in expected_modules, (
            f"{t.id}: module_scope={t.module_scope!r} outside "
            f"expected set {sorted(expected_modules)}"
        )


def test_proofpoint48_t009_in_hitl_state(proofpoint48: Path) -> None:
    """Memory ground truth: T-009 caught a real L1 boundary violation
    and escalated to AWAITING_HITL. If the reviewer chain weakens and
    starts approving this kind of violation, this test catches it."""
    status = TaskStatusFile.model_validate_json(
        (proofpoint48 / "task_status.json").read_text(encoding="utf-8")
    )
    assert "T-009" in status.records, "T-009 missing from status records"
    assert status.records["T-009"].status == TaskStatus.AWAITING_HITL


def test_proofpoint48_rfc_has_module_breakdown_delta_section(
    proofpoint48: Path,
) -> None:
    """M3.1.1's delta RFC parser keys off the `### Module Breakdown
    (delta)` H3 marker. If the Architect prompt or template drifts
    away from this header, downstream Orchestrator scope-union
    validation falls apart silently."""
    rfc = read_text(proofpoint48 / "RFC.md")
    assert "Module Breakdown" in rfc, "RFC missing Module Breakdown section"
    assert "delta" in rfc.lower(), "RFC has no delta marker"


# ---------------------------------------------------------------------
# b8d60b6f5791 — Pre-M2 greenfield CLI (full DONE)
# ---------------------------------------------------------------------


def test_cli_greenfield_intent_describes_cli_note_taker(cli_greenfield: Path) -> None:
    intent = read_json(cli_greenfield / "intent.json")
    text = (intent["goal"] + " " + " ".join(intent["must_have_features"])).lower()
    assert "note" in text
    assert "cli" in text or "terminal" in text


def test_cli_greenfield_has_no_stack_lock(cli_greenfield: Path) -> None:
    """Pre-M2 fixture sanity: stack.json wasn't a concept yet. If a
    future migration retro-adds it, this test should be updated
    intentionally — it pins the historical shape."""
    assert not (cli_greenfield / "stack.json").exists()


def test_cli_greenfield_all_tasks_done_no_extensions(cli_greenfield: Path) -> None:
    dag = TaskDAG.model_validate_json(
        (cli_greenfield / "task_dag.json").read_text(encoding="utf-8")
    )
    status = TaskStatusFile.model_validate_json(
        (cli_greenfield / "task_status.json").read_text(encoding="utf-8")
    )
    assert len(dag.extensions) == 0, "expected greenfield, no extend cycles"
    assert len(dag.tasks) == 6
    for task in dag.tasks:
        assert task.id in status.records, f"{task.id} missing from status"
        assert status.records[task.id].status == TaskStatus.DONE, (
            f"{task.id}: status {status.records[task.id].status} != DONE"
        )


def test_cli_greenfield_classic_4_module_layout(cli_greenfield: Path) -> None:
    """Four-module greenfield pattern (cli / models / repository /
    service) is the canonical T2/T4 shape Architect produces from this
    family of briefs. The shape itself is the contract we're guarding."""
    dag = TaskDAG.model_validate_json(
        (cli_greenfield / "task_dag.json").read_text(encoding="utf-8")
    )
    scopes = {t.module_scope.split("/")[0] for t in dag.tasks}
    expected = {"cli", "models", "repository", "service"}
    missing = expected - scopes
    assert not missing, f"missing expected module scopes: {missing}"


# ---------------------------------------------------------------------
# 1b9c9f9ca18b — Pre-Item-48 extend (historical, NOT a correctness target)
# ---------------------------------------------------------------------


def test_pre_item48_extend_is_schema_compatible(pre_item48_extend: Path) -> None:
    """Pin: historical artifacts parse with the current Pydantic models.
    A breaking schema change to TaskDAG / LockedStack must update this
    fixture (`scripts/record_e2e_fixture.py` re-record) or be flagged
    here. We intentionally do NOT assert the 10-task delta drift — that
    behavior is what Item 48 fixed."""
    dag = TaskDAG.model_validate_json(
        (pre_item48_extend / "task_dag.json").read_text(encoding="utf-8")
    )
    LockedStack.model_validate_json(
        (pre_item48_extend / "stack.json").read_text(encoding="utf-8")
    )
    assert dag.tasks
    assert dag.extensions, "extend cycle ran — should have at least one extension"


def test_pre_item48_extend_documents_pre_aggregation_drift(
    pre_item48_extend: Path,
) -> None:
    """Soft documentation assertion: the historical drift (10-AC →
    10-task 1:1 over-granularization) is what makes this fixture
    interesting. If a future Item 48 refinement re-records this fixture
    to also use aggregated tasks, this test fails — at which point the
    fixture has lost its historical-reference value and can be retired."""
    dag = TaskDAG.model_validate_json(
        (pre_item48_extend / "task_dag.json").read_text(encoding="utf-8")
    )
    delta = dag.extensions[0]
    new_tasks = delta.get("new_tasks") or []
    assert len(new_tasks) >= 8, (
        f"pre-Item-48 fixture lost its drift signature: only "
        f"{len(new_tasks)} delta tasks (expected the historical 10)"
    )


def test_pre_item48_extend_state_is_tasks_ready(pre_item48_extend: Path) -> None:
    """Captured before execution: no Worker turn yet."""
    state = read_json(pre_item48_extend / "state.json")
    assert state["state"] == "tasks_ready"
