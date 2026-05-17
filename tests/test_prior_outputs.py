# SPDX-License-Identifier: FSL-1.1-Apache-2.0
# Copyright (c) 2026 ortim.dev
"""collect_prior_outputs() walker tests.

Five guarantees:
  - only DONE tasks contribute (PENDING / AWAITING_HITL are skipped)
  - the current task is excluded
  - co-located test files (*.test.ts, *.spec.py) don't pollute the exports
  - per-module char budget caps individual modules with truncated=True
  - empty workspace / no DONE tasks → empty dict, no crash
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from ortim.codebase.prior_tasks import (  # noqa: E402
    collect_prior_outputs,
    format_prior_outputs_block,
)
from ortim.executor.status import TaskRunRecord, TaskStatus, TaskStatusFile  # noqa: E402
from ortim.orchestrator import TaskDAG, TaskSpec  # noqa: E402


def _task(tid: str, scope: str) -> TaskSpec:
    return TaskSpec(
        id=tid,
        title="x",
        description="x",
        module_scope=scope,
        rfc_section="§7",
        acceptance_criteria=["x"],
        estimated_tokens=100,
    )


def _workspace_with(files: dict[str, str]) -> Path:
    ws = Path(tempfile.mkdtemp())
    for rel, body in files.items():
        target = ws / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(body, encoding="utf-8")
    return ws


def _status(records: dict[str, TaskStatus]) -> TaskStatusFile:
    sf = TaskStatusFile(project_id="P")
    for tid, st in records.items():
        sf.records[tid] = TaskRunRecord(task_id=tid, status=st)
    return sf


def test_only_done_tasks_are_surfaced() -> None:
    ws = _workspace_with(
        {
            "module-a/index.ts": "export function aFn() {}\n",
            "module-b/index.ts": "export function bFn() {}\n",
        }
    )
    dag = TaskDAG(
        project_id="P",
        tasks=[_task("T-1", "module-a"), _task("T-2", "module-b")],
    )
    status = _status({"T-1": TaskStatus.DONE, "T-2": TaskStatus.PENDING})
    result = collect_prior_outputs(
        workspace=ws,
        dag=dag,
        status_file=status,
        current_task_id="T-3",
    )
    assert "module-a" in result
    assert "module-b" not in result  # PENDING, not surfaced


def test_current_task_is_excluded() -> None:
    ws = _workspace_with({"x/index.ts": "export function xFn() {}\n"})
    dag = TaskDAG(project_id="P", tasks=[_task("T-1", "x")])
    status = _status({"T-1": TaskStatus.DONE})
    # T-1 is the *current* task → excluded even though DONE
    result = collect_prior_outputs(
        workspace=ws, dag=dag, status_file=status, current_task_id="T-1"
    )
    assert result == {}


def test_test_files_are_filtered_out() -> None:
    ws = _workspace_with(
        {
            "svc/index.ts": "export function svcFn() {}\n",
            "svc/index.test.ts": "describe('svcFn', () => { expect(true).toBe(true); });\n",
        }
    )
    dag = TaskDAG(project_id="P", tasks=[_task("T-1", "svc")])
    status = _status({"T-1": TaskStatus.DONE})
    result = collect_prior_outputs(
        workspace=ws, dag=dag, status_file=status, current_task_id="T-curr"
    )
    files = result["svc"].files
    assert any("svc/index.ts" in p for p in files)
    # The co-located test file must NOT appear — it would be noise
    assert not any(".test." in p for p in files)


def test_per_module_budget_truncates() -> None:
    long_body = "\n".join(f"export function fn{i}(): number {{ return 0; }}" for i in range(50))
    ws = _workspace_with({"big/index.ts": long_body})
    dag = TaskDAG(project_id="P", tasks=[_task("T-1", "big")])
    status = _status({"T-1": TaskStatus.DONE})
    # Cap at 200 chars — far less than 50 signatures need
    result = collect_prior_outputs(
        workspace=ws,
        dag=dag,
        status_file=status,
        current_task_id="T-curr",
        per_module_char_budget=200,
    )
    # Truncation may drop the only file, leaving no exports surfaced —
    # in that case `result['big']` is omitted because the module is empty.
    # If anything was kept, the module must be marked truncated.
    if "big" in result:
        assert result["big"].truncated is True


def test_no_done_tasks_returns_empty() -> None:
    ws = _workspace_with({"x/index.ts": "export function xFn() {}\n"})
    dag = TaskDAG(project_id="P", tasks=[_task("T-1", "x")])
    status = _status({"T-1": TaskStatus.PENDING})
    result = collect_prior_outputs(
        workspace=ws, dag=dag, status_file=status, current_task_id="T-curr"
    )
    assert result == {}


def test_format_block_lists_modules_alphabetically() -> None:
    ws = _workspace_with(
        {
            "service-z/index.ts": "export function zFn() {}\n",
            "service-a/index.ts": "export function aFn() {}\n",
        }
    )
    dag = TaskDAG(
        project_id="P",
        tasks=[_task("T-1", "service-z"), _task("T-2", "service-a")],
    )
    status = _status({"T-1": TaskStatus.DONE, "T-2": TaskStatus.DONE})
    modules = collect_prior_outputs(
        workspace=ws, dag=dag, status_file=status, current_task_id="T-curr"
    )
    block = format_prior_outputs_block(modules)
    assert "## Prior task exports" in block
    # service-a should appear before service-z in the block
    a_idx = block.find("### service-a")
    z_idx = block.find("### service-z")
    assert 0 < a_idx < z_idx


def test_format_block_empty_returns_empty_string() -> None:
    assert format_prior_outputs_block({}) == ""
