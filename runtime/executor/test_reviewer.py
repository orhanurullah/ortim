# SPDX-License-Identifier: FSL-1.1-Apache-2.0
# Copyright (c) 2026 ortim.dev
"""Test Strategist Reviewer — hard veto on AC×test coverage gaps and test failures.

Mirror of SecurityReviewer's hard-veto contract: reject → task escalates to
AWAITING_HITL without retry. Intent: a Worker that can't write tests for the
ACs it was given won't fix that by re-rolling — a human needs to look.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from runtime.audit import AuditLogger
from runtime.babel.intent import _strip_code_fences
from runtime.executor.test_runner import TestResult
from runtime.executor.worker import WorkerOutput
from runtime.llm import LLMClient
from runtime.memory import MemoryLoader
from runtime.orchestrator import TaskSpec


Severity = Literal["high", "medium", "low"]


class ACCoverageEntry(BaseModel):
    ac: str
    test: str | None = None


class TestVerdict(BaseModel):
    approved: bool
    severity: Severity | None = None
    reasons: list[str] = Field(default_factory=list)
    suggestions: list[str] = Field(default_factory=list)
    ac_coverage: list[ACCoverageEntry] = Field(default_factory=list)
    reviewer: str = "test"


class TestReviewerAgent:
    name = "test"
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
        test_result: TestResult | None = None,
    ) -> TestVerdict:
        system_prompt = self.memory.load_agent_prompt("test_reviewer")
        full_system = system_prompt

        files_block = "\n\n".join(
            f"### {f.path} ({f.operation})\n```\n{f.content}\n```"
            for f in worker_output.files
        ) or "(no files emitted)"

        if test_result is None:
            test_block = "(test runner did not run)"
        elif test_result.skipped_reason:
            test_block = f"SKIPPED — {test_result.skipped_reason}"
        elif test_result.passed:
            test_block = "PASSED"
        else:
            test_block = (
                f"FAILED (exit {test_result.exit_code}); "
                f"stderr tail: {test_result.stderr_tail[-400:]}"
            )

        user_prompt = (
            f"Project ID: {project_id}\n\n"
            f"Task:\n{task.model_dump_json(indent=2)}\n\n"
            f"RFC section ({task.rfc_section}):\n```\n{rfc_text}\n```\n\n"
            f"Worker summary: {worker_output.summary}\n\n"
            f"Test runner outcome:\n{test_block}\n\n"
            f"Files emitted:\n\n{files_block}\n\n"
            "Apply the AC×test rubric. Output ONLY a TestVerdict JSON."
        )

        response = self.llm.call(
            system=full_system,
            user=user_prompt,
            temperature=0.0,
            max_tokens=2000,
        )
        cleaned = _strip_code_fences(response.text)
        verdict = TestVerdict.model_validate_json(cleaned)

        self.audit.log(
            "test_reviewer_verdict",
            project_id=project_id,
            task_id=task.id,
            approved=verdict.approved,
            severity=verdict.severity,
            reasons=verdict.reasons,
            ac_coverage_count=len(verdict.ac_coverage),
            ac_coverage_missing=sum(
                1 for entry in verdict.ac_coverage if entry.test is None
            ),
            **response.audit_fields(),
        )
        return verdict
