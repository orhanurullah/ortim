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
    PRD_DRAFTING = "prd_drafting"
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


TRANSITIONS: dict[ProjectState, set[ProjectState]] = {
    ProjectState.INTAKE: {
        ProjectState.BABEL_PROCESSING,
        ProjectState.PRD_DRAFTING,  # M1 brownfield: skip Babel when codebase + EN brief
        ProjectState.FAILED,
    },
    ProjectState.BABEL_PROCESSING: {ProjectState.PRD_DRAFTING, ProjectState.FAILED},
    ProjectState.PRD_DRAFTING: {ProjectState.PRD_AWAITING_APPROVAL, ProjectState.FAILED},
    ProjectState.PRD_AWAITING_APPROVAL: {
        ProjectState.PRD_APPROVED,
        ProjectState.PRD_DRAFTING,
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
        ProjectState.PRD_DRAFTING,
        ProjectState.RFC_DRAFTING,
        ProjectState.TASKS_READY,
        ProjectState.EXECUTING,
        ProjectState.SCHEMA_AWAITING_APPROVAL,
        ProjectState.BUDGET_AWAITING_APPROVAL,
        ProjectState.DEPLOY_AWAITING_APPROVAL,
        ProjectState.FAILED,
    },
    ProjectState.DONE: set(),
    ProjectState.FAILED: set(),
}


HITL_GATES: dict[ProjectState, str] = {
    ProjectState.PRD_AWAITING_APPROVAL: "G1: PRD review",
    ProjectState.RFC_AWAITING_APPROVAL: "G2: RFC + Golden Path review",
    ProjectState.SCHEMA_AWAITING_APPROVAL: "G3: Schema/migration review",
    ProjectState.BUDGET_AWAITING_APPROVAL: "G7: Budget cap review",
    ProjectState.DEPLOY_AWAITING_APPROVAL: "G6: Deploy approval",
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
