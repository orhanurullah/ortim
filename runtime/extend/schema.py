# SPDX-License-Identifier: FSL-1.1-Apache-2.0
# Copyright (c) 2026 ortim.dev
"""M3.1 extend cycle schemas.

Two records:
- `ExtensionIntent` — the per-cycle delta brief, structured. Mirrors
  `runtime.babel.intent.StructuredIntent` shape so the IntentAnalyst
  prompts that consume it can be (largely) reused.
- `DagDelta` — the slice of `TaskDAG` added by one extend cycle. The
  parent `TaskDAG` carries `extensions: list[DagDelta]` for audit /
  status rendering; existing tasks stay in `TaskDAG.tasks`.
"""

from __future__ import annotations

from pydantic import BaseModel, Field, field_validator

from runtime.orchestrator.task_dag import TaskSpec


class ExtensionIntent(BaseModel):
    """Per-cycle delta brief. The `parent_project_id` ties the extension
    back to the originating workspace — the runtime uses it to load the
    locked PRD/RFC/stack as immutable context for the ExtenderAgent."""

    parent_project_id: str
    cycle: int = Field(ge=1)
    goal: str
    must_have_features: list[str] = Field(default_factory=list)
    explicit_non_goals: list[str] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)

    @field_validator("goal")
    @classmethod
    def _goal_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("ExtensionIntent.goal must be non-empty")
        return v


class DagDelta(BaseModel):
    """New tasks appended by one extend cycle. Validation:
    - Every `new_tasks[i].id` must start with `T-` (TaskSpec already enforces).
    - `cycle` is 1-indexed; first extend = cycle 1.
    - `starts_from_task_id` is informational — the actual ID continuity
      check lives in the Orchestrator validator (M3.1.1) and uses the
      parent `TaskDAG.max_task_id()` helper.
    """

    cycle: int = Field(ge=1)
    feature_title: str
    new_tasks: list[TaskSpec]
    starts_from_task_id: str

    @field_validator("starts_from_task_id")
    @classmethod
    def _starts_from_format(cls, v: str) -> str:
        if not v.startswith("T-"):
            raise ValueError(
                f"starts_from_task_id must start with 'T-' (got {v!r})"
            )
        return v

    @field_validator("feature_title")
    @classmethod
    def _title_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("DagDelta.feature_title must be non-empty")
        return v
