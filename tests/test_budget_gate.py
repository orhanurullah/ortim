# SPDX-License-Identifier: FSL-1.1-Apache-2.0
# Copyright (c) 2026 ortim.dev
"""G7 budget gate wiring tests.

Detector + budget math live in `test_gate_detector.py` and
`test_budget_tracker.py`. This file pins:

  * `_maybe_open_budget_gate` transitions EXECUTING → BUDGET_AWAITING_APPROVAL
    when audit-derived spend reaches the cap, and is a no-op otherwise.
  * env-var contract: missing / invalid / non-positive `AI_FACTORY_BUDGET_CAP_USD`
    disables the gate entirely.
  * Audit event `gate_budget_opened` carries spend + cap + overage.
  * State machine round-trip via the `budget_approved` alias works.
"""

from __future__ import annotations

import json
import os
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
)


def _project_in_executing() -> Project:
    p = Project(name="t", initial_brief_tr="x")
    for step in [
        ProjectState.BABEL_PROCESSING,
        ProjectState.PRD_DRAFTING,
        ProjectState.MVP_SCOPE_LOCKING,
        ProjectState.PRD_AWAITING_APPROVAL,
        ProjectState.PRD_APPROVED,
        ProjectState.RFC_DRAFTING,
        ProjectState.RFC_AWAITING_APPROVAL,
        ProjectState.RFC_APPROVED,
        ProjectState.TASKS_GENERATING,
        ProjectState.TASKS_READY,
        ProjectState.EXECUTING,
    ]:
        p.transition(step, actor="test", note="setup")
    return p


def _write_synthetic_spend(audit_path: Path, project_id: str, usd: float) -> None:
    """Write an audit row whose token counts will cost `usd` USD under
    the default Anthropic Opus 4 pricing. Using inflated output tokens
    keeps the arithmetic simple ($75/M output) — 1M output tokens = $75."""
    record = {
        "event": "worker_output_ok",
        "project_id": project_id,
        "tokens": {"in": 0, "out": int((usd / 75.0) * 1_000_000)},
        "provider": "anthropic",
    }
    with audit_path.open("w", encoding="utf-8") as f:
        f.write(json.dumps(record) + "\n")


def _setup(tmp: Path, cap_usd: float | None) -> tuple[Project, AuditLogger]:
    project = _project_in_executing()
    audit_path = tmp / "audit.jsonl"
    audit_path.touch()
    audit = AuditLogger(path=audit_path)
    os.environ["AUDIT_LOG_PATH"] = str(audit_path)
    if cap_usd is not None:
        os.environ["AI_FACTORY_BUDGET_CAP_USD"] = str(cap_usd)
    else:
        os.environ.pop("AI_FACTORY_BUDGET_CAP_USD", None)
    return project, audit


def _teardown_env() -> None:
    os.environ.pop("AI_FACTORY_BUDGET_CAP_USD", None)
    os.environ.pop("AUDIT_LOG_PATH", None)


# ---------------------------------------------------------------------
# Helper behavior
# ---------------------------------------------------------------------


def test_gate_no_op_when_cap_env_unset() -> None:
    from runtime.main import _maybe_open_budget_gate

    with tempfile.TemporaryDirectory() as tmp:
        project, audit = _setup(Path(tmp), cap_usd=None)
        try:
            gated, spent, cap = _maybe_open_budget_gate(project, audit)
            assert gated is False
            assert cap == 0.0
            assert project.state == ProjectState.EXECUTING
        finally:
            _teardown_env()


def test_gate_no_op_when_cap_invalid() -> None:
    from runtime.main import _maybe_open_budget_gate

    with tempfile.TemporaryDirectory() as tmp:
        project, audit = _setup(Path(tmp), cap_usd=None)
        os.environ["AI_FACTORY_BUDGET_CAP_USD"] = "not-a-number"
        try:
            gated, _, cap = _maybe_open_budget_gate(project, audit)
            assert gated is False
            assert cap == 0.0
        finally:
            _teardown_env()


def test_gate_no_op_when_spend_below_cap() -> None:
    from runtime.main import _maybe_open_budget_gate

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        project, audit = _setup(tmp_path, cap_usd=1.0)
        _write_synthetic_spend(tmp_path / "audit.jsonl", project.id, usd=0.25)
        try:
            gated, spent, cap = _maybe_open_budget_gate(project, audit)
            assert gated is False
            assert cap == 1.0
            assert 0.24 < spent < 0.26
            assert project.state == ProjectState.EXECUTING
        finally:
            _teardown_env()


def test_gate_fires_and_transitions_when_spend_reaches_cap() -> None:
    from runtime.main import _maybe_open_budget_gate

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        project, audit = _setup(tmp_path, cap_usd=0.50)
        _write_synthetic_spend(tmp_path / "audit.jsonl", project.id, usd=0.60)
        try:
            gated, spent, cap = _maybe_open_budget_gate(project, audit)
            assert gated is True
            assert project.state == ProjectState.BUDGET_AWAITING_APPROVAL
            assert cap == 0.50
            assert spent >= 0.50
        finally:
            _teardown_env()


def test_gate_audit_event_includes_spent_cap_overage() -> None:
    from runtime.main import _maybe_open_budget_gate

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        project, audit = _setup(tmp_path, cap_usd=1.00)
        _write_synthetic_spend(tmp_path / "audit.jsonl", project.id, usd=1.50)
        audit_path = tmp_path / "audit.jsonl"
        try:
            gated, _, _ = _maybe_open_budget_gate(project, audit)
            assert gated
            events = [
                json.loads(line)
                for line in audit_path.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            opened = [e for e in events if e.get("event") == "gate_budget_opened"]
            assert len(opened) == 1
            ev = opened[0]
            assert ev["cap_usd"] == 1.00
            assert ev["spent_usd"] >= 1.00
            assert ev["overage_pct"] >= 100.0
        finally:
            _teardown_env()


def test_gate_does_not_refire_when_project_already_gated() -> None:
    """Idempotency: state guard prevents the gate from re-firing on a
    project that's already in BUDGET_AWAITING_APPROVAL."""
    from runtime.main import _maybe_open_budget_gate

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        project, audit = _setup(tmp_path, cap_usd=0.50)
        _write_synthetic_spend(tmp_path / "audit.jsonl", project.id, usd=0.75)
        try:
            # First call gates the project.
            first, _, _ = _maybe_open_budget_gate(project, audit)
            assert first is True
            # Second call must NOT transition (project is no longer EXECUTING).
            second, _, _ = _maybe_open_budget_gate(project, audit)
            assert second is False
            assert project.state == ProjectState.BUDGET_AWAITING_APPROVAL
        finally:
            _teardown_env()


# ---------------------------------------------------------------------
# State machine — the budget_approved round-trip
# ---------------------------------------------------------------------


def test_state_machine_round_trip_via_budget_approved() -> None:
    """EXECUTING → BUDGET_AWAITING_APPROVAL → EXECUTING is the legal
    approval path the `advance budget_approved` alias resolves to."""
    project = _project_in_executing()
    project.transition(
        ProjectState.BUDGET_AWAITING_APPROVAL,
        actor="executor",
        note="cap breached",
    )
    project.transition(
        ProjectState.EXECUTING, actor="cli-manual", note="approved"
    )
    assert project.state == ProjectState.EXECUTING


def test_state_machine_blocks_skip_past_budget_gate() -> None:
    """A project in BUDGET_AWAITING_APPROVAL must not be able to leap
    directly to DONE; only an explicit EXECUTING approval (or PAUSED/
    FAILED) is permitted."""
    project = _project_in_executing()
    project.transition(
        ProjectState.BUDGET_AWAITING_APPROVAL,
        actor="executor",
        note="cap breached",
    )
    with pytest.raises(InvalidTransition):
        project.transition(
            ProjectState.DONE, actor="test", note="should fail"
        )
