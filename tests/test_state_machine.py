# SPDX-License-Identifier: FSL-1.1-Apache-2.0
# Copyright (c) 2026 ortim.dev
"""Smoke tests for state machine - stdlib-only (no pydantic/typer needed)."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ortim.orchestrator.state_machine import (  # noqa: E402
    HITL_GATES,
    TRANSITIONS,
    InvalidTransition,
    ProjectState,
    validate_transition,
)


def test_all_states_have_transition_entry() -> None:
    for state in ProjectState:
        assert state in TRANSITIONS, f"State {state.value} missing from TRANSITIONS"


def test_failed_is_truly_terminal() -> None:
    """FAILED has no out-transitions — once a project fails it must be
    inspected manually. DONE used to be terminal too, but M3.1 added
    `DONE -> EXTEND_DIALOG` so DONE is now a re-entry point for `ortim
    extend`. See test_extend_entry_point_from_done for that path."""
    assert TRANSITIONS[ProjectState.FAILED] == set()


def test_extend_entry_point_from_done() -> None:
    """M3.1 — `ortim extend` is the only valid action from DONE.
    DONE has exactly one out-transition (EXTEND_DIALOG); preserving the
    'project is shippable' invariant while enabling iterative dev."""
    assert TRANSITIONS[ProjectState.DONE] == {ProjectState.EXTEND_DIALOG}


def test_happy_path_transitions_are_valid() -> None:
    chain = [
        ProjectState.INTAKE,
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


def test_skipping_scope_locking_is_blocked() -> None:
    """Faz 1.1 — PRD_DRAFTING cannot jump directly to PRD_AWAITING_APPROVAL.
    The user must pass through MVP_SCOPE_LOCKING first so each feature
    has an explicit phase assignment."""
    try:
        validate_transition(
            ProjectState.PRD_DRAFTING, ProjectState.PRD_AWAITING_APPROVAL
        )
    except InvalidTransition:
        return
    raise AssertionError(
        "Expected InvalidTransition when skipping MVP_SCOPE_LOCKING"
    )


def test_mvp_scope_locking_advance_and_backstep() -> None:
    """MVP_SCOPE_LOCKING advances to PRD_AWAITING_APPROVAL (G1) and can
    step back to either PRD_DIALOG (M2 path) or PRD_DRAFTING (legacy)."""
    validate_transition(
        ProjectState.MVP_SCOPE_LOCKING, ProjectState.PRD_AWAITING_APPROVAL
    )
    validate_transition(
        ProjectState.MVP_SCOPE_LOCKING, ProjectState.PRD_DIALOG
    )
    validate_transition(
        ProjectState.MVP_SCOPE_LOCKING, ProjectState.PRD_DRAFTING
    )


def test_prd_awaiting_approval_can_rescope() -> None:
    """G1 reviewer that wants to rescope before signing returns to
    MVP_SCOPE_LOCKING rather than fully redrafting the PRD."""
    validate_transition(
        ProjectState.PRD_AWAITING_APPROVAL, ProjectState.MVP_SCOPE_LOCKING
    )


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


# ---- M2 conversational intake & stack iteration ----


def test_m2_dialog_happy_path_is_valid() -> None:
    """Babel -> Intent dialog -> Stack dialog -> PRD dialog -> approval gate.

    Verifies the new conversational flow can chain end-to-end without
    bumping into the legacy gates. The PRD_AWAITING_APPROVAL gate is reused
    so HITL ergonomics stay identical from there on.
    """
    chain = [
        ProjectState.BABEL_PROCESSING,
        ProjectState.INTAKE_DIALOG,
        ProjectState.STACK_DIALOG,
        ProjectState.PRD_DIALOG,
        ProjectState.MVP_SCOPE_LOCKING,
        ProjectState.PRD_AWAITING_APPROVAL,
    ]
    for current, target in zip(chain[:-1], chain[1:], strict=True):
        validate_transition(current, target)


def test_m2_dialog_back_steps_are_valid() -> None:
    """STACK_DIALOG -> INTAKE_DIALOG and PRD_DIALOG -> STACK_DIALOG are
    legal back-steps so the user can rework an upstream artifact without
    abandoning the project."""
    validate_transition(ProjectState.STACK_DIALOG, ProjectState.INTAKE_DIALOG)
    validate_transition(ProjectState.PRD_DIALOG, ProjectState.STACK_DIALOG)


def test_m2_dialog_skip_to_approval_is_blocked() -> None:
    """INTAKE_DIALOG cannot jump directly to PRD_AWAITING_APPROVAL — the
    stack and PRD dialogs must run first. Same shape as the legacy
    PRD_DRAFTING -> RFC_DRAFTING guard."""
    try:
        validate_transition(
            ProjectState.INTAKE_DIALOG, ProjectState.PRD_AWAITING_APPROVAL
        )
    except InvalidTransition:
        return
    raise AssertionError(
        "Expected InvalidTransition when skipping stack + PRD dialogs"
    )


def test_legacy_babel_to_prd_drafting_still_valid() -> None:
    """ORTIM_DIALOG_MODE=off path: BABEL_PROCESSING can still go
    directly to PRD_DRAFTING, so the legacy fixture/test stays green."""
    validate_transition(ProjectState.BABEL_PROCESSING, ProjectState.PRD_DRAFTING)


# ---- M3.1 `ortim extend` cycle ----


def test_m3_1_extend_happy_path_is_valid() -> None:
    """`ortim extend <id> "<brief>"` cycle: DONE -> EXTEND_DIALOG ->
    EXTEND_PRD_DIALOG -> EXTEND_PRD_AWAITING_APPROVAL -> EXTEND_PRD_APPROVED
    -> EXTEND_RFC_DRAFTING -> EXTEND_RFC_AWAITING_APPROVAL ->
    EXTEND_RFC_APPROVED -> TASKS_GENERATING. From TASKS_GENERATING the
    existing chain takes over."""
    chain = [
        ProjectState.DONE,
        ProjectState.EXTEND_DIALOG,
        ProjectState.EXTEND_PRD_DIALOG,
        ProjectState.EXTEND_PRD_AWAITING_APPROVAL,
        ProjectState.EXTEND_PRD_APPROVED,
        ProjectState.EXTEND_RFC_DRAFTING,
        ProjectState.EXTEND_RFC_AWAITING_APPROVAL,
        ProjectState.EXTEND_RFC_APPROVED,
        ProjectState.TASKS_GENERATING,
        ProjectState.TASKS_READY,
        ProjectState.EXECUTING,
        ProjectState.DONE,
    ]
    for current, target in zip(chain[:-1], chain[1:], strict=True):
        validate_transition(current, target)


def test_m3_1_extend_skip_g1_is_blocked() -> None:
    """EXTEND_PRD_DIALOG cannot jump straight to EXTEND_PRD_APPROVED —
    G1 (cycle N) must fire. Same shape as the legacy PRD_DRAFTING ->
    PRD_AWAITING_APPROVAL -> PRD_APPROVED guard."""
    try:
        validate_transition(
            ProjectState.EXTEND_PRD_DIALOG, ProjectState.EXTEND_PRD_APPROVED
        )
    except InvalidTransition:
        return
    raise AssertionError(
        "Expected InvalidTransition when skipping G1 in extend cycle"
    )


def test_m3_1_extend_skip_g2_is_blocked() -> None:
    """EXTEND_RFC_DRAFTING cannot jump straight to EXTEND_RFC_APPROVED —
    G2 (cycle N) must fire."""
    try:
        validate_transition(
            ProjectState.EXTEND_RFC_DRAFTING, ProjectState.EXTEND_RFC_APPROVED
        )
    except InvalidTransition:
        return
    raise AssertionError(
        "Expected InvalidTransition when skipping G2 in extend cycle"
    )


def test_m3_1_extend_back_steps_are_valid() -> None:
    """EXTEND_PRD_DIALOG -> EXTEND_DIALOG and EXTEND_PRD_AWAITING_APPROVAL
    -> EXTEND_PRD_DIALOG must be valid back-steps so the user can rework
    a delta artifact mid-cycle without abandoning the extension."""
    validate_transition(
        ProjectState.EXTEND_PRD_DIALOG, ProjectState.EXTEND_DIALOG
    )
    validate_transition(
        ProjectState.EXTEND_PRD_AWAITING_APPROVAL, ProjectState.EXTEND_PRD_DIALOG
    )
    validate_transition(
        ProjectState.EXTEND_RFC_AWAITING_APPROVAL, ProjectState.EXTEND_RFC_DRAFTING
    )


def test_m3_1_extend_hitl_gates_registered() -> None:
    """G1 (cycle N) and G2 (cycle N) must appear in HITL_GATES so
    `ortim gates <id>` surfaces them with the cycle disambiguation."""
    assert ProjectState.EXTEND_PRD_AWAITING_APPROVAL in HITL_GATES
    assert ProjectState.EXTEND_RFC_AWAITING_APPROVAL in HITL_GATES
    assert "extend" in HITL_GATES[ProjectState.EXTEND_PRD_AWAITING_APPROVAL].lower()
    assert "extend" in HITL_GATES[ProjectState.EXTEND_RFC_AWAITING_APPROVAL].lower()


def test_m3_1_extend_pause_resume_works() -> None:
    """Mid-extend the user can pause; resuming from PAUSED back into
    EXTEND_DIALOG / EXTEND_PRD_DIALOG / EXTEND_RFC_DRAFTING must be
    legal so a multi-day extend cycle isn't a one-shot commitment."""
    validate_transition(ProjectState.EXTEND_DIALOG, ProjectState.PAUSED)
    validate_transition(ProjectState.PAUSED, ProjectState.EXTEND_DIALOG)
    validate_transition(ProjectState.PAUSED, ProjectState.EXTEND_PRD_DIALOG)
    validate_transition(ProjectState.PAUSED, ProjectState.EXTEND_RFC_DRAFTING)


if __name__ == "__main__":
    tests = [
        test_all_states_have_transition_entry,
        test_failed_is_truly_terminal,
        test_extend_entry_point_from_done,
        test_happy_path_transitions_are_valid,
        test_skipping_prd_approval_is_blocked,
        test_skipping_rfc_approval_is_blocked,
        test_hitl_gates_at_approval_states,
        test_revision_loop_allowed_after_pending_approval,
        test_pause_resume_paths,
        test_m2_dialog_happy_path_is_valid,
        test_m2_dialog_back_steps_are_valid,
        test_m2_dialog_skip_to_approval_is_blocked,
        test_legacy_babel_to_prd_drafting_still_valid,
        test_m3_1_extend_happy_path_is_valid,
        test_m3_1_extend_skip_g1_is_blocked,
        test_m3_1_extend_skip_g2_is_blocked,
        test_m3_1_extend_back_steps_are_valid,
        test_m3_1_extend_hitl_gates_registered,
        test_m3_1_extend_pause_resume_works,
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
