# SPDX-License-Identifier: FSL-1.1-Apache-2.0
# Copyright (c) 2026 ortim.dev
"""Performance Reviewer — soft veto. Findings annotate the task; never block.

Intent: catch known anti-patterns (N+1, missing pagination, sync I/O on hot
paths, bundle bloat) without pretending to be a benchmark. Output is recorded
as a comment on the task and surfaced to the next iteration's reviewer chain.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from ortim.audit import AuditLogger
from ortim.babel.intent import _strip_code_fences
from ortim.executor.worker import WorkerOutput
from ortim.llm import LLMClient
from ortim.memory import MemoryLoader
from ortim.orchestrator import TaskSpec


Severity = Literal["high", "medium", "low"]
EstimatedCost = Literal["low", "medium", "high"]


class PerfVerdict(BaseModel):
    approved: bool = True
    severity: Severity | None = None
    reasons: list[str] = Field(default_factory=list)
    suggestions: list[str] = Field(default_factory=list)
    estimated_cost: EstimatedCost | None = None
    reviewer: str = "perf"


class PerfReviewerAgent:
    name = "perf"
    is_hard_veto = False  # soft veto — informational only

    def __init__(
        self,
        llm: LLMClient,
        memory: MemoryLoader,
        audit: AuditLogger,
    ) -> None:
        self.llm = llm
        self.memory = memory
        self.audit = audit

    def review(
        self,
        task: TaskSpec,
        worker_output: WorkerOutput,
        rfc_text: str,
        project_id: str,
    ) -> PerfVerdict:
        system_prompt = self.memory.load_agent_prompt("perf_reviewer")
        full_system = system_prompt

        files_block = "\n\n".join(
            f"### {f.path} ({f.operation})\n```\n{f.content}\n```"
            for f in worker_output.files
        ) or "(no files emitted)"

        user_prompt = (
            f"Project ID: {project_id}\n\n"
            f"Task:\n{task.model_dump_json(indent=2)}\n\n"
            f"RFC section ({task.rfc_section}):\n```\n{rfc_text}\n```\n\n"
            f"Worker summary: {worker_output.summary}\n\n"
            f"Files emitted:\n\n{files_block}\n\n"
            "Apply the perf anti-pattern catalogue. Output ONLY a PerfVerdict JSON."
        )

        response = self.llm.call(
            system=full_system,
            user=user_prompt,
            temperature=0.0,
            max_tokens=1500,
        )
        cleaned = _strip_code_fences(response.text)
        verdict = PerfVerdict.model_validate_json(cleaned)

        self.audit.log(
            "perf_reviewer_verdict",
            project_id=project_id,
            task_id=task.id,
            approved=verdict.approved,
            severity=verdict.severity,
            reasons=verdict.reasons,
            estimated_cost=verdict.estimated_cost,
            **response.audit_fields(),
        )
        return verdict
