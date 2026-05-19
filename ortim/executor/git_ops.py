# SPDX-License-Identifier: FSL-1.1-Apache-2.0
# Copyright (c) 2026 ortim.dev
"""Per-task git branch isolation — subprocess wrapper.

The workspace becomes its own git repo on the first execute(). Each task
gets a `task/<task-id>` branch; on reviewer approval it merges to main and
the branch is deleted. On rejection the branch is abandoned (`branch -D`)
which discards the Worker's writes without touching main.

Best-effort by default: if `git` is not on PATH, ops are skipped and the
runner proceeds without isolation. Set `ORTIM_GIT_ENABLED=true` to
require git (raises `GitNotAvailable` if missing) or `=false` to disable
even when present.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from ortim.env import env_get


class GitNotAvailable(Exception):
    pass


class GitOperationFailed(Exception):
    def __init__(self, cmd: list[str], stderr: str) -> None:
        super().__init__(
            f"git {' '.join(cmd)} failed: {stderr.strip()[:300]}"
        )
        self.cmd = cmd
        self.stderr = stderr


def git_available() -> bool:
    return shutil.which("git") is not None


def git_enabled(workspace: Path) -> bool:
    """Resolve env-var preference into an effective on/off decision.

    Raises `GitNotAvailable` if the user explicitly required git but the
    binary is missing. The `workspace` arg is reserved for future per-project
    overrides via `.ortim.toml`.
    """
    flag = (env_get("ORTIM_GIT_ENABLED", "auto") or "auto").lower()
    if flag == "false":
        return False
    if flag in ("true", "1", "yes"):
        if not git_available():
            raise GitNotAvailable(
                "ORTIM_GIT_ENABLED=true but `git` is not on PATH"
            )
        return True
    return git_available()


def _run(
    args: list[str], cwd: Path, *, check: bool = True, timeout: float = 30.0
) -> subprocess.CompletedProcess[str]:
    # `stdin=DEVNULL` is required on Python 3.14 + Windows: subprocess
    # tries to inherit the parent's stdin handle even when only stdout/
    # stderr are piped via `capture_output=True`. Under pytest the parent
    # stdin handle is invalid, and `_make_inheritable` raises
    # `OSError: [WinError 6/50]`. DEVNULL gives subprocess a valid sentinel
    # so it doesn't touch the parent handle. No behavioral change — git
    # never reads stdin in these invocations.
    result = subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
    )
    if check and result.returncode != 0:
        raise GitOperationFailed(args, result.stderr)
    return result


def is_repo(workspace: Path) -> bool:
    return (workspace / ".git").exists()


def ensure_repo(workspace: Path) -> None:
    """Initialize a git repo with a `main` branch and a baseline empty commit.

    The seed commit gives subsequent task branches a base to diverge from
    even before any Worker output exists.
    """
    if is_repo(workspace):
        return
    workspace.mkdir(parents=True, exist_ok=True)
    _run(["init", "-b", "main"], workspace)
    _run(["config", "user.email", "ortim@local"], workspace)
    _run(["config", "user.name", "ortim"], workspace)
    _run(["commit", "--allow-empty", "-m", "ortim: workspace init"], workspace)


def current_branch(workspace: Path) -> str:
    return _run(["rev-parse", "--abbrev-ref", "HEAD"], workspace).stdout.strip()


def start_task_branch(workspace: Path, task_id: str) -> str:
    """Switch to main, drop any pre-existing task branch, then create a fresh one."""
    branch = f"task/{task_id}"
    _run(["checkout", "main"], workspace)
    existing = _run(["branch", "--list", branch], workspace, check=False).stdout.strip()
    if existing:
        _run(["branch", "-D", branch], workspace)
    _run(["checkout", "-b", branch], workspace)
    return branch


def commit_changes(workspace: Path, task_id: str, summary: str) -> str:
    """Stage everything and commit. Returns commit SHA, or empty string if nothing to commit."""
    _run(["add", "-A"], workspace)
    diff = _run(["diff", "--cached", "--quiet"], workspace, check=False)
    if diff.returncode == 0:
        return ""
    msg = f"{task_id}: {summary[:120]}"
    _run(["commit", "-m", msg], workspace)
    return _run(["rev-parse", "HEAD"], workspace).stdout.strip()


def merge_task_to_main(workspace: Path, task_id: str) -> None:
    """Merge `task/<id>` into main on the primary repo, then drop the branch.

    Worktree-aware: if a worktree at `.worktrees/<task_id>` is still pinned
    to this branch, we remove it before `branch -D` so the deletion succeeds.
    """
    branch = f"task/{task_id}"
    _run(["checkout", "main"], workspace)
    _run(["merge", "--no-ff", branch, "-m", f"merge {branch}"], workspace)
    target = worktree_path(workspace, task_id)
    if target.exists():
        _run(["worktree", "remove", "--force", str(target)], workspace, check=False)
    _run(["branch", "-D", branch], workspace)


def abandon_task_branch(workspace: Path, task_id: str) -> None:
    """Discard the task branch entirely. Caller has already decided to reject."""
    branch = f"task/{task_id}"
    if current_branch(workspace) == branch:
        _run(["checkout", "main"], workspace)
    _run(["branch", "-D", branch], workspace, check=False)


# ---- Worktree support (v0.5c — parallel batch execution) ----------------------
#
# In sequential mode the executor checks the primary repo out to `task/<id>`
# and operates there. That serializes all task work because there is only one
# working tree. For parallel mode we attach an extra worktree per task at
# `<workspace>/.worktrees/<task_id>` so multiple Workers can write and run
# tests concurrently without stepping on each other; merges back to main are
# serialized in the caller.


def worktree_root(workspace: Path) -> Path:
    return workspace / ".worktrees"


def worktree_path(workspace: Path, task_id: str) -> Path:
    safe = task_id.replace("/", "_").replace("\\", "_")
    return worktree_root(workspace) / safe


def _branch_exists(workspace: Path, branch: str) -> bool:
    return bool(
        _run(["branch", "--list", branch], workspace, check=False).stdout.strip()
    )


def add_worktree(workspace: Path, task_id: str) -> Path:
    """Create a `.worktrees/<task_id>` worktree on a fresh `task/<id>` branch.

    Cleans up any stale worktree/branch from a prior attempt first so the
    operation is idempotent.
    """
    target = worktree_path(workspace, task_id)
    branch = f"task/{task_id}"

    if target.exists():
        _run(["worktree", "remove", "--force", str(target)], workspace, check=False)
    if _branch_exists(workspace, branch):
        _run(["branch", "-D", branch], workspace, check=False)

    worktree_root(workspace).mkdir(parents=True, exist_ok=True)
    _run(["worktree", "add", "-b", branch, str(target), "main"], workspace)
    return target


def remove_worktree(workspace: Path, task_id: str) -> None:
    target = worktree_path(workspace, task_id)
    if target.exists():
        _run(["worktree", "remove", "--force", str(target)], workspace, check=False)
    branch = f"task/{task_id}"
    _run(["branch", "-D", branch], workspace, check=False)
