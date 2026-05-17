# SPDX-License-Identifier: FSL-1.1-Apache-2.0
# Copyright (c) 2026 ortim.dev
"""Executor: Worker + reviewer chain + git lifecycle (v0.6b — multi-reviewer hard veto)."""

from ortim.executor.git_ops import (
    GitNotAvailable,
    GitOperationFailed,
    abandon_task_branch,
    add_worktree,
    commit_changes,
    current_branch,
    ensure_repo,
    git_available,
    git_enabled,
    is_repo,
    merge_task_to_main,
    remove_worktree,
    start_task_branch,
    worktree_path,
    worktree_root,
)
from ortim.executor.perf_reviewer import PerfReviewerAgent, PerfVerdict
from ortim.executor.reviewer import CodeReviewerAgent, ReviewVerdict
from ortim.executor.runner import ExecutionResult, ReviewerChain, execute_task
from ortim.executor.sandbox import (
    SandboxViolation,
    check_extension,
    check_in_scope,
    normalize_relative,
    resolve_in_workspace,
)
from ortim.executor.security_reviewer import (
    SecurityReviewerAgent,
    SecurityVerdict,
)
from ortim.executor.status import TaskRunRecord, TaskStatus, TaskStatusFile
from ortim.executor.test_reviewer import (
    ACCoverageEntry,
    TestReviewerAgent,
    TestVerdict,
)
from ortim.executor.test_runner import TestPlan, TestResult, configured_plan, run_tests
from ortim.executor.worker import (
    FileChange,
    WorkerAgent,
    WorkerOutOfScope,
    WorkerOutput,
    WorkerSkillNotConsulted,
)

__all__ = [
    "ACCoverageEntry",
    "CodeReviewerAgent",
    "ExecutionResult",
    "FileChange",
    "GitNotAvailable",
    "GitOperationFailed",
    "PerfReviewerAgent",
    "PerfVerdict",
    "ReviewVerdict",
    "ReviewerChain",
    "SandboxViolation",
    "SecurityReviewerAgent",
    "SecurityVerdict",
    "TaskRunRecord",
    "TaskStatus",
    "TaskStatusFile",
    "TestPlan",
    "TestResult",
    "TestReviewerAgent",
    "TestVerdict",
    "WorkerAgent",
    "WorkerOutOfScope",
    "WorkerOutput",
    "WorkerSkillNotConsulted",
    "abandon_task_branch",
    "add_worktree",
    "check_extension",
    "check_in_scope",
    "commit_changes",
    "configured_plan",
    "current_branch",
    "ensure_repo",
    "execute_task",
    "git_available",
    "git_enabled",
    "is_repo",
    "merge_task_to_main",
    "normalize_relative",
    "remove_worktree",
    "resolve_in_workspace",
    "run_tests",
    "start_task_branch",
    "worktree_path",
    "worktree_root",
]
