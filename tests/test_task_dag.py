# SPDX-License-Identifier: FSL-1.1-Apache-2.0
# Copyright (c) 2026 ortim.dev
"""Tests for TaskDAG validation and batching."""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from ortim.orchestrator import (  # noqa: E402
    CyclicDAG,
    MissingDependency,
    TaskDAG,
    TaskSpec,
)


def _task(tid: str, deps: list[str] | None = None, **kwargs) -> TaskSpec:
    return TaskSpec(
        id=tid,
        title=kwargs.get("title", f"do {tid}"),
        description=kwargs.get("description", "x"),
        module_scope=kwargs.get("module_scope", "shared"),
        dependencies=deps or [],
        estimated_tokens=kwargs.get("estimated_tokens", 5000),
        acceptance_criteria=kwargs.get("acceptance_criteria", ["c"]),
        rfc_section=kwargs.get("rfc_section", "§7"),
    )


def test_simple_linear_dag_validates() -> None:
    dag = TaskDAG(
        project_id="P",
        tasks=[_task("T-001"), _task("T-002", ["T-001"]), _task("T-003", ["T-002"])],
    )
    dag.validate_dag()


def test_missing_dependency_raises() -> None:
    dag = TaskDAG(
        project_id="P",
        tasks=[_task("T-001"), _task("T-002", ["T-999"])],
    )
    try:
        dag.validate_dag()
    except MissingDependency:
        return
    raise AssertionError("Expected MissingDependency")


def test_cycle_two_node() -> None:
    dag = TaskDAG(
        project_id="P",
        tasks=[_task("T-001", ["T-002"]), _task("T-002", ["T-001"])],
    )
    try:
        dag.validate_dag()
    except CyclicDAG:
        return
    raise AssertionError("Expected CyclicDAG")


def test_cycle_three_node() -> None:
    dag = TaskDAG(
        project_id="P",
        tasks=[
            _task("T-001", ["T-003"]),
            _task("T-002", ["T-001"]),
            _task("T-003", ["T-002"]),
        ],
    )
    try:
        dag.validate_dag()
    except CyclicDAG:
        return
    raise AssertionError("Expected CyclicDAG")


def test_self_dependency_raises() -> None:
    dag = TaskDAG(
        project_id="P",
        tasks=[_task("T-001", ["T-001"])],
    )
    try:
        dag.validate_dag()
    except CyclicDAG:
        return
    raise AssertionError("Expected CyclicDAG for self-dependency")


def test_duplicate_task_ids_raises() -> None:
    dag = TaskDAG(
        project_id="P",
        tasks=[_task("T-001"), _task("T-001")],
    )
    try:
        dag.validate_dag()
    except ValueError:
        return
    raise AssertionError("Expected ValueError for duplicate IDs")


def test_topological_batches_diamond() -> None:
    """A → B, A → C, B → D, C → D should produce 3 batches: [A], [B, C], [D]."""
    dag = TaskDAG(
        project_id="P",
        tasks=[
            _task("T-001"),
            _task("T-002", ["T-001"]),
            _task("T-003", ["T-001"]),
            _task("T-004", ["T-002", "T-003"]),
        ],
    )
    batches = dag.topological_batches()
    assert batches == [["T-001"], ["T-002", "T-003"], ["T-004"]]


def test_topological_batches_independent_first() -> None:
    """Three independent tasks should all be in batch 1."""
    dag = TaskDAG(
        project_id="P",
        tasks=[_task("T-001"), _task("T-002"), _task("T-003")],
    )
    batches = dag.topological_batches()
    assert batches == [["T-001", "T-002", "T-003"]]


def test_invalid_task_id_format_raises() -> None:
    try:
        TaskSpec(
            id="bad-id",
            title="t",
            description="d",
            module_scope="m",
            acceptance_criteria=["c"],
        )
    except ValueError:
        return
    raise AssertionError("Expected ValueError on bad task id format")


def test_token_cap_enforced() -> None:
    try:
        TaskSpec(
            id="T-001",
            title="t",
            description="d",
            module_scope="m",
            estimated_tokens=25_000,
        )
    except ValueError:
        return
    raise AssertionError("Expected ValueError when tokens > 20K")


def test_total_estimated_tokens() -> None:
    dag = TaskDAG(
        project_id="P",
        tasks=[
            _task("T-001", estimated_tokens=3000),
            _task("T-002", estimated_tokens=7000),
        ],
    )
    assert dag.total_estimated_tokens() == 10_000


if __name__ == "__main__":
    tests = [
        test_simple_linear_dag_validates,
        test_missing_dependency_raises,
        test_cycle_two_node,
        test_cycle_three_node,
        test_self_dependency_raises,
        test_duplicate_task_ids_raises,
        test_topological_batches_diamond,
        test_topological_batches_independent_first,
        test_invalid_task_id_format_raises,
        test_token_cap_enforced,
        test_total_estimated_tokens,
    ]
    failed = 0
    for test in tests:
        try:
            test()
            print(f"PASS  {test.__name__}")
        except Exception as e:
            failed += 1
            print(f"FAIL  {test.__name__}: {e}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
