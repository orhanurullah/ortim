# SPDX-License-Identifier: FSL-1.1-Apache-2.0
# Copyright (c) 2026 ortim.dev
"""Code Reviewer agent — RFC compliance check on Worker output (soft veto).

Phase-0 rubric model (M1.5+): the verdict is a structured per-criterion
list, not free-form prose. Each acceptance criterion gets exactly one
`CriterionVerdict` (`pass | fail | partial | unverifiable`) plus evidence
and an optional code quote. `approved` and `reasons` are derived properties
preserved for callers that still read them.

`unverifiable` is a deliberate signal: the criterion itself is broken
(ambiguous wording, requires runtime data the reviewer doesn't have, etc.).
The runner escalates such tasks to AWAITING_HITL with a `criteria_design_failure`
audit entry — the Worker is not at fault, the criterion is.

Soft veto: a `fail` or `partial` rejection sends the task back to PENDING
with the attempt counter incremented; after `max_attempts` it escalates to
AWAITING_HITL. Hard vetoes (Security, Test Strategist) are emitted by their
own reviewer agents and short-circuit retry budget.
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


CriterionStatus = Literal["pass", "fail", "partial", "unverifiable"]

# Sub-categorization for `unverifiable`. Lets the runner, CLI, and audit log
# distinguish "the criterion is badly worded" from "tests were skipped".
# `None` is backward-compat: older LLM outputs that don't emit this field
# default to `criterion_design` (the safe, conservative bucket).
UnverifiableReason = Literal["criterion_design", "test_infrastructure"]


class CriterionVerdict(BaseModel):
    """One acceptance criterion's structured verdict.

    `criterion` MUST be quoted verbatim from the original `TaskSpec.acceptance_criteria`
    list — the rubric prompt forbids paraphrasing or inventing new criteria.
    `evidence` is a one-line justification (which file/line/test demonstrates
    the status). `code_quote` is an optional exact-string excerpt from the
    emitted code that supports the verdict.
    """

    criterion: str
    status: CriterionStatus
    evidence: str
    code_quote: str | None = None
    unverifiable_reason: UnverifiableReason | None = None
    """Set only when `status == "unverifiable"`. `criterion_design` means the
    criterion wording is ambiguous and no machine check can confirm it.
    `test_infrastructure` means the criterion requires test execution but
    tests were skipped or unavailable. Default `None` maps to
    `criterion_design` for backward compat."""


class ReviewVerdict(BaseModel):
    """Rubric verdict over a Worker output.

    The reviewer must emit one entry per acceptance criterion in
    `criteria_verdicts`, plus any independent L1-principle violations in
    `l1_violations` (DI, secrets, scope leak, etc.). `suggestions` carry
    non-blocking improvement notes.

    Backward-compat properties (`approved`, `reasons`) are derived so the
    runner, audit log, and CLI rendering keep working without schema
    sprawl.
    """

    criteria_verdicts: list[CriterionVerdict] = Field(default_factory=list)
    l1_violations: list[str] = Field(default_factory=list)
    suggestions: list[str] = Field(default_factory=list)

    @property
    def approved(self) -> bool:
        if self.l1_violations:
            return False
        if self.has_unverifiable:
            return False
        if not self.criteria_verdicts:
            return False
        return all(c.status == "pass" for c in self.criteria_verdicts)

    @property
    def has_unverifiable(self) -> bool:
        return any(c.status == "unverifiable" for c in self.criteria_verdicts)

    @property
    def unverifiable_by_design(self) -> list[CriterionVerdict]:
        """Criteria unverifiable due to ambiguous wording (not Worker's fault)."""
        return [
            c for c in self.criteria_verdicts
            if c.status == "unverifiable"
            and (c.unverifiable_reason or "criterion_design") == "criterion_design"
        ]

    @property
    def unverifiable_by_infra(self) -> list[CriterionVerdict]:
        """Criteria unverifiable because test infrastructure is unavailable."""
        return [
            c for c in self.criteria_verdicts
            if c.status == "unverifiable"
            and c.unverifiable_reason == "test_infrastructure"
        ]

    @property
    def reasons(self) -> list[str]:
        out: list[str] = []
        for c in self.criteria_verdicts:
            if c.status in ("fail", "partial"):
                quote = f" — code: `{c.code_quote}`" if c.code_quote else ""
                out.append(f"[{c.status}] {c.criterion}: {c.evidence}{quote}")
            elif c.status == "unverifiable":
                reason = c.unverifiable_reason or "criterion_design"
                if reason == "test_infrastructure":
                    tag = "unverifiable:test_infra"
                    note = "(test runner unavailable — set AI_FACTORY_TEST_CMD)"
                else:
                    tag = "unverifiable:design"
                    note = "(criterion design issue, not Worker fault)"
                out.append(
                    f"[{tag}] {c.criterion}: {c.evidence} {note}"
                )
        out.extend(f"[L1] {v}" for v in self.l1_violations)
        return out


class CodeReviewerAgent:
    MAX_RETRIES = 3

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
    ) -> ReviewVerdict:
        system_prompt = self.memory.load_agent_prompt("reviewer")
        principles = self.memory.load_l1_principles()
        full_system = (
            f"{system_prompt}\n\n## L1 Immutable Principles\n\n{principles}"
        )

        files_block = "\n\n".join(
            f"### {f.path} ({f.operation})\n```\n{f.content}\n```"
            for f in worker_output.files
        ) or "(no files emitted)"

        test_block = _render_test_block(test_result)

        criteria_block = "\n".join(
            f"  - {c}" for c in task.acceptance_criteria
        ) or "  (none)"

        expected_count = len(task.acceptance_criteria)
        base_user_prompt = (
            f"Project ID: {project_id}\n\n"
            f"Task:\n{task.model_dump_json(indent=2)}\n\n"
            f"Acceptance criteria (verbatim, one verdict per item, "
            f"EXACTLY {expected_count} entries required):\n{criteria_block}\n\n"
            f"RFC section ({task.rfc_section}):\n```\n{rfc_text}\n```\n\n"
            f"Worker summary: {worker_output.summary}\n\n"
            f"Test outcome:\n{test_block}\n\n"
            f"Files emitted:\n\n{files_block}\n\n"
            "Apply the rubric. Emit one CriterionVerdict per acceptance "
            "criterion (verbatim text, status, evidence, optional code_quote). "
            f"You MUST emit EXACTLY {expected_count} entries in `criteria_verdicts` "
            "— one per acceptance criterion above, in the same order. Do NOT "
            "introduce criteria that were not in the list. Mark as "
            "`unverifiable` if a criterion cannot be checked from the inputs "
            "given (e.g. ambiguous wording, requires runtime data not present).\n\n"
            "Emit ReviewVerdict JSON. Output ONLY the JSON object."
        )

        # Phase 0+ deterministic length-check loop. The LLM has been observed
        # (todo-greenfield-4 T-005) to emit fewer verdicts than the criterion
        # list — silently dropping criteria the rubric prompt explicitly
        # forbids. We catch that here and retry with a structured correction
        # message, modeled on Orchestrator's retry-on-validation pattern.
        previous_error: str | None = None
        for attempt in range(1, self.MAX_RETRIES + 1):
            user_prompt = base_user_prompt
            if previous_error:
                user_prompt = (
                    f"Previous attempt was rejected by the runtime validator:\n"
                    f"  {previous_error}\n\n"
                    "Fix the count and re-emit the corrected JSON. Output ONLY JSON.\n\n"
                    + base_user_prompt
                )

            response = self.llm.call(
                system=full_system,
                user=user_prompt,
                temperature=0.0,
                max_tokens=2000,
            )
            cleaned = _strip_code_fences(response.text)

            try:
                verdict = ReviewVerdict.model_validate_json(cleaned)
            except ValueError as e:
                previous_error = f"invalid JSON / schema: {str(e)[:200]}"
                self.audit.log(
                    "reviewer_validation_failed",
                    project_id=project_id,
                    task_id=task.id,
                    attempt=attempt,
                    error=previous_error,
                    **response.audit_fields(),
                )
                continue

            actual_count = len(verdict.criteria_verdicts)
            if actual_count != expected_count:
                previous_error = (
                    f"emitted {actual_count} criterion verdicts but the task "
                    f"has EXACTLY {expected_count} acceptance criteria. "
                    "Every criterion needs its own verdict — none can be omitted."
                )
                self.audit.log(
                    "reviewer_validation_failed",
                    project_id=project_id,
                    task_id=task.id,
                    attempt=attempt,
                    error=previous_error,
                    expected_count=expected_count,
                    actual_count=actual_count,
                    **response.audit_fields(),
                )
                continue

            self.audit.log(
                "reviewer_verdict",
                project_id=project_id,
                task_id=task.id,
                attempt=attempt,
                approved=verdict.approved,
                criteria_verdicts=[c.model_dump() for c in verdict.criteria_verdicts],
                l1_violations=verdict.l1_violations,
                has_unverifiable=verdict.has_unverifiable,
                reasons=verdict.reasons,
                suggestions=verdict.suggestions,
                tests_passed=test_result.passed if test_result else None,
                tests_skipped=test_result.skipped_reason if test_result else None,
                **response.audit_fields(),
            )
            return verdict

        raise RuntimeError(
            f"CodeReviewer failed to produce a valid rubric after "
            f"{self.MAX_RETRIES} attempts. Last error: {previous_error}"
        )


def _render_test_block(test_result: TestResult | None) -> str:
    if test_result is None:
        return "(test runner did not run)"
    if test_result.skipped_reason:
        return f"SKIPPED — {test_result.skipped_reason}"
    if test_result.passed:
        return "PASSED"
    return (
        f"FAILED (exit {test_result.exit_code})\n"
        f"--- stdout tail ---\n{test_result.stdout_tail or '(empty)'}\n"
        f"--- stderr tail ---\n{test_result.stderr_tail or '(empty)'}"
    )
