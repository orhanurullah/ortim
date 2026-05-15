# SPDX-License-Identifier: FSL-1.1-Apache-2.0
# Copyright (c) 2026 ortim.dev
"""Tests for the multi-cycle drift detector (`ortim drift-check`).

Four orthogonal checks:

  * D1 module_scope        — task.module_scope ∉ baseline §7 ∪ delta H3
  * D2 task_id_continuity  — extend cycle assigns ID ≤ prior cycle max
  * D3 id_collision        — duplicate task IDs in the DAG
  * D4 status_audit        — task_status DONE without worker_output_ok event

Plus one multi-cycle integration scenario against a synthetic workspace
that exercises baseline + extend + audit log together.
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from runtime.extend.drift import (  # noqa: E402
    KIND_ID_COLLISION,
    KIND_ID_CONTINUITY,
    KIND_MODULE_SCOPE,
    KIND_STATUS_AUDIT,
    SEV_ERROR,
    SEV_WARNING,
    inspect_drift,
)


def _baseline_rfc() -> str:
    return (
        "# RFC\n\n"
        "## 7. Module Breakdown\n\n"
        "| Module | Responsibility |\n"
        "|---|---|\n"
        "| `task` | core task domain |\n"
        "| `ui` | presentation layer |\n"
        "| `shared` | cross-cutting utilities |\n"
        "\n"
        "## 8. Next section\n"
    )


def _baseline_dag(tasks: list[dict]) -> str:
    return json.dumps({
        "project_id": "P1",
        "tasks": tasks,
        "extensions": [],
    })


def _task(id_: str, scope: str, deps: list[str] | None = None) -> dict:
    return {
        "id": id_,
        "title": "t",
        "description": "d",
        "module_scope": scope,
        "rfc_section": "§7",
        "dependencies": deps or [],
        "acceptance_criteria": ["criterion"],
        "estimated_tokens": 1000,
    }


def _write_workspace(workspace: Path, *, rfc: str, dag: dict) -> None:
    (workspace / "RFC.md").write_text(rfc, encoding="utf-8")
    (workspace / "task_dag.json").write_text(
        json.dumps(dag), encoding="utf-8"
    )


# ---------------------------------------------------------------------
# D1 — module scope coverage
# ---------------------------------------------------------------------


def test_module_scope_clean_when_all_tasks_in_rfc_modules() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        ws = Path(tmp)
        _write_workspace(
            ws,
            rfc=_baseline_rfc(),
            dag={
                "project_id": "P1",
                "tasks": [
                    _task("T-001", "task"),
                    _task("T-002", "ui", deps=["T-001"]),
                ],
                "extensions": [],
            },
        )
        report = inspect_drift(ws, audit_path=Path(tmp) / "nonexistent.jsonl")
        assert report.is_clean
        assert report.cycle_count == 1


def test_module_scope_flags_unscoped_task() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        ws = Path(tmp)
        _write_workspace(
            ws,
            rfc=_baseline_rfc(),
            dag={
                "project_id": "P1",
                "tasks": [
                    _task("T-001", "task"),
                    _task("T-002", "auth"),  # not in {task, ui, shared}
                ],
                "extensions": [],
            },
        )
        report = inspect_drift(ws, audit_path=Path(tmp) / "nonexistent.jsonl")
        scope_errors = [f for f in report.errors if f.kind == KIND_MODULE_SCOPE]
        assert len(scope_errors) == 1
        assert scope_errors[0].entity == "T-002"
        assert "auth" in scope_errors[0].message


def test_module_scope_accepts_delta_modules_from_extension() -> None:
    """Extend cycle introduces new module `tagging` via the delta H3
    block. Tasks scoped to `tagging` should NOT flag as drift."""
    with tempfile.TemporaryDirectory() as tmp:
        ws = Path(tmp)
        rfc = _baseline_rfc() + (
            "\n## Extension 1\n\n"
            "### Module Breakdown (delta)\n\n"
            "| Module | Responsibility |\n"
            "|---|---|\n"
            "| `tagging` | tag CRUD |\n"
        )
        _write_workspace(
            ws,
            rfc=rfc,
            dag={
                "project_id": "P1",
                "tasks": [
                    _task("T-001", "task"),
                    _task("T-002", "tagging", deps=["T-001"]),
                ],
                "extensions": [],
            },
        )
        report = inspect_drift(ws, audit_path=Path(tmp) / "nonexistent.jsonl")
        scope_errors = [f for f in report.errors if f.kind == KIND_MODULE_SCOPE]
        assert scope_errors == []


# ---------------------------------------------------------------------
# D2 — task ID continuity across extend cycles
# ---------------------------------------------------------------------


def test_extend_id_continuity_clean_when_ids_strictly_above_prior_max() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        ws = Path(tmp)
        _write_workspace(
            ws,
            rfc=_baseline_rfc(),
            dag={
                "project_id": "P1",
                "tasks": [
                    _task("T-001", "task"),
                    _task("T-002", "ui", deps=["T-001"]),
                    _task("T-003", "task", deps=["T-002"]),
                    _task("T-004", "ui", deps=["T-003"]),
                ],
                "extensions": [
                    {"cycle": 1, "new_tasks": ["T-003", "T-004"]},
                ],
            },
        )
        report = inspect_drift(ws, audit_path=Path(tmp) / "nonexistent.jsonl")
        continuity_errors = [
            f for f in report.errors if f.kind == KIND_ID_CONTINUITY
        ]
        assert continuity_errors == []
        assert report.cycle_count == 2


def test_extend_id_continuity_flags_below_min_id() -> None:
    """Baseline went to T-005; cycle 1 should start at T-006. A cycle 1
    that tries to (re)use T-003 fails continuity."""
    with tempfile.TemporaryDirectory() as tmp:
        ws = Path(tmp)
        _write_workspace(
            ws,
            rfc=_baseline_rfc(),
            dag={
                "project_id": "P1",
                "tasks": [
                    _task("T-001", "task"),
                    _task("T-002", "ui", deps=["T-001"]),
                    _task("T-003", "task", deps=["T-002"]),
                    _task("T-004", "ui", deps=["T-003"]),
                    _task("T-005", "task", deps=["T-004"]),
                ],
                "extensions": [
                    {"cycle": 1, "new_tasks": ["T-003"]},
                ],
            },
        )
        report = inspect_drift(ws, audit_path=Path(tmp) / "nonexistent.jsonl")
        continuity_errors = [
            f for f in report.errors if f.kind == KIND_ID_CONTINUITY
        ]
        assert len(continuity_errors) == 1
        assert continuity_errors[0].entity == "T-003"
        assert continuity_errors[0].cycle == 1


# ---------------------------------------------------------------------
# D3 — duplicate task IDs
# ---------------------------------------------------------------------


def test_id_collision_flags_duplicate_task_ids() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        ws = Path(tmp)
        _write_workspace(
            ws,
            rfc=_baseline_rfc(),
            dag={
                "project_id": "P1",
                "tasks": [
                    _task("T-001", "task"),
                    _task("T-001", "ui"),
                ],
                "extensions": [],
            },
        )
        report = inspect_drift(ws, audit_path=Path(tmp) / "nonexistent.jsonl")
        collision_errors = [
            f for f in report.errors if f.kind == KIND_ID_COLLISION
        ]
        assert len(collision_errors) == 1
        assert collision_errors[0].entity == "T-001"


# ---------------------------------------------------------------------
# D4 — status ↔ audit reconciliation
# ---------------------------------------------------------------------


def test_status_audit_warns_when_done_without_worker_output_ok() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        ws = Path(tmp)
        _write_workspace(
            ws,
            rfc=_baseline_rfc(),
            dag={
                "project_id": "P1",
                "tasks": [
                    _task("T-001", "task"),
                    _task("T-002", "ui", deps=["T-001"]),
                ],
                "extensions": [],
            },
        )
        (ws / "task_status.json").write_text(
            json.dumps({
                "project_id": "P1",
                "records": {
                    "T-001": {
                        "task_id": "T-001",
                        "status": "DONE",
                        "attempts": 1,
                    },
                    "T-002": {
                        "task_id": "T-002",
                        "status": "DONE",
                        "attempts": 1,
                    },
                },
            }),
            encoding="utf-8",
        )
        audit_path = ws / "audit.jsonl"
        audit_path.write_text(
            json.dumps({
                "event": "worker_output_ok",
                "project_id": "P1",
                "task_id": "T-001",
            }) + "\n",
            encoding="utf-8",
        )
        report = inspect_drift(ws, audit_path=audit_path)
        warnings = [f for f in report.warnings if f.kind == KIND_STATUS_AUDIT]
        assert len(warnings) == 1
        assert warnings[0].entity == "T-002"
        assert warnings[0].severity == SEV_WARNING


# ---------------------------------------------------------------------
# Multi-cycle integration — baseline + 1 extend with mixed signals
# ---------------------------------------------------------------------


def test_multicycle_integration_baseline_clean_extend_introduces_drift() -> None:
    """Baseline cycle correct (T-001..T-003 in {task, ui}); extend cycle
    introduces both legitimate new modules AND deliberate drift (one
    task scoped to a module that's neither baseline nor declared in
    delta). Reporter should: flag the bad extend task, accept the good
    delta-module task, NOT flag any baseline task."""
    with tempfile.TemporaryDirectory() as tmp:
        ws = Path(tmp)
        rfc = _baseline_rfc() + (
            "\n## Extension 1\n\n"
            "### Module Breakdown (delta)\n\n"
            "| Module | Responsibility |\n"
            "|---|---|\n"
            "| `tagging` | tag CRUD |\n"
        )
        _write_workspace(
            ws,
            rfc=rfc,
            dag={
                "project_id": "P1",
                "tasks": [
                    _task("T-001", "task"),
                    _task("T-002", "ui", deps=["T-001"]),
                    _task("T-003", "task", deps=["T-002"]),
                    _task("T-004", "tagging", deps=["T-003"]),
                    _task("T-005", "billing", deps=["T-004"]),
                ],
                "extensions": [
                    {"cycle": 1, "new_tasks": ["T-004", "T-005"]},
                ],
            },
        )
        (ws / "task_status.json").write_text(
            json.dumps({
                "project_id": "P1",
                "records": {
                    "T-001": {"task_id": "T-001", "status": "DONE", "attempts": 1},
                    "T-002": {"task_id": "T-002", "status": "DONE", "attempts": 1},
                    "T-003": {"task_id": "T-003", "status": "DONE", "attempts": 1},
                },
            }),
            encoding="utf-8",
        )
        audit_path = ws / "audit.jsonl"
        audit_path.write_text(
            "\n".join(
                json.dumps({
                    "event": "worker_output_ok",
                    "project_id": "P1",
                    "task_id": tid,
                })
                for tid in ["T-001", "T-002", "T-003"]
            )
            + "\n",
            encoding="utf-8",
        )
        report = inspect_drift(ws, audit_path=audit_path)
        scope = [f for f in report.errors if f.kind == KIND_MODULE_SCOPE]
        # Only T-005 (billing) should flag — T-004 (tagging) is delta-legit.
        assert len(scope) == 1
        assert scope[0].entity == "T-005"
        # No status warnings — every DONE has a matching audit event.
        assert not [f for f in report.warnings if f.kind == KIND_STATUS_AUDIT]
        assert report.cycle_count == 2


# ---------------------------------------------------------------------
# Schema + serialization sanity
# ---------------------------------------------------------------------


def test_to_json_dict_stable_schema() -> None:
    from runtime.extend.drift import to_json_dict

    with tempfile.TemporaryDirectory() as tmp:
        ws = Path(tmp)
        _write_workspace(
            ws,
            rfc=_baseline_rfc(),
            dag={
                "project_id": "P1",
                "tasks": [_task("T-001", "auth")],
                "extensions": [],
            },
        )
        report = inspect_drift(ws, audit_path=Path(tmp) / "nonexistent.jsonl")
        out = to_json_dict(report)
        assert set(out.keys()) == {
            "project_id",
            "cycle_count",
            "error_count",
            "warning_count",
            "findings",
        }
        assert out["error_count"] == 1
        assert out["findings"][0]["kind"] == KIND_MODULE_SCOPE
        assert out["findings"][0]["severity"] == SEV_ERROR
