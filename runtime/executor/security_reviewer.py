# SPDX-License-Identifier: FSL-1.1-Apache-2.0
# Copyright (c) 2026 ortim.dev
"""Security Reviewer agent — hard veto on injection, secrets, broken auth, etc.

Hard veto means: a reject from this reviewer escalates the task to
AWAITING_HITL immediately, regardless of `max_attempts`. The intent is that
security defects are not the kind of thing the same Worker should retry — a
human needs to see them.

Severity → action:
  - high   → reject (hard veto)
  - medium → reject (hard veto)
  - low    → approved=true, item lives in `suggestions`
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from runtime.audit import AuditLogger
from runtime.babel.intent import _strip_code_fences
from runtime.executor.worker import WorkerOutput
from runtime.llm import LLMClient
from runtime.memory import MemoryLoader
from runtime.orchestrator import TaskSpec


Severity = Literal["high", "medium", "low"]


class SecurityVerdict(BaseModel):
    approved: bool
    severity: Severity | None = None
    reasons: list[str] = Field(default_factory=list)
    suggestions: list[str] = Field(default_factory=list)
    reviewer: str = "security"


class SecurityReviewerAgent:
    """Hard-veto reviewer focused on injection, secrets, authn/authz, crypto."""

    name = "security"
    is_hard_veto = True

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
    ) -> SecurityVerdict:
        system_prompt = self.memory.load_agent_prompt("security_reviewer")
        principles = self.memory.load_l1_principles()
        full_system = (
            f"{system_prompt}\n\n## L1 Immutable Principles\n\n{principles}"
        )

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
            "Apply the threat catalogue. Output ONLY a SecurityVerdict JSON."
        )

        response = self.llm.call(
            system=full_system,
            user=user_prompt,
            temperature=0.0,
            max_tokens=2000,
        )
        cleaned = _strip_code_fences(response.text)
        verdict = SecurityVerdict.model_validate_json(cleaned)

        self.audit.log(
            "security_reviewer_verdict",
            project_id=project_id,
            task_id=task.id,
            approved=verdict.approved,
            severity=verdict.severity,
            reasons=verdict.reasons,
            **response.audit_fields(),
        )
        return verdict
