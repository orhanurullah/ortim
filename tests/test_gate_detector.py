# SPDX-License-Identifier: FSL-1.1-Apache-2.0
# Copyright (c) 2026 ortim.dev
"""Smoke tests for HITL gate detectors (Faz 6c).

Detectors are pure functions; tests exercise positive/negative cases on
synthetic DAGs and WorkerOutputs without any LLM call.
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from runtime.budget import BudgetTracker  # noqa: E402
from runtime.executor.worker import FileChange, WorkerOutput  # noqa: E402
from runtime.orchestrator import (  # noqa: E402
    TaskDAG,
    TaskSpec,
    detect_budget_breach,
    detect_external_calls,
    detect_schema_tasks,
    detect_security_severity,
)


def _task(
    tid: str = "T-001",
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


# ---- G3 ----------------------------------------------------------------------


def test_schema_keyword_in_description_triggers() -> None:
    dag = TaskDAG(project_id="P", tasks=[_task(tid="T-001", desc="Add Alembic migration for users")])
    ev = detect_schema_tasks(dag)
    assert ev.triggered
    assert ev.task_ids == ("T-001",)


def test_schema_keyword_in_path_triggers() -> None:
    dag = TaskDAG(
        project_id="P",
        tasks=[_task(tid="T-002", scope="alembic/versions", title="add", desc="x")],
    )
    ev = detect_schema_tasks(dag)
    assert ev.triggered


def test_schema_no_match_is_quiet() -> None:
    dag = TaskDAG(
        project_id="P",
        tasks=[
            _task(tid="T-001", title="Add login endpoint", desc="POST /login"),
            _task(tid="T-002", title="Add logger", desc="structured JSON logs"),
        ],
    )
    ev = detect_schema_tasks(dag)
    assert not ev.triggered
    assert ev.task_ids == ()


# ---- G4 ----------------------------------------------------------------------


def test_external_import_boto3_triggers() -> None:
    out = WorkerOutput(
        task_id="T-001",
        summary="x",
        files=[
            FileChange(path="src/x.py", content="import boto3\nclient = boto3.client('s3')\n"),
        ],
    )
    ev = detect_external_calls(out)
    assert ev.triggered
    assert any("src/x.py" == fp for fp, _ in ev.matches)


def test_external_url_triggers() -> None:
    out = WorkerOutput(
        task_id="T-001",
        summary="x",
        files=[
            FileChange(
                path="src/api.py",
                content="URL = 'https://api.stripe.com/v1/charges'\n",
            ),
        ],
    )
    ev = detect_external_calls(out)
    assert ev.triggered


def test_localhost_url_does_not_trigger() -> None:
    out = WorkerOutput(
        task_id="T-001",
        summary="x",
        files=[
            FileChange(path="src/api.py", content="URL = 'http://localhost:8080/'\n"),
        ],
    )
    ev = detect_external_calls(out)
    assert not ev.triggered


def test_no_external_returns_empty() -> None:
    out = WorkerOutput(
        task_id="T-001",
        summary="x",
        files=[FileChange(path="src/util.py", content="def add(a, b): return a + b\n")],
    )
    ev = detect_external_calls(out)
    assert not ev.triggered
    assert ev.matches == ()


# ---- G5 ----------------------------------------------------------------------


class _DummyVerdict:
    def __init__(self, severity: str | None, reasons: list[str]):
        self.severity = severity
        self.reasons = reasons


def test_security_high_triggers() -> None:
    ev = detect_security_severity(_DummyVerdict("high", ["sql injection"]))
    assert ev.triggered
    assert ev.severity == "high"


def test_security_medium_triggers() -> None:
    ev = detect_security_severity(_DummyVerdict("medium", ["weak hash"]))
    assert ev.triggered


def test_security_low_does_not_trigger() -> None:
    ev = detect_security_severity(_DummyVerdict("low", ["minor note"]))
    assert not ev.triggered


def test_security_none_does_not_trigger() -> None:
    ev = detect_security_severity(None)
    assert not ev.triggered
    assert ev.severity is None


# ---- G7 ----------------------------------------------------------------------


def _audit_with_cost(path: Path, in_tok: int, out_tok: int) -> None:
    rec = {
        "project_id": "P", "provider": "anthropic",
        "tokens": {"in": in_tok, "out": out_tok},
    }
    path.write_text(json.dumps(rec) + "\n", encoding="utf-8")


def test_budget_under_cap_does_not_trigger() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "audit.jsonl"
        _audit_with_cost(path, 100, 100)  # < $0.01
        ev = detect_budget_breach(BudgetTracker(audit_path=path), "P", cap_usd=10.0)
        assert not ev.triggered


def test_budget_over_cap_triggers() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "audit.jsonl"
        # $1M tok at anthropic price = $15 in + $75 out = $90, easily over $1
        _audit_with_cost(path, 1_000_000, 1_000_000)
        ev = detect_budget_breach(BudgetTracker(audit_path=path), "P", cap_usd=1.0)
        assert ev.triggered
        assert ev.spent_usd >= ev.cap_usd
        assert ev.overage_pct > 100


if __name__ == "__main__":
    tests = [
        test_schema_keyword_in_description_triggers,
        test_schema_keyword_in_path_triggers,
        test_schema_no_match_is_quiet,
        test_external_import_boto3_triggers,
        test_external_url_triggers,
        test_localhost_url_does_not_trigger,
        test_no_external_returns_empty,
        test_security_high_triggers,
        test_security_medium_triggers,
        test_security_low_does_not_trigger,
        test_security_none_does_not_trigger,
        test_budget_under_cap_does_not_trigger,
        test_budget_over_cap_triggers,
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
