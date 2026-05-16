# SPDX-License-Identifier: FSL-1.1-Apache-2.0
# Copyright (c) 2026 ortim.dev
"""Tests for TaskSpec.phase + `ortim run-all --phase` filter — Faz 1.1."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from runtime.orchestrator import TaskDAG, TaskSpec  # noqa: E402


def test_task_spec_defaults_to_phase_1() -> None:
    t = TaskSpec(
        id="T-001",
        title="x",
        description="x",
        module_scope="m",
        acceptance_criteria=["c"],
    )
    assert t.phase == 1


def test_task_spec_accepts_explicit_phase() -> None:
    t = TaskSpec(
        id="T-002",
        title="x",
        description="x",
        module_scope="m",
        phase=2,
    )
    assert t.phase == 2


def test_task_spec_rejects_non_positive_phase() -> None:
    with pytest.raises(ValueError):
        TaskSpec(id="T-003", title="x", description="x", module_scope="m", phase=0)
    with pytest.raises(ValueError):
        TaskSpec(id="T-004", title="x", description="x", module_scope="m", phase=-1)


def test_legacy_dag_json_without_phase_loads_clean() -> None:
    """Pre-1.1 DAGs serialize TaskSpecs without `phase`. Re-deserializing
    must default to phase=1 so old workspaces stay valid."""
    legacy = """
    {
        "project_id": "p",
        "tasks": [
            {
                "id": "T-001",
                "title": "first",
                "description": "first task",
                "module_scope": "core",
                "dependencies": [],
                "estimated_tokens": 5000,
                "acceptance_criteria": ["x"]
            }
        ]
    }
    """
    dag = TaskDAG.model_validate_json(legacy)
    assert dag.tasks[0].phase == 1


def test_dag_round_trip_preserves_phase() -> None:
    dag = TaskDAG(
        project_id="p",
        tasks=[
            TaskSpec(
                id="T-001", title="a", description="a",
                module_scope="m1", phase=1, acceptance_criteria=["c"],
            ),
            TaskSpec(
                id="T-002", title="b", description="b",
                module_scope="m2", phase=2, acceptance_criteria=["c"],
            ),
        ],
    )
    js = dag.model_dump_json()
    reloaded = TaskDAG.model_validate_json(js)
    assert [t.phase for t in reloaded.tasks] == [1, 2]
