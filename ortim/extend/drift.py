# SPDX-License-Identifier: FSL-1.1-Apache-2.0
# Copyright (c) 2026 ortim.dev
"""Multi-cycle integrity checks for `ortim extend` workspaces.

The Orchestrator's M3.1.1 validators enforce most of these invariants at
DAG-generation time. This module re-runs them post-hoc against the
materialized artifacts on disk so that:

  * manual edits or external tooling that bypass the Orchestrator are
    caught before they cascade into Worker confusion
  * a future bug in an Orchestrator validator surfaces as a drift
    finding rather than silently corrupting downstream cycles
  * task_status.json claims (DONE / FAILED) are reconciled against the
    audit log's worker_output_ok events — this one is bonus, not
    Orchestrator-enforceable, and is the most operationally useful
    check in practice

v1 checks (D1, D2, D3, D4 in the design doc). D5 (stack drift between
stack.json and RFC §4 key_libraries) requires RFC §4 parsing and is
deferred. v1 is report-only: no auto-reconcile, no mutation of
artifacts.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

from ortim.agents.orchestrator import (
    _find_unscoped_tasks,
    _parse_rfc_extension_modules,
    _parse_rfc_modules,
)
from ortim.executor.status import TaskStatus, TaskStatusFile
from ortim.orchestrator.task_dag import TaskDAG

SEV_ERROR = "error"
SEV_WARNING = "warning"

KIND_MODULE_SCOPE = "module_scope"
KIND_ID_CONTINUITY = "task_id_continuity"
KIND_ID_COLLISION = "id_collision"
KIND_STATUS_AUDIT = "status_audit_mismatch"


@dataclass(frozen=True)
class DriftFinding:
    kind: str
    severity: str
    entity: str
    message: str
    cycle: int | None = None


@dataclass(frozen=True)
class DriftReport:
    project_id: str
    cycle_count: int
    findings: list[DriftFinding] = field(default_factory=list)

    @property
    def errors(self) -> list[DriftFinding]:
        return [f for f in self.findings if f.severity == SEV_ERROR]

    @property
    def warnings(self) -> list[DriftFinding]:
        return [f for f in self.findings if f.severity == SEV_WARNING]

    @property
    def is_clean(self) -> bool:
        return not self.findings


def inspect_drift(
    workspace: Path,
    *,
    project_id: str | None = None,
    audit_path: Path | None = None,
) -> DriftReport:
    """Run every drift check against a workspace and return a structured
    report. Pure read — never modifies the workspace.

    The workspace must contain `task_dag.json` at minimum. Missing
    `RFC.md` / `task_status.json` / audit log degrade individual checks
    gracefully (the affected findings are simply not emitted), but the
    overall call still succeeds.
    """
    dag_path = workspace / "task_dag.json"
    if not dag_path.exists():
        raise FileNotFoundError(f"task_dag.json missing in {workspace}")

    dag = TaskDAG.model_validate_json(dag_path.read_text(encoding="utf-8"))
    pid = project_id or dag.project_id
    cycle_count = 1 + len(dag.extensions)
    findings: list[DriftFinding] = []

    rfc_path = workspace / "RFC.md"
    rfc_text = rfc_path.read_text(encoding="utf-8") if rfc_path.exists() else ""

    findings.extend(_check_module_scope(dag, rfc_text))
    findings.extend(_check_id_collisions(dag))
    findings.extend(_check_extend_continuity(dag))
    findings.extend(_check_status_audit(workspace, dag, pid, audit_path))

    return DriftReport(
        project_id=pid,
        cycle_count=cycle_count,
        findings=findings,
    )


def _parse_baseline_modules_permissive(rfc_text: str) -> set[str]:
    """Wider net than `ortim.agents.orchestrator._parse_rfc_modules`.

    The orchestrator's parser requires backticks in the module column
    (`| `task` | ...`). Real-world RFCs vary: proofpoint48 baseline §7
    uses bare-name rows (`| task | CRUD ...`). For drift detection — a
    post-hoc check, not a generation-time gate — we prefer false
    positives (catching real drift) over silent skips. Permissive parse
    handles both shapes; the strict parser is consulted first when it
    returns a non-None / non-empty result.
    """
    section = re.search(
        r"##\s*\d*\.?\s*Module Breakdown\b", rfc_text, re.IGNORECASE
    )
    if not section:
        return set()
    start = section.end()
    next_section = re.search(r"\n##\s", rfc_text[start:])
    body = rfc_text[
        start : start + (next_section.start() if next_section else len(rfc_text) - start)
    ]

    modules: set[str] = set()
    for raw_line in body.splitlines():
        line = raw_line.strip()
        if not line.startswith("|"):
            continue
        # Separator row, e.g. `|---|---|`
        if not set(line.strip("|")) - set(" -:|"):
            continue
        parts = [p.strip() for p in line.strip("|").split("|")]
        if not parts:
            continue
        first = parts[0]
        # Accept backticked OR bare name in column 1.
        if first.startswith("`") and "`" in first[1:]:
            name = first.split("`")[1]
        else:
            name = first
        name = re.sub(r"\s*\(new\)\s*$", "", name).strip()
        # Header row words to skip.
        if name.lower() in {"module", "name", "section", "modules"}:
            continue
        # Module names are simple identifiers — no spaces, slashes, or
        # markdown punctuation. Filters out free-text rows that aren't
        # actually module declarations.
        if not name:
            continue
        if not re.fullmatch(r"[A-Za-z0-9_./\-]+", name):
            continue
        modules.add(name)
    return modules


def _check_module_scope(dag: TaskDAG, rfc_text: str) -> list[DriftFinding]:
    """D1 — every task's `module_scope` must be in
    `(baseline §7 ∪ delta H3 blocks)`. Hard Rule 13 / Item 42 enforces
    this at DAG generation; we re-check against the on-disk RFC.

    Baseline parse falls back from the orchestrator's strict parser to a
    permissive one when strict returns None or empty — drift detection
    should not silently skip a check just because the RFC author used a
    bare-name table.
    """
    if not rfc_text:
        return []
    strict = _parse_rfc_modules(rfc_text)
    baseline: set[str] = strict if strict else _parse_baseline_modules_permissive(rfc_text)
    if not baseline:
        return []
    rfc_modules = baseline | _parse_rfc_extension_modules(rfc_text)
    mismatches = _find_unscoped_tasks(dag, rfc_modules)
    return [
        DriftFinding(
            kind=KIND_MODULE_SCOPE,
            severity=SEV_ERROR,
            entity=task_id,
            message=(
                f"module_scope {scope!r} not in RFC module set "
                f"{sorted(rfc_modules)}"
            ),
        )
        for task_id, scope in mismatches
    ]


def _check_id_collisions(dag: TaskDAG) -> list[DriftFinding]:
    """D3 — duplicate task IDs in the same DAG. The standard
    TaskDAG.validate_dag() raises on this, but inspect_drift returns
    findings instead so a single corrupt artifact doesn't abort the
    whole report."""
    seen: dict[str, int] = {}
    findings: list[DriftFinding] = []
    for task in dag.tasks:
        seen[task.id] = seen.get(task.id, 0) + 1
    for task_id, count in seen.items():
        if count > 1:
            findings.append(
                DriftFinding(
                    kind=KIND_ID_COLLISION,
                    severity=SEV_ERROR,
                    entity=task_id,
                    message=f"task ID {task_id!r} appears {count} times in DAG",
                )
            )
    return findings


def _check_extend_continuity(dag: TaskDAG) -> list[DriftFinding]:
    """D2 — for each extend cycle, the cycle's new tasks must have IDs
    strictly above the prior cycle's max. The Orchestrator's
    `_find_below_min_ids` validator enforces this at generation time;
    we re-run it on materialized state.

    Walks extensions in order. For cycle N, the "prior max" is the max
    ID across (baseline tasks ∪ new tasks from cycles 1..N-1).
    """
    if not dag.extensions:
        return []

    findings: list[DriftFinding] = []
    baseline_task_ids = {t.id for t in dag.tasks}
    consumed_ids: set[str] = set()

    for ext in dag.extensions:
        cycle = ext.get("cycle")
        # `new_tasks` is canonically `list[TaskSpec]` (dict-shaped after
        # JSON load) per the `DagDelta` schema. Tests and legacy
        # shorthand also accept `list[str]` of bare task IDs; normalize
        # both here so the integrity check is shape-agnostic.
        new_task_ids: list[str] = []
        for item in ext.get("new_tasks") or []:
            if isinstance(item, dict):
                tid = item.get("id")
                if isinstance(tid, str):
                    new_task_ids.append(tid)
            elif isinstance(item, str):
                new_task_ids.append(item)

        # Prior max = baseline + earlier cycles' new tasks.
        prior_ids = (baseline_task_ids - set(new_task_ids)) | consumed_ids
        prior_max = _max_id_int(prior_ids)

        for tid in new_task_ids:
            tail = tid.removeprefix("T-")
            try:
                n = int(tail)
            except ValueError:
                findings.append(
                    DriftFinding(
                        kind=KIND_ID_CONTINUITY,
                        severity=SEV_ERROR,
                        entity=tid,
                        cycle=cycle,
                        message=(
                            f"new task ID {tid!r} has non-numeric tail; "
                            f"continuity check cannot order it"
                        ),
                    )
                )
                continue
            if n <= prior_max:
                findings.append(
                    DriftFinding(
                        kind=KIND_ID_CONTINUITY,
                        severity=SEV_ERROR,
                        entity=tid,
                        cycle=cycle,
                        message=(
                            f"new task {tid!r} (n={n}) not strictly above "
                            f"prior max {prior_max}; extend cycles must "
                            f"assign continuous IDs"
                        ),
                    )
                )
        consumed_ids |= set(new_task_ids)

    return findings


def _max_id_int(ids: set[str]) -> int:
    max_n = 0
    for tid in ids:
        try:
            n = int(tid.removeprefix("T-"))
        except ValueError:
            continue
        if n > max_n:
            max_n = n
    return max_n


def _check_status_audit(
    workspace: Path,
    dag: TaskDAG,
    project_id: str,
    audit_path: Path | None,
) -> list[DriftFinding]:
    """D4 — `task_status.json` says DONE but the audit log has no
    `worker_output_ok` for that task. Warning, not error, because:

      * manual `advance` calls can legitimately move tasks to DONE
        without a Worker turn (rare, but used during recovery)
      * audit log truncation / rotation can erase old events
      * the warning surfaces the inconsistency for human review
        without blocking automation
    """
    status_path = workspace / "task_status.json"
    if not status_path.exists():
        return []

    try:
        status = TaskStatusFile.model_validate_json(
            status_path.read_text(encoding="utf-8")
        )
    except (ValueError, OSError):
        return []

    audit_path = audit_path or Path(
        os.getenv("AUDIT_LOG_PATH", "./ortim/audit/decisions.jsonl")
    )
    if not audit_path.exists():
        return []

    tasks_with_worker_ok: set[str] = set()
    with audit_path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            if entry.get("project_id") != project_id:
                continue
            if entry.get("event") == "worker_output_ok":
                tid = entry.get("task_id")
                if isinstance(tid, str):
                    tasks_with_worker_ok.add(tid)

    dag_ids = {t.id for t in dag.tasks}
    findings: list[DriftFinding] = []
    for tid, record in status.records.items():
        if record.status != TaskStatus.DONE:
            continue
        if tid not in dag_ids:
            # Status references a task not in the DAG — separate
            # consistency issue, surface it.
            findings.append(
                DriftFinding(
                    kind=KIND_STATUS_AUDIT,
                    severity=SEV_WARNING,
                    entity=tid,
                    message=(
                        f"task_status records DONE for {tid!r} but the "
                        f"task is not in the DAG"
                    ),
                )
            )
            continue
        if tid not in tasks_with_worker_ok:
            findings.append(
                DriftFinding(
                    kind=KIND_STATUS_AUDIT,
                    severity=SEV_WARNING,
                    entity=tid,
                    message=(
                        f"task_status records DONE for {tid!r} but no "
                        f"worker_output_ok event in audit log (manual "
                        f"advance, log truncation, or genuine drift)"
                    ),
                )
            )

    return findings


def to_json_dict(report: DriftReport) -> dict:
    return {
        "project_id": report.project_id,
        "cycle_count": report.cycle_count,
        "error_count": len(report.errors),
        "warning_count": len(report.warnings),
        "findings": [
            {
                "kind": f.kind,
                "severity": f.severity,
                "entity": f.entity,
                "message": f.message,
                "cycle": f.cycle,
            }
            for f in report.findings
        ],
    }
