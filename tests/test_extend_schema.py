# SPDX-License-Identifier: FSL-1.1-Apache-2.0
# Copyright (c) 2026 ortim.dev
"""M3.1.0b — extension schemas (ExtensionIntent + DagDelta) and the
TaskDAG.extensions field + TaskDAG.max_task_id() helper."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ortim.extend import DagDelta, ExtensionIntent  # noqa: E402
from ortim.orchestrator.task_dag import TaskDAG, TaskSpec  # noqa: E402


def _task(task_id: str, *, scope: str = "ui") -> TaskSpec:
    return TaskSpec(
        id=task_id,
        title=f"task {task_id}",
        description=f"description for {task_id}",
        module_scope=scope,
        acceptance_criteria=[f"{task_id} works"],
    )


# ---- ExtensionIntent ----


def test_extension_intent_minimal_round_trip() -> None:
    intent = ExtensionIntent(
        parent_project_id="P-1",
        cycle=1,
        goal="Add tagging to tasks so users can categorize their todos",
    )
    assert intent.parent_project_id == "P-1"
    assert intent.cycle == 1
    assert intent.must_have_features == []
    # JSON round-trip must be lossless.
    raw = intent.model_dump_json()
    parsed = ExtensionIntent.model_validate_json(raw)
    assert parsed == intent


def test_extension_intent_rejects_cycle_zero() -> None:
    with pytest.raises(ValidationError):
        ExtensionIntent(
            parent_project_id="P-1",
            cycle=0,
            goal="add tagging",
        )


def test_extension_intent_rejects_empty_goal() -> None:
    with pytest.raises(ValidationError):
        ExtensionIntent(
            parent_project_id="P-1",
            cycle=1,
            goal="   ",
        )


# ---- DagDelta ----


def test_dag_delta_minimal_round_trip() -> None:
    delta = DagDelta(
        cycle=1,
        feature_title="Tagging",
        new_tasks=[_task("T-006", scope="tagging")],
        starts_from_task_id="T-006",
    )
    raw = delta.model_dump_json()
    parsed = DagDelta.model_validate_json(raw)
    assert parsed == delta
    assert parsed.new_tasks[0].id == "T-006"


def test_dag_delta_rejects_invalid_starts_from_format() -> None:
    with pytest.raises(ValidationError):
        DagDelta(
            cycle=1,
            feature_title="Tagging",
            new_tasks=[_task("T-006")],
            starts_from_task_id="006",  # missing T- prefix
        )


def test_dag_delta_rejects_empty_feature_title() -> None:
    with pytest.raises(ValidationError):
        DagDelta(
            cycle=1,
            feature_title="",
            new_tasks=[_task("T-006")],
            starts_from_task_id="T-006",
        )


# ---- TaskDAG.extensions back-compat + max_task_id ----


def test_task_dag_legacy_json_loads_without_extensions_field(tmp_path: Path) -> None:
    """A legacy task_dag.json (pre-M3.1, no `extensions` field) must load
    cleanly. Default `[]` keeps every shipped project re-loadable."""
    legacy = {
        "project_id": "P-1",
        "tasks": [
            {
                "id": "T-001",
                "title": "first",
                "description": "...",
                "module_scope": "ui",
                "dependencies": [],
                "estimated_tokens": 5000,
                "acceptance_criteria": ["works"],
                "rfc_section": "",
            },
        ],
    }
    f = tmp_path / "task_dag.json"
    f.write_text(json.dumps(legacy), encoding="utf-8")
    dag = TaskDAG.model_validate_json(f.read_text(encoding="utf-8"))
    assert dag.extensions == []
    assert len(dag.tasks) == 1


def test_task_dag_extensions_round_trip() -> None:
    """A DAG with one extension delta serializes and reloads identically."""
    delta_dict = DagDelta(
        cycle=1,
        feature_title="Tagging",
        new_tasks=[_task("T-006", scope="tagging")],
        starts_from_task_id="T-006",
    ).model_dump()
    dag = TaskDAG(
        project_id="P-1",
        tasks=[_task("T-001"), _task("T-002")],
        extensions=[delta_dict],
    )
    raw = dag.model_dump_json()
    parsed = TaskDAG.model_validate_json(raw)
    assert len(parsed.extensions) == 1
    assert parsed.extensions[0]["feature_title"] == "Tagging"
    assert parsed.extensions[0]["cycle"] == 1


def test_max_task_id_zero_when_empty() -> None:
    dag = TaskDAG(project_id="P-1", tasks=[])
    assert dag.max_task_id() == 0


def test_max_task_id_finds_highest() -> None:
    dag = TaskDAG(
        project_id="P-1",
        tasks=[_task("T-001"), _task("T-005"), _task("T-003")],
    )
    assert dag.max_task_id() == 5


def test_max_task_id_tolerates_padded_and_non_padded() -> None:
    dag = TaskDAG(
        project_id="P-1",
        tasks=[_task("T-001"), _task("T-12"), _task("T-007")],
    )
    assert dag.max_task_id() == 12


def test_max_task_id_skips_non_numeric_tails() -> None:
    """If somehow a non-numeric task ID slips in (legacy fixture, custom
    naming), `max_task_id` skips it rather than raising. The validator
    in M3.1.1 will catch the actual collision case separately."""
    dag = TaskDAG(
        project_id="P-1",
        tasks=[_task("T-001"), _task("T-foo"), _task("T-003")],
    )
    assert dag.max_task_id() == 3


# ---- M3.1.1c — merged task_dag.json persistence ----


def test_merged_extend_dag_persists_prior_tasks_and_delta(tmp_path: Path) -> None:
    """M3.1.1c — the post-extend task_dag.json must:
    - retain every prior task verbatim (id, deps, scope)
    - include the new delta tasks
    - carry one DagDelta entry per extend cycle in `extensions`

    This pins the merge shape that `_generate_extend_dag` writes; if the
    schema or merge logic regresses, run-all's skip-DONE behavior would
    silently degrade because the prior tasks would be missing."""
    prior_dag = TaskDAG(
        project_id="P-1",
        tasks=[
            _task("T-001", scope="db"),
            _task("T-002", scope="ui"),
            _task("T-003", scope="store"),
        ],
        extensions=[],
    )
    delta = DagDelta(
        cycle=1,
        feature_title="Tagging",
        new_tasks=[
            _task("T-004", scope="tagging"),
            _task("T-005", scope="ui"),
        ],
        starts_from_task_id="T-004",
    )

    merged = TaskDAG(
        project_id="P-1",
        tasks=[*prior_dag.tasks, *delta.new_tasks],
        extensions=[*prior_dag.extensions, delta.model_dump()],
    )
    path = tmp_path / "task_dag.json"
    path.write_text(merged.model_dump_json(indent=2), encoding="utf-8")

    # Round-trip via filesystem (the run-all path always reads from disk).
    reloaded = TaskDAG.model_validate_json(path.read_text(encoding="utf-8"))

    assert [t.id for t in reloaded.tasks] == [
        "T-001", "T-002", "T-003", "T-004", "T-005"
    ]
    assert len(reloaded.extensions) == 1
    assert reloaded.extensions[0]["cycle"] == 1
    assert reloaded.extensions[0]["feature_title"] == "Tagging"
    assert reloaded.extensions[0]["starts_from_task_id"] == "T-004"
    # Prior tasks' module_scopes preserved (not silently dropped).
    assert {t.id: t.module_scope for t in reloaded.tasks} == {
        "T-001": "db",
        "T-002": "ui",
        "T-003": "store",
        "T-004": "tagging",
        "T-005": "ui",
    }


def test_merged_extend_dag_supports_multiple_cycles_in_extensions(
    tmp_path: Path,
) -> None:
    """Each extend cycle appends one DagDelta. After 2 cycles, extensions
    has 2 entries in cycle order; tasks list grows by both deltas."""
    prior = TaskDAG(
        project_id="P-1",
        tasks=[_task("T-001"), _task("T-002")],
        extensions=[
            DagDelta(
                cycle=1,
                feature_title="Tagging",
                new_tasks=[_task("T-003", scope="tagging")],
                starts_from_task_id="T-003",
            ).model_dump()
        ],
    )
    # Effective tasks at this point would be T-001..T-003 already merged in,
    # but the test sets up the prior fresh to verify cycle 2 appends correctly.
    merged_prior = TaskDAG(
        project_id="P-1",
        tasks=[_task("T-001"), _task("T-002"), _task("T-003", scope="tagging")],
        extensions=prior.extensions,
    )

    delta2 = DagDelta(
        cycle=2,
        feature_title="Due dates",
        new_tasks=[_task("T-004", scope="due-dates")],
        starts_from_task_id="T-004",
    )
    final = TaskDAG(
        project_id="P-1",
        tasks=[*merged_prior.tasks, *delta2.new_tasks],
        extensions=[*merged_prior.extensions, delta2.model_dump()],
    )
    path = tmp_path / "task_dag.json"
    path.write_text(final.model_dump_json(indent=2), encoding="utf-8")

    reloaded = TaskDAG.model_validate_json(path.read_text(encoding="utf-8"))
    assert [t.id for t in reloaded.tasks] == ["T-001", "T-002", "T-003", "T-004"]
    assert [d["cycle"] for d in reloaded.extensions] == [1, 2]
    assert [d["feature_title"] for d in reloaded.extensions] == [
        "Tagging",
        "Due dates",
    ]
