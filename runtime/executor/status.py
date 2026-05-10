# SPDX-License-Identifier: FSL-1.1-Apache-2.0
# Copyright (c) 2026 ortim.dev
"""Per-task run status sidecar (`workspaces/<id>/task_status.json`).

DAG.json is immutable once produced by the Orchestrator agent. Per-task
runtime state (attempts, last verdict, FAILED vs AWAITING_HITL) lives here
so it can be updated independently of the DAG.
"""

from __future__ import annotations

from enum import Enum
from pathlib import Path

from pydantic import BaseModel, Field


class TaskStatus(str, Enum):
    PENDING = "PENDING"
    IN_PROGRESS = "IN_PROGRESS"
    DONE = "DONE"
    FAILED = "FAILED"
    AWAITING_HITL = "AWAITING_HITL"


class TaskRunRecord(BaseModel):
    task_id: str
    status: TaskStatus = TaskStatus.PENDING
    attempts: int = 0
    last_review_approved: bool | None = None
    last_review_reasons: list[str] = Field(default_factory=list)
    last_review_suggestions: list[str] = Field(default_factory=list)
    last_error: str | None = None


class TaskStatusFile(BaseModel):
    project_id: str
    records: dict[str, TaskRunRecord] = Field(default_factory=dict)

    @classmethod
    def load_or_init(cls, workspace: Path, project_id: str) -> "TaskStatusFile":
        path = workspace / "task_status.json"
        if path.exists():
            return cls.model_validate_json(path.read_text(encoding="utf-8"))
        return cls(project_id=project_id)

    def save(self, workspace: Path) -> None:
        (workspace / "task_status.json").write_text(
            self.model_dump_json(indent=2), encoding="utf-8"
        )

    def get_or_create(self, task_id: str) -> TaskRunRecord:
        if task_id not in self.records:
            self.records[task_id] = TaskRunRecord(task_id=task_id)
        return self.records[task_id]
