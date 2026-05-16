# SPDX-License-Identifier: FSL-1.1-Apache-2.0
# Copyright (c) 2026 ortim.dev
"""Mutation runner — aggregates per-case scoring into a CatchRateReport.

Uses a FakeReviewer that ducks the `ReviewerLike` Protocol — no LLM
call, no Anthropic SDK, just predictable verdicts so the aggregation
math is the only thing under test."""

from __future__ import annotations

import sys
from collections.abc import Callable
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from runtime.executor.reviewer import (  # noqa: E402
    CriterionVerdict,
    ReviewVerdict,
)
from runtime.executor.worker import WorkerOutput  # noqa: E402
from runtime.mutation import DEFAULT_CASES, run_mutation_suite  # noqa: E402
from runtime.mutation.case import MutationCase  # noqa: E402
from runtime.orchestrator import TaskSpec  # noqa: E402


class _FakeReviewer:
    """Reviewer-shape stub. Receives `verdict_for` — a function from
    TaskSpec.id → ReviewVerdict — so each test can decide per-case
    behavior. Tracks call count for assertions about runner invocation."""

    def __init__(
        self,
        verdict_for: Callable[[TaskSpec], ReviewVerdict],
        raise_on: set[str] | None = None,
    ) -> None:
        self.verdict_for = verdict_for
        self.raise_on = raise_on or set()
        self.calls: list[str] = []

    def review(
        self,
        task: TaskSpec,
        worker_output: WorkerOutput,
        rfc_text: str,
        project_id: str,
        test_result: object | None = None,
        active_skills: object | None = None,
    ) -> ReviewVerdict:
        self.calls.append(worker_output.summary)
        if any(token in worker_output.summary for token in self.raise_on):
            raise RuntimeError(f"fake reviewer crash for {worker_output.summary!r}")
        return self.verdict_for(task)


def _approve(_task: TaskSpec) -> ReviewVerdict:
    return ReviewVerdict(
        criteria_verdicts=[
            CriterionVerdict(criterion=c, status="pass", evidence="ok")
            for c in ["c1", "c2", "c3"]
        ],
    )


def _reject_with_keywords(keywords_for_each_case: dict[str, str]) -> Callable[[TaskSpec], ReviewVerdict]:
    """Return a verdict_for that rejects with a `fail` verdict whose
    evidence carries the supplied keyword (lookup by task title — runner
    uses the case's task_title)."""

    def fn(task: TaskSpec) -> ReviewVerdict:
        evidence = keywords_for_each_case.get(task.title, "generic failure reason")
        return ReviewVerdict(
            criteria_verdicts=[
                CriterionVerdict(criterion="c1", status="pass", evidence="ok"),
                CriterionVerdict(criterion="c2", status="fail", evidence=evidence),
            ],
        )

    return fn


# ---------------------------------------------------------------------------
# Runner — happy path
# ---------------------------------------------------------------------------


def test_runner_calls_review_once_per_case() -> None:
    fake = _FakeReviewer(verdict_for=_approve)
    report = run_mutation_suite(DEFAULT_CASES, fake)
    assert len(fake.calls) == len(DEFAULT_CASES)
    assert report.total == len(DEFAULT_CASES)


def test_runner_aggregates_all_approved_as_zero_caught() -> None:
    """When the (fake) Reviewer approves everything, the catch rate is
    0% — every bug slipped through. This is the worst-case data point
    for the live run."""
    fake = _FakeReviewer(verdict_for=_approve)
    report = run_mutation_suite(DEFAULT_CASES, fake)
    assert report.caught_loose == 0
    assert report.caught_strict == 0
    assert report.loose_rate == 0.0
    assert report.strict_rate == 0.0


def test_runner_aggregates_strict_catch_when_evidence_matches_keyword() -> None:
    """Build a verdict per case whose `fail` evidence contains a known
    bug keyword for that case. Strict rate should be 100%."""
    evidence_by_title = {
        c.task_title: c.bug_keywords[0]  # first keyword each
        for c in DEFAULT_CASES
    }
    fake = _FakeReviewer(verdict_for=_reject_with_keywords(evidence_by_title))
    report = run_mutation_suite(DEFAULT_CASES, fake)
    assert report.caught_loose == len(DEFAULT_CASES)
    assert report.caught_strict == len(DEFAULT_CASES)
    assert report.loose_rate == 1.0
    assert report.strict_rate == 1.0


def test_runner_distinguishes_loose_only_from_strict_catch() -> None:
    """A Reviewer that rejects every case but with generic, non-pattern
    evidence — loose catch only. Strict rate < loose rate is the
    diagnostic-quality signal."""
    fake = _FakeReviewer(
        verdict_for=_reject_with_keywords({})  # no keyword matches
    )
    report = run_mutation_suite(DEFAULT_CASES, fake)
    assert report.caught_loose == len(DEFAULT_CASES)
    assert report.caught_strict == 0


# ---------------------------------------------------------------------------
# Per-bug-class breakdown
# ---------------------------------------------------------------------------


def test_runner_emits_per_class_rows_keyed_by_bug_class() -> None:
    fake = _FakeReviewer(verdict_for=_approve)
    report = run_mutation_suite(DEFAULT_CASES, fake)
    seen_classes = {c.bug_class for c in DEFAULT_CASES}
    assert set(report.per_class.keys()) == seen_classes
    for cls, (loose, strict, errors, total) in report.per_class.items():
        assert total == sum(1 for c in DEFAULT_CASES if c.bug_class == cls)
        assert loose == 0  # _approve never rejects
        assert strict == 0
        assert errors == 0


# ---------------------------------------------------------------------------
# Error handling — reviewer crash on one case must not poison the rest
# ---------------------------------------------------------------------------


def test_runner_records_error_when_reviewer_raises() -> None:
    crashing_case_summary = (
        f"Mutation case: {DEFAULT_CASES[0].bug_class}/{DEFAULT_CASES[0].name}"
    )
    fake = _FakeReviewer(
        verdict_for=_approve,
        raise_on={DEFAULT_CASES[0].name},
    )
    report = run_mutation_suite(DEFAULT_CASES, fake)
    assert report.errors == 1
    assert report.total == len(DEFAULT_CASES)
    error_results = [r for r in report.cases if r.error is not None]
    assert len(error_results) == 1
    assert error_results[0].case_name == DEFAULT_CASES[0].name
    assert "RuntimeError" in (error_results[0].error or "")
    # Non-crashing cases still ran.
    assert len(fake.calls) == len(DEFAULT_CASES)
    assert crashing_case_summary in fake.calls


def test_runner_error_does_not_count_as_catch() -> None:
    fake = _FakeReviewer(
        verdict_for=_approve,
        raise_on={DEFAULT_CASES[0].name},
    )
    report = run_mutation_suite(DEFAULT_CASES, fake)
    crashed = next(r for r in report.cases if r.error is not None)
    assert crashed.caught_loose is False
    assert crashed.caught_strict is False


# ---------------------------------------------------------------------------
# Report rendering
# ---------------------------------------------------------------------------


def test_report_render_contains_rate_and_per_class_rows() -> None:
    fake = _FakeReviewer(verdict_for=_approve)
    report = run_mutation_suite(DEFAULT_CASES, fake)
    text = report.render()
    assert "Mutation report" in text
    assert "Caught (loose)" in text
    assert "Caught (strict)" in text
    assert "Per bug class" in text
    for case in DEFAULT_CASES:
        assert case.bug_class in text


def test_report_render_handles_empty_run() -> None:
    fake = _FakeReviewer(verdict_for=_approve)
    report = run_mutation_suite([], fake)
    assert "no cases" in report.render().lower()


# ---------------------------------------------------------------------------
# Single-case smoke — make sure the runner threads file_path through
# ---------------------------------------------------------------------------


def test_runner_passes_mutated_code_in_worker_output() -> None:
    """End-to-end shape check: the runner constructs a WorkerOutput
    whose first FileChange carries the case's mutated_code and path.
    This is the contract that the live Reviewer relies on — break it
    and every case turns into a scope/extension violation."""
    captured: list[WorkerOutput] = []

    class _CapturingReviewer:
        def review(
            self,
            task: TaskSpec,
            worker_output: WorkerOutput,
            rfc_text: str,
            project_id: str,
            test_result: object | None = None,
            active_skills: object | None = None,
        ) -> ReviewVerdict:
            captured.append(worker_output)
            return _approve(task)

    one_case: list[MutationCase] = [DEFAULT_CASES[0]]
    run_mutation_suite(one_case, _CapturingReviewer())
    assert len(captured) == 1
    output = captured[0]
    assert output.files[0].path == DEFAULT_CASES[0].file_path
    assert output.files[0].content == DEFAULT_CASES[0].mutated_code
