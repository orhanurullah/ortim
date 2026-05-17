# SPDX-License-Identifier: FSL-1.1-Apache-2.0
# Copyright (c) 2026 ortim.dev
"""Runner — execute a mutation suite through a Reviewer-like callable.

The runner is decoupled from `CodeReviewerAgent` via the `ReviewerLike`
Protocol so tests can pass a synthetic fake without instantiating an
LLM client. In production, `client_for("reviewer")` + the real agent
go in.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from ortim.executor.reviewer import ReviewVerdict
from ortim.executor.test_runner import TestResult
from ortim.executor.worker import FileChange, WorkerOutput
from ortim.mutation.case import CatchResult, CatchRateReport, MutationCase
from ortim.mutation.scoring import score_case
from ortim.orchestrator import TaskSpec
from ortim.skills import Skill


class ReviewerLike(Protocol):
    """Minimal interface the runner depends on. Satisfied by
    `CodeReviewerAgent` and any FakeReviewer used in tests."""

    def review(
        self,
        task: TaskSpec,
        worker_output: WorkerOutput,
        rfc_text: str,
        project_id: str,
        test_result: TestResult | None = ...,
        active_skills: list[Skill] | None = ...,
    ) -> ReviewVerdict: ...


def _summarize_verdict(verdict: ReviewVerdict) -> str:
    """Short one-line summary of a verdict for the catch result row."""
    statuses: dict[str, int] = {}
    for cv in verdict.criteria_verdicts:
        statuses[cv.status] = statuses.get(cv.status, 0) + 1
    parts = [f"{k}={v}" for k, v in sorted(statuses.items())]
    if verdict.l1_violations:
        parts.append(f"L1={len(verdict.l1_violations)}")
    parts.append(f"approved={verdict.approved}")
    return " ".join(parts)


def _build_task_spec(case: MutationCase) -> TaskSpec:
    return TaskSpec(
        id="T-mut",
        title=case.task_title,
        description=case.task_description,
        module_scope=case.module_scope,
        acceptance_criteria=list(case.acceptance_criteria),
        rfc_section=case.rfc_section,
        estimated_tokens=2000,
    )


def _build_worker_output(case: MutationCase) -> WorkerOutput:
    return WorkerOutput(
        task_id="T-mut",
        summary=f"Mutation case: {case.bug_class}/{case.name}",
        files=[
            FileChange(
                path=case.file_path,
                content=case.mutated_code,
                operation="create",
            )
        ],
    )


def run_mutation_suite(
    cases: Sequence[MutationCase],
    reviewer: ReviewerLike,
    project_id: str = "mutation-test",
) -> CatchRateReport:
    """Run every case through the reviewer, score it, aggregate the
    catch rate per bug class.

    The runner never raises on individual case failures — a Reviewer
    that crashes on one case is itself a finding (the verdict object
    can't be obtained, so neither catch flag is set; the case is
    recorded with `error` populated).
    """
    results: list[CatchResult] = []
    per_class_counts: dict[str, list[int]] = {}
    for case in cases:
        slot = per_class_counts.setdefault(case.bug_class, [0, 0, 0, 0])
        slot[3] += 1  # total
        try:
            verdict = reviewer.review(
                task=_build_task_spec(case),
                worker_output=_build_worker_output(case),
                rfc_text=case.rfc_excerpt,
                project_id=project_id,
            )
        except Exception as exc:  # noqa: BLE001 — runner intentionally never raises
            slot[2] += 1  # errors
            results.append(
                CatchResult(
                    case_name=case.name,
                    bug_class=case.bug_class,
                    caught_loose=False,
                    caught_strict=False,
                    verdict_summary="",
                    error=f"{type(exc).__name__}: {exc}",
                )
            )
            continue

        loose, strict = score_case(case, verdict)
        if loose:
            slot[0] += 1
        if strict:
            slot[1] += 1
        results.append(
            CatchResult(
                case_name=case.name,
                bug_class=case.bug_class,
                caught_loose=loose,
                caught_strict=strict,
                verdict_summary=_summarize_verdict(verdict),
            )
        )

    total_loose = sum(slot[0] for slot in per_class_counts.values())
    total_strict = sum(slot[1] for slot in per_class_counts.values())
    total_errors = sum(slot[2] for slot in per_class_counts.values())
    return CatchRateReport(
        total=len(results),
        caught_loose=total_loose,
        caught_strict=total_strict,
        errors=total_errors,
        per_class={
            cls: (slot[0], slot[1], slot[2], slot[3])
            for cls, slot in per_class_counts.items()
        },
        cases=results,
    )
