# SPDX-License-Identifier: FSL-1.1-Apache-2.0
# Copyright (c) 2026 ortim.dev
"""Single-task execution pipeline.

  Worker → write files → run tests → CodeReviewer (soft veto)
                                   → SecurityReviewer (hard veto, optional)
                                   → TestReviewer (hard veto, optional)
                                   → PerfReviewer (soft veto, optional)
       → if hard veto: branch abandon, task → AWAITING_HITL (no retry)
       → if only soft veto: branch abandon, task → PENDING (retry up to max)
       → if all approved: commit → merge (sequential) or signal merge (worktree)

Two git modes:

  - **sequential** (`use_worktree=False`): the runner checks out `task/<id>` on
    the primary repo and operates there. One task at a time.
  - **parallel** (`use_worktree=True`): the runner adds a worktree at
    `<workspace>/.worktrees/<task_id>` on a fresh `task/<id>` branch. Worker
    writes, tests run, and the commit happens in the worktree. The caller is
    responsible for serializing the merge back to main and removing the
    worktree (only `run-all --parallel` does this today).

Tests are opt-in via `AI_FACTORY_TEST_CMD`. Hard-veto reviewers are opt-in
via `ReviewerChain` — when `None`, the legacy single-CodeReviewer behavior
is preserved (so existing smoke tests keep working).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from runtime.audit import AuditLogger
from runtime.codebase import CodebaseSummary, read_related
from runtime.executor.git_ops import (
    GitOperationFailed,
    abandon_task_branch,
    add_worktree,
    commit_changes,
    ensure_repo,
    git_enabled,
    merge_task_to_main,
    remove_worktree,
    start_task_branch,
)
from runtime.executor.perf_reviewer import PerfReviewerAgent, PerfVerdict
from runtime.executor.reviewer import CodeReviewerAgent, ReviewVerdict
from runtime.executor.sandbox import normalize_relative, resolve_in_workspace
from runtime.executor.security_reviewer import SecurityReviewerAgent, SecurityVerdict
from runtime.executor.status import TaskStatus, TaskStatusFile
from runtime.executor.test_reviewer import TestReviewerAgent, TestVerdict
from runtime.executor.test_runner import TestResult, run_tests
from runtime.executor.worker import WorkerAgent, WorkerOutOfScope, WorkerOutput
from runtime.hooks import HookResult, run_hook
from runtime.llm import LLMClient
from runtime.memory import MemoryLoader
from runtime.orchestrator import TaskSpec


@dataclass
class ReviewerChain:
    """Optional hard-veto reviewers layered on top of CodeReviewer.

    Each is independently optional — pass `None` for any field to skip that
    reviewer. If all three are `None`, the runner behaves exactly like the
    pre-6b pipeline: only CodeReviewer (soft veto) runs.
    """

    security: SecurityReviewerAgent | None = None
    test: TestReviewerAgent | None = None
    perf: PerfReviewerAgent | None = None


@dataclass
class ExecutionResult:
    task_id: str
    status: TaskStatus
    worker_output: WorkerOutput | None = None
    verdict: ReviewVerdict | None = None
    test_result: TestResult | None = None
    branch: str | None = None
    commit_sha: str | None = None
    written_paths: list[str] | None = None
    task_workspace: Path | None = None
    needs_merge: bool = False
    error: str | None = None
    verdicts: list[Any] = field(default_factory=list)
    blocked_by: str | None = None

    @property
    def approved(self) -> bool:
        return self.status == TaskStatus.DONE


def execute_task(
    task: TaskSpec,
    rfc_text: str,
    project_id: str,
    workspace: Path,
    status_file: TaskStatusFile,
    llm: LLMClient,
    memory: MemoryLoader,
    audit: AuditLogger,
    max_attempts: int = 3,
    use_worktree: bool = False,
    reviewer_llm: LLMClient | None = None,
    reviewer_chain: ReviewerChain | None = None,
    codebase_summary: CodebaseSummary | None = None,
    app_class: str = "web",
) -> ExecutionResult:
    """Run one task end-to-end. Mutates `status_file` in memory; the caller saves it.

    With `use_worktree=True` the caller MUST handle merge/cleanup of approved
    tasks (see `ExecutionResult.needs_merge`). Rejected tasks clean up their
    own worktree before returning.

    `reviewer_chain` adds Security/Test/Perf reviewers on top of CodeReviewer.
    Hard veto from Security/Test → task → AWAITING_HITL immediately
    (no retry — security/test gaps don't get fixed by re-rolling the same Worker).
    Perf reviewer is informational only; its findings annotate the verdict
    but never block.
    """
    record = status_file.get_or_create(task.id)

    if record.status == TaskStatus.DONE:
        return ExecutionResult(task.id, TaskStatus.DONE, error="already DONE")
    if record.status == TaskStatus.AWAITING_HITL:
        return ExecutionResult(
            task.id, TaskStatus.AWAITING_HITL, error="awaiting human approval"
        )

    record.status = TaskStatus.IN_PROGRESS
    record.attempts += 1

    use_git = git_enabled(workspace)
    if use_worktree and not use_git:
        record.status = TaskStatus.FAILED
        record.last_error = "use_worktree=True requires git enabled"
        return ExecutionResult(
            task.id, TaskStatus.FAILED, error=record.last_error
        )

    branch: str | None = None
    task_workspace = workspace
    if use_git:
        ensure_repo(workspace)
        if use_worktree:
            task_workspace = add_worktree(workspace, task.id)
            branch = f"task/{task.id}"
        else:
            branch = start_task_branch(workspace, task.id)

    prior_reasons = record.last_review_reasons if record.attempts > 1 else None

    related_files: dict[str, str] | None = None
    if codebase_summary is not None:
        # Brownfield path: triage real files into the Worker prompt so it can
        # modify existing modules instead of regenerating from scratch.
        try:
            related_files = read_related(
                summary=codebase_summary,
                root=task_workspace,
                module_scope=task.module_scope,
                task_description=f"{task.title}\n{task.description}",
            )
        except Exception as e:  # never fail a task because triage failed
            audit.log(
                "executor_read_related_failed",
                project_id=project_id,
                task_id=task.id,
                error=str(e)[:300],
            )
            related_files = None

    worker = WorkerAgent(llm, memory, audit)
    try:
        output = worker.execute(
            task,
            rfc_text,
            project_id,
            prior_reasons,
            related_files=related_files,
            app_class=app_class,
        )
    except (WorkerOutOfScope, ValueError) as e:
        err_text = str(e)[:300]
        record.last_error = err_text
        # Phase 0 / item 15: feed the sandbox or parse failure back into
        # `prior_reasons` so the next Worker call sees concrete feedback.
        # Without this, the auto-retry loop (item 7) reruns the Worker with
        # the same prompt and `prior_reasons=None`, producing the identical
        # violation verbatim — observed in `todo-greenfield-3` T-002 across
        # three attempts. The `[sandbox]` tag lets the Worker distinguish
        # this from Reviewer rubric reasons.
        record.last_review_reasons = [
            f"[sandbox] Previous attempt failed before reaching review: "
            f"{err_text}. Only emit files under "
            f"module_scope='{task.module_scope}/'. To consume types or "
            f"symbols from other modules, IMPORT them via the language's "
            f"import mechanism (e.g. Go `import \"<pkg>\"`, TypeScript "
            f"`import { ... } from \"<path>\"`); do NOT re-create files "
            f"that already exist in other modules."
        ]
        if use_git and branch:
            _try_cleanup_branch(workspace, task.id, use_worktree)
        record.status = (
            TaskStatus.AWAITING_HITL
            if record.attempts >= max_attempts
            else TaskStatus.PENDING
        )
        return ExecutionResult(
            task.id, record.status, branch=branch, error=record.last_error
        )

    written: list[str] = []
    for f in output.files:
        rel = normalize_relative(f.path)
        abs_path = resolve_in_workspace(task_workspace, rel)
        abs_path.parent.mkdir(parents=True, exist_ok=True)
        abs_path.write_text(f.content, encoding="utf-8")
        written.append(str(rel))

    test_result: TestResult | None = None
    if output.files:
        test_result = run_tests(task_workspace)
        audit.log(
            "executor_tests",
            project_id=project_id,
            task_id=task.id,
            passed=test_result.passed,
            skipped_reason=test_result.skipped_reason,
            exit_code=test_result.exit_code,
            worktree=use_worktree,
        )

    code_reviewer = CodeReviewerAgent(reviewer_llm or llm, memory, audit)
    verdict = code_reviewer.review(task, output, rfc_text, project_id, test_result)

    record.last_review_approved = verdict.approved
    record.last_review_reasons = list(verdict.reasons)
    record.last_review_suggestions = list(verdict.suggestions)
    record.last_error = None

    test_failed = (
        test_result is not None
        and not test_result.passed
        and not test_result.skipped
    )
    code_ok = verdict.approved and not test_failed

    all_verdicts: list[Any] = [verdict]
    blocked_by: str | None = None

    # Hard-veto reviewers run only if the code-level review and tests are clean.
    # No point running SecurityReviewer over a Worker output that already
    # failed its own tests — that's wasted budget.
    if code_ok and reviewer_chain is not None:
        if reviewer_chain.security is not None:
            sec_verdict = reviewer_chain.security.review(
                task, output, rfc_text, project_id
            )
            all_verdicts.append(sec_verdict)
            if _is_hard_reject(sec_verdict):
                blocked_by = sec_verdict.reviewer
                _merge_reviewer_reasons(record, sec_verdict)

        if blocked_by is None and reviewer_chain.test is not None:
            test_verdict = reviewer_chain.test.review(
                task, output, rfc_text, project_id, test_result
            )
            all_verdicts.append(test_verdict)
            if _is_hard_reject(test_verdict):
                blocked_by = test_verdict.reviewer
                _merge_reviewer_reasons(record, test_verdict)

        # Perf is soft veto: never blocks, always annotates.
        if reviewer_chain.perf is not None:
            perf_verdict = reviewer_chain.perf.review(
                task, output, rfc_text, project_id
            )
            all_verdicts.append(perf_verdict)
            if perf_verdict.reasons:
                record.last_review_suggestions.extend(
                    f"[perf] {r}" for r in perf_verdict.reasons
                )
            if perf_verdict.suggestions:
                record.last_review_suggestions.extend(
                    f"[perf] {s}" for s in perf_verdict.suggestions
                )

    approved = code_ok and blocked_by is None

    if approved:
        # pre_commit hook (lint, format check) — last gate before we commit.
        # A failing hook is a soft veto: task → PENDING with retry budget,
        # because lint/format fixes are exactly what a Worker can iterate on.
        hook_result = run_hook(
            "pre_commit",
            task_workspace,
            audit,
            project_id=project_id,
            task_id=task.id,
        )
        if not hook_result.passed:
            if use_git and branch:
                _try_cleanup_branch(workspace, task.id, use_worktree)
            record.last_review_reasons.append(
                f"[pre_commit] hook failed (exit {hook_result.exit_code}); "
                f"stderr tail: {hook_result.stderr_tail[-300:]}"
            )
            record.status = (
                TaskStatus.AWAITING_HITL
                if record.attempts >= max_attempts
                else TaskStatus.PENDING
            )
            return ExecutionResult(
                task.id,
                record.status,
                worker_output=output,
                verdict=verdict,
                test_result=test_result,
                branch=branch,
                written_paths=written,
                error="pre_commit hook failed",
                verdicts=all_verdicts,
            )

        commit_sha: str | None = None
        if use_git:
            commit_sha = commit_changes(task_workspace, task.id, output.summary)
            if commit_sha and not use_worktree:
                # sequential: merge inline now
                merge_task_to_main(workspace, task.id)
        record.status = TaskStatus.DONE
        return ExecutionResult(
            task.id,
            TaskStatus.DONE,
            worker_output=output,
            verdict=verdict,
            test_result=test_result,
            branch=branch,
            commit_sha=commit_sha,
            written_paths=written,
            task_workspace=task_workspace if use_worktree else None,
            needs_merge=use_worktree and bool(commit_sha),
            verdicts=all_verdicts,
        )

    if use_git and branch:
        _try_cleanup_branch(workspace, task.id, use_worktree)
    # No-git mode: files remain on disk; next attempt overwrites same paths.

    if test_failed and test_result is not None:
        test_msg = (
            f"tests failed (exit {test_result.exit_code}); "
            f"stderr tail: {test_result.stderr_tail[-400:]}"
        )
        record.last_review_reasons.append(test_msg)

    if blocked_by is not None:
        # Hard veto: skip retry budget, escalate immediately.
        record.status = TaskStatus.AWAITING_HITL
        audit.log(
            "executor_hard_veto",
            project_id=project_id,
            task_id=task.id,
            blocked_by=blocked_by,
            attempt=record.attempts,
        )
        error_msg = f"hard veto by {blocked_by}"
    elif verdict.has_unverifiable:
        # The criteria themselves are broken (ambiguous, or require data the
        # reviewer didn't have). Retrying with the same Worker won't help —
        # the Orchestrator needs to rewrite the criteria.
        record.status = TaskStatus.AWAITING_HITL
        audit.log(
            "executor_criteria_design_failure",
            project_id=project_id,
            task_id=task.id,
            unverifiable=[
                c.criterion
                for c in verdict.criteria_verdicts
                if c.status == "unverifiable"
            ],
            attempt=record.attempts,
        )
        error_msg = "criteria_design_failure (one or more criteria are unverifiable)"
    else:
        record.status = (
            TaskStatus.AWAITING_HITL
            if record.attempts >= max_attempts
            else TaskStatus.PENDING
        )
        error_msg = "test failure" if test_failed else "review rejected"

    return ExecutionResult(
        task.id,
        record.status,
        worker_output=output,
        verdict=verdict,
        test_result=test_result,
        branch=branch,
        written_paths=written,
        error=error_msg,
        verdicts=all_verdicts,
        blocked_by=blocked_by,
    )


def _is_hard_reject(verdict: SecurityVerdict | TestVerdict) -> bool:
    """A hard reviewer hard-rejects iff approved=False; severity is informational."""
    return not verdict.approved


def _merge_reviewer_reasons(record, verdict) -> None:
    """Annotate task_status with reviewer-tagged reasons so the next reader
    sees which reviewer raised which finding."""
    tag = verdict.reviewer
    record.last_review_reasons.extend(f"[{tag}] {r}" for r in verdict.reasons)
    if verdict.suggestions:
        record.last_review_suggestions.extend(
            f"[{tag}] {s}" for s in verdict.suggestions
        )


def _try_cleanup_branch(workspace: Path, task_id: str, use_worktree: bool) -> None:
    try:
        if use_worktree:
            remove_worktree(workspace, task_id)
        else:
            abandon_task_branch(workspace, task_id)
    except GitOperationFailed:
        pass
