# SPDX-License-Identifier: FSL-1.1-Apache-2.0
# Copyright (c) 2026 ortim.dev
"""Dialog artifact storage + turn cap.

Covers the contracts the CLI commands and the agent flow depend on:
  - intent.md / stack.json+md / PRD.md round-trip through save/load
  - LockedStack JSON survives the persistence boundary unchanged
  - count_dialog_turns is monotonic across appends
  - dialog_mode_on respects ORTIM_DIALOG_MODE (default on)
  - turn_cap reads ORTIM_DIALOG_TURN_CAP and falls back to 10
  - non-dialog states cannot record turn history (programmer error)
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from ortim.architecture import LockedStack  # noqa: E402
from ortim.dialog import (  # noqa: E402
    DIALOG_MODE_ENV,
    DIALOG_TURN_CAP_DEFAULT,
    DIALOG_TURN_CAP_ENV,
    append_dialog_turn,
    count_dialog_turns,
    dialog_mode_on,
    load_intent_md,
    load_locked_stack,
    load_prd_md,
    save_intent_md,
    save_locked_stack,
    save_prd_md,
    turn_cap,
)
from ortim.orchestrator.state_machine import ProjectState  # noqa: E402


def _ws() -> Path:
    return Path(tempfile.mkdtemp())


def _sample_stack() -> LockedStack:
    return LockedStack(
        tier="T0",
        app_class="web",
        language="TypeScript",
        primary_framework="Node CLI",
        package_manager="npm",
        test_cmd="npx vitest run",
        run_cmd="npx tsx src/main.ts",
        key_libraries=["commander"],
        deploy_target="none",
        rationale="Single-binary CLI.",
    )


def test_intent_roundtrip() -> None:
    ws = _ws()
    assert load_intent_md(ws) is None
    save_intent_md(ws, "# Project Intent\nGoal: ...")
    assert load_intent_md(ws) == "# Project Intent\nGoal: ..."


def test_stack_roundtrip_preserves_all_fields() -> None:
    ws = _ws()
    assert load_locked_stack(ws) is None
    save_locked_stack(ws, _sample_stack())
    out = load_locked_stack(ws)
    assert out is not None
    assert out.language == "TypeScript"
    assert out.test_cmd == "npx vitest run"
    assert out.key_libraries == ["commander"]
    # stack.md is also written, even though downstream layers ignore it
    assert (ws / "stack.md").exists()
    md = (ws / "stack.md").read_text(encoding="utf-8")
    assert "TypeScript" in md
    assert "npx vitest run" in md


def test_prd_roundtrip() -> None:
    ws = _ws()
    assert load_prd_md(ws) is None
    save_prd_md(ws, "# PRD\n\n## Goals\n- ...")
    assert load_prd_md(ws) == "# PRD\n\n## Goals\n- ..."


def test_turn_counter_starts_at_zero_and_increments() -> None:
    ws = _ws()
    state = ProjectState.INTAKE_DIALOG
    assert count_dialog_turns(ws, state) == 0

    t1 = append_dialog_turn(ws, state, "first feedback", "response one")
    assert t1.turn_n == 1
    assert t1.had_feedback is True
    assert t1.feedback_hash != ""

    t2 = append_dialog_turn(ws, state, None, "response two")
    assert t2.turn_n == 2
    assert t2.had_feedback is False
    assert t2.feedback_hash == ""

    assert count_dialog_turns(ws, state) == 2


def test_turn_counters_are_per_state() -> None:
    ws = _ws()
    append_dialog_turn(ws, ProjectState.INTAKE_DIALOG, "x", "y")
    append_dialog_turn(ws, ProjectState.STACK_DIALOG, "a", "b")
    append_dialog_turn(ws, ProjectState.STACK_DIALOG, "c", "d")

    assert count_dialog_turns(ws, ProjectState.INTAKE_DIALOG) == 1
    assert count_dialog_turns(ws, ProjectState.STACK_DIALOG) == 2
    assert count_dialog_turns(ws, ProjectState.PRD_DIALOG) == 0


def test_non_dialog_state_cannot_record_turns() -> None:
    ws = _ws()
    try:
        append_dialog_turn(ws, ProjectState.PRD_DRAFTING, "x", "y")
    except ValueError:
        return
    raise AssertionError(
        "PRD_DRAFTING is not a dialog state; append_dialog_turn should reject"
    )


def test_dialog_mode_on_by_default(monkeypatch) -> None:
    monkeypatch.delenv(DIALOG_MODE_ENV, raising=False)
    assert dialog_mode_on() is True


def test_dialog_mode_off_when_explicitly_disabled(monkeypatch) -> None:
    monkeypatch.setenv(DIALOG_MODE_ENV, "off")
    assert dialog_mode_on() is False
    monkeypatch.setenv(DIALOG_MODE_ENV, "0")
    assert dialog_mode_on() is False
    monkeypatch.setenv(DIALOG_MODE_ENV, "FALSE")
    assert dialog_mode_on() is False


def test_turn_cap_default_when_unset(monkeypatch) -> None:
    monkeypatch.delenv(DIALOG_TURN_CAP_ENV, raising=False)
    assert turn_cap() == DIALOG_TURN_CAP_DEFAULT


def test_turn_cap_reads_env_and_clamps_to_one_minimum(monkeypatch) -> None:
    monkeypatch.setenv(DIALOG_TURN_CAP_ENV, "3")
    assert turn_cap() == 3
    monkeypatch.setenv(DIALOG_TURN_CAP_ENV, "0")
    assert turn_cap() == 1
    monkeypatch.setenv(DIALOG_TURN_CAP_ENV, "not-a-number")
    assert turn_cap() == DIALOG_TURN_CAP_DEFAULT
