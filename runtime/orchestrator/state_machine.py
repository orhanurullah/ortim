# SPDX-License-Identifier: FSL-1.1-Apache-2.0
# Copyright (c) 2026 ortim.dev
"""Project lifecycle state machine.

States are explicit and transitions are validated. Any attempt to transition
to a non-allowed next state raises InvalidTransition.

An LLM-driven orchestrator can otherwise "decide" to skip approval gates;
the state machine makes those gates structural, not advisory.
"""

from __future__ import annotations

from enum import Enum


class ProjectState(str, Enum):
    INTAKE = "intake"
    BABEL_PROCESSING = "babel_processing"
    # M2 dialog states. Engaged when AI_FACTORY_DIALOG_MODE=on (default).
    # Legacy direct BABEL_PROCESSING -> PRD_DRAFTING transition is preserved
    # for AI_FACTORY_DIALOG_MODE=off and for older fixtures/tests.
    INTAKE_DIALOG = "intake_dialog"
    STACK_DIALOG = "stack_dialog"
    PRD_DIALOG = "prd_dialog"
    PRD_DRAFTING = "prd_drafting"
    # Faz 1.1 — MVP scope locking. Sits between PRD draft and G1 so the
    # user assigns phase + priority to each feature before signing the
    # PRD. The Architect (Call 2 / RFC) and Orchestrator (DAG) consume
    # `scope.json` to emit Phase 1 modules separately from Phase 2+.
    MVP_SCOPE_LOCKING = "mvp_scope_locking"
    PRD_AWAITING_APPROVAL = "prd_awaiting_approval"
    PRD_APPROVED = "prd_approved"
    RFC_DRAFTING = "rfc_drafting"
    RFC_AWAITING_APPROVAL = "rfc_awaiting_approval"
    RFC_APPROVED = "rfc_approved"
    TASKS_GENERATING = "tasks_generating"
    TASKS_READY = "tasks_ready"
    SCHEMA_AWAITING_APPROVAL = "schema_awaiting_approval"  # G3
    EXECUTING = "executing"
    BUDGET_AWAITING_APPROVAL = "budget_awaiting_approval"  # G7
    DEPLOY_AWAITING_APPROVAL = "deploy_awaiting_approval"  # G6
    DONE = "done"
    FAILED = "failed"
    PAUSED = "paused"
    # M3.1 — `ortim extend`: iterative dev on shipped projects. After DONE,
    # `ortim extend <id> "<feature brief>"` enters EXTEND_DIALOG; the cycle
    # mirrors the initial flow (intent → PRD → G1 → RFC → G2 → DAG → exec)
    # but skips StackAnalyst (LockedStack is locked forever) and treats
    # PRD/RFC as append-only sections rather than full rewrites.
    EXTEND_DIALOG = "extend_dialog"
    EXTEND_PRD_DIALOG = "extend_prd_dialog"
    EXTEND_PRD_AWAITING_APPROVAL = "extend_prd_awaiting_approval"   # G1 cycle N
    EXTEND_PRD_APPROVED = "extend_prd_approved"
    EXTEND_RFC_DRAFTING = "extend_rfc_drafting"
    EXTEND_RFC_AWAITING_APPROVAL = "extend_rfc_awaiting_approval"   # G2 cycle N
    EXTEND_RFC_APPROVED = "extend_rfc_approved"


TRANSITIONS: dict[ProjectState, set[ProjectState]] = {
    ProjectState.INTAKE: {
        ProjectState.BABEL_PROCESSING,
        ProjectState.PRD_DRAFTING,  # M1 brownfield: skip Babel when codebase + EN brief
        ProjectState.FAILED,
    },
    ProjectState.BABEL_PROCESSING: {
        ProjectState.PRD_DRAFTING,        # legacy / AI_FACTORY_DIALOG_MODE=off
        ProjectState.INTAKE_DIALOG,       # M2 default: enter conversational intake
        ProjectState.FAILED,
    },
    ProjectState.INTAKE_DIALOG: {
        ProjectState.STACK_DIALOG,        # lock intent → advance
        ProjectState.PAUSED,
        ProjectState.FAILED,
    },
    ProjectState.STACK_DIALOG: {
        ProjectState.PRD_DIALOG,          # lock stack → advance
        ProjectState.INTAKE_DIALOG,       # back-step: rework intent
        ProjectState.PAUSED,
        ProjectState.FAILED,
    },
    ProjectState.PRD_DIALOG: {
        ProjectState.MVP_SCOPE_LOCKING,      # PRD draft ready → assign phase to features
        ProjectState.STACK_DIALOG,           # back-step: rework stack
        ProjectState.PAUSED,
        ProjectState.FAILED,
    },
    ProjectState.PRD_DRAFTING: {
        ProjectState.MVP_SCOPE_LOCKING,      # legacy / dialog-mode-off path
        ProjectState.FAILED,
    },
    ProjectState.MVP_SCOPE_LOCKING: {
        ProjectState.PRD_AWAITING_APPROVAL,  # scope locked → G1
        ProjectState.PRD_DIALOG,             # back-step: rework PRD
        ProjectState.PRD_DRAFTING,           # back-step (dialog-mode-off path)
        ProjectState.PAUSED,
        ProjectState.FAILED,
    },
    ProjectState.PRD_AWAITING_APPROVAL: {
        ProjectState.PRD_APPROVED,
        ProjectState.PRD_DRAFTING,
        ProjectState.MVP_SCOPE_LOCKING,      # reviewer wants to rescope before approving
        ProjectState.PAUSED,
        ProjectState.FAILED,
    },
    ProjectState.PRD_APPROVED: {ProjectState.RFC_DRAFTING},
    ProjectState.RFC_DRAFTING: {ProjectState.RFC_AWAITING_APPROVAL, ProjectState.FAILED},
    ProjectState.RFC_AWAITING_APPROVAL: {
        ProjectState.RFC_APPROVED,
        ProjectState.RFC_DRAFTING,
        ProjectState.PAUSED,
        ProjectState.FAILED,
    },
    ProjectState.RFC_APPROVED: {ProjectState.TASKS_GENERATING},
    ProjectState.TASKS_GENERATING: {ProjectState.TASKS_READY, ProjectState.FAILED},
    ProjectState.TASKS_READY: {
        ProjectState.EXECUTING,
        ProjectState.SCHEMA_AWAITING_APPROVAL,  # G3 detour when DAG has schema/migration task
        ProjectState.PAUSED,
    },
    ProjectState.SCHEMA_AWAITING_APPROVAL: {
        ProjectState.EXECUTING,         # human approved the schema plan
        ProjectState.TASKS_READY,       # send back for DAG revision
        ProjectState.PAUSED,
        ProjectState.FAILED,
    },
    ProjectState.EXECUTING: {
        ProjectState.DONE,
        ProjectState.DEPLOY_AWAITING_APPROVAL,  # G6 when deploy task present
        ProjectState.BUDGET_AWAITING_APPROVAL,  # G7 when cap breached mid-run
        ProjectState.FAILED,
        ProjectState.PAUSED,
    },
    ProjectState.BUDGET_AWAITING_APPROVAL: {
        ProjectState.EXECUTING,         # human raised the cap or accepted overage
        ProjectState.PAUSED,
        ProjectState.FAILED,
    },
    ProjectState.DEPLOY_AWAITING_APPROVAL: {
        ProjectState.DONE,              # deploy approved + executed
        ProjectState.EXECUTING,         # bounce back for revisions
        ProjectState.PAUSED,
        ProjectState.FAILED,
    },
    ProjectState.PAUSED: {
        ProjectState.INTAKE_DIALOG,
        ProjectState.STACK_DIALOG,
        ProjectState.PRD_DIALOG,
        ProjectState.PRD_DRAFTING,
        ProjectState.MVP_SCOPE_LOCKING,
        ProjectState.RFC_DRAFTING,
        ProjectState.TASKS_READY,
        ProjectState.EXECUTING,
        ProjectState.SCHEMA_AWAITING_APPROVAL,
        ProjectState.BUDGET_AWAITING_APPROVAL,
        ProjectState.DEPLOY_AWAITING_APPROVAL,
        # M3.1 extend states — pause/resume mid-cycle.
        ProjectState.EXTEND_DIALOG,
        ProjectState.EXTEND_PRD_DIALOG,
        ProjectState.EXTEND_RFC_DRAFTING,
        ProjectState.FAILED,
    },
    ProjectState.DONE: {
        ProjectState.EXTEND_DIALOG,     # M3.1 — `ortim extend <id> "<brief>"`
    },
    ProjectState.FAILED: set(),
    # M3.1 extend cycle. Mirrors the initial flow (intent → PRD → G1 → RFC →
    # G2 → DAG) but stops at TASKS_GENERATING; from there the existing
    # TASKS_GENERATING → TASKS_READY → EXECUTING → DONE chain takes over.
    # Existing DONE tasks stay DONE; only newly-emitted PENDING tasks run.
    ProjectState.EXTEND_DIALOG: {
        ProjectState.EXTEND_PRD_DIALOG,
        ProjectState.PAUSED,
        ProjectState.FAILED,
    },
    ProjectState.EXTEND_PRD_DIALOG: {
        ProjectState.EXTEND_PRD_AWAITING_APPROVAL,  # lock delta PRD → G1 (cycle N)
        ProjectState.EXTEND_DIALOG,                 # back-step: rework intent
        ProjectState.PAUSED,
        ProjectState.FAILED,
    },
    ProjectState.EXTEND_PRD_AWAITING_APPROVAL: {
        ProjectState.EXTEND_PRD_APPROVED,
        ProjectState.EXTEND_PRD_DIALOG,             # bounce back for revision
        ProjectState.PAUSED,
        ProjectState.FAILED,
    },
    ProjectState.EXTEND_PRD_APPROVED: {ProjectState.EXTEND_RFC_DRAFTING},
    ProjectState.EXTEND_RFC_DRAFTING: {
        ProjectState.EXTEND_RFC_AWAITING_APPROVAL,
        ProjectState.FAILED,
    },
    ProjectState.EXTEND_RFC_AWAITING_APPROVAL: {
        ProjectState.EXTEND_RFC_APPROVED,
        ProjectState.EXTEND_RFC_DRAFTING,           # bounce back for revision
        ProjectState.PAUSED,
        ProjectState.FAILED,
    },
    ProjectState.EXTEND_RFC_APPROVED: {ProjectState.TASKS_GENERATING},
}


HITL_GATES: dict[ProjectState, str] = {
    ProjectState.PRD_AWAITING_APPROVAL: "G1: PRD review",
    ProjectState.RFC_AWAITING_APPROVAL: "G2: RFC + Golden Path review",
    ProjectState.SCHEMA_AWAITING_APPROVAL: "G3: Schema/migration review",
    ProjectState.BUDGET_AWAITING_APPROVAL: "G7: Budget cap review",
    ProjectState.DEPLOY_AWAITING_APPROVAL: "G6: Deploy approval",
    # M3.1 — G1 and G2 fire again per extend cycle. The state names
    # disambiguate "extending project" from "fresh project" in audits + UX.
    ProjectState.EXTEND_PRD_AWAITING_APPROVAL: "G1: PRD review (extend cycle)",
    ProjectState.EXTEND_RFC_AWAITING_APPROVAL: "G2: RFC review (extend cycle)",
}

# Task-level gates surface via task_status.AWAITING_HITL rather than a project
# state. Two known triggers, both wired in the executor:
#   - G4 (external integration): a Worker output adds a new external SDK/URL
#   - G5 (security): SecurityReviewer hard veto with severity=high|medium


class InvalidTransition(Exception):
    pass


def validate_transition(current: ProjectState, target: ProjectState) -> None:
    allowed = TRANSITIONS.get(current, set())
    if target not in allowed:
        allowed_names = sorted(s.value for s in allowed) or ["<terminal>"]
        raise InvalidTransition(
            f"Cannot transition {current.value} -> {target.value}. "
            f"Allowed: {allowed_names}"
        )
