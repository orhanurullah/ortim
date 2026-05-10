# SPDX-License-Identifier: FSL-1.1-Apache-2.0
# Copyright (c) 2026 ortim.dev
"""Smoke tests for state machine - stdlib-only (no pydantic/typer needed)."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from runtime.orchestrator.state_machine import (  # noqa: E402
    HITL_GATES,
    TRANSITIONS,
    InvalidTransition,
    ProjectState,
    validate_transition,
)


def test_all_states_have_transition_entry() -> None:
    for state in ProjectState:
        assert state in TRANSITIONS, f"State {state.value} missing from TRANSITIONS"


def test_terminal_states_have_no_transitions() -> None:
    assert TRANSITIONS[ProjectState.DONE] == set()
    assert TRANSITIONS[ProjectState.FAILED] == set()


def test_happy_path_transitions_are_valid() -> None:
    chain = [
        ProjectState.INTAKE,
        ProjectState.BABEL_PROCESSING,
        ProjectState.PRD_DRAFTING,
        ProjectState.PRD_AWAITING_APPROVAL,
        ProjectState.PRD_APPROVED,
        ProjectState.RFC_DRAFTING,
        ProjectState.RFC_AWAITING_APPROVAL,
        ProjectState.RFC_APPROVED,
        ProjectState.TASKS_GENERATING,
        ProjectState.TASKS_READY,
        ProjectState.EXECUTING,
        ProjectState.DONE,
    ]
    for current, target in zip(chain[:-1], chain[1:], strict=True):
        validate_transition(current, target)


def test_skipping_prd_approval_is_blocked() -> None:
    try:
        validate_transition(ProjectState.PRD_DRAFTING, ProjectState.RFC_DRAFTING)
    except InvalidTransition:
        return
    raise AssertionError("Expected InvalidTransition when skipping PRD approval")


def test_skipping_rfc_approval_is_blocked() -> None:
    try:
        validate_transition(ProjectState.RFC_DRAFTING, ProjectState.EXECUTING)
    except InvalidTransition:
        return
    raise AssertionError("Expected InvalidTransition when skipping RFC approval")


def test_hitl_gates_at_approval_states() -> None:
    assert ProjectState.PRD_AWAITING_APPROVAL in HITL_GATES
    assert ProjectState.RFC_AWAITING_APPROVAL in HITL_GATES


def test_revision_loop_allowed_after_pending_approval() -> None:
    validate_transition(
        ProjectState.PRD_AWAITING_APPROVAL, ProjectState.PRD_DRAFTING
    )
    validate_transition(
        ProjectState.RFC_AWAITING_APPROVAL, ProjectState.RFC_DRAFTING
    )


def test_pause_resume_paths() -> None:
    validate_transition(ProjectState.EXECUTING, ProjectState.PAUSED)
    validate_transition(ProjectState.PAUSED, ProjectState.EXECUTING)


if __name__ == "__main__":
    tests = [
        test_all_states_have_transition_entry,
        test_terminal_states_have_no_transitions,
        test_happy_path_transitions_are_valid,
        test_skipping_prd_approval_is_blocked,
        test_skipping_rfc_approval_is_blocked,
        test_hitl_gates_at_approval_states,
        test_revision_loop_allowed_after_pending_approval,
        test_pause_resume_paths,
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
