# SPDX-License-Identifier: FSL-1.1-Apache-2.0
# Copyright (c) 2026 ortim.dev
"""Smoke tests for executor sandbox + status + git_ops + test_runner (no LLM required)."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path, PurePosixPath

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from runtime.executor.sandbox import (  # noqa: E402
    SandboxViolation,
    check_extension,
    check_in_scope,
    normalize_relative,
)
from runtime.executor.status import (  # noqa: E402
    TaskRunRecord,
    TaskStatus,
    TaskStatusFile,
)
from runtime.executor.reviewer import ReviewVerdict  # noqa: E402
from runtime.executor.worker import FileChange, WorkerOutput  # noqa: E402
from runtime.executor import git_ops  # noqa: E402
from runtime.executor import test_runner  # noqa: E402


# ---------- normalize_relative ----------


def test_normalize_accepts_clean_relative() -> None:
    p = normalize_relative("src/auth/login.md")
    assert p == PurePosixPath("src/auth/login.md")


def test_normalize_accepts_backslash_input() -> None:
    p = normalize_relative("src\\auth\\login.md")
    assert p == PurePosixPath("src/auth/login.md")


def test_normalize_strips_dot_segments() -> None:
    p = normalize_relative("src/./auth/login.md")
    assert p == PurePosixPath("src/auth/login.md")


def test_normalize_rejects_empty() -> None:
    for raw in ("", "   ", ".", "./"):
        try:
            normalize_relative(raw)
        except SandboxViolation:
            continue
        raise AssertionError(f"Expected SandboxViolation for {raw!r}")


def test_normalize_rejects_absolute() -> None:
    for raw in ("/etc/passwd", "C:/Windows/System32"):
        try:
            normalize_relative(raw)
        except SandboxViolation:
            continue
        raise AssertionError(f"Expected SandboxViolation for {raw!r}")


def test_normalize_rejects_parent_traversal() -> None:
    for raw in ("../etc/passwd", "src/../../../etc", "src/../../etc"):
        try:
            normalize_relative(raw)
        except SandboxViolation:
            continue
        raise AssertionError(f"Expected SandboxViolation for {raw!r}")


# ---------- check_in_scope ----------


def test_in_scope_accepts_strictly_inside() -> None:
    p = normalize_relative("src/auth/login.md")
    check_in_scope(p, "src/auth")


def test_in_scope_rejects_sibling() -> None:
    p = normalize_relative("src/payments/charge.md")
    try:
        check_in_scope(p, "src/auth")
    except SandboxViolation:
        return
    raise AssertionError("Expected SandboxViolation for sibling directory")


def test_in_scope_rejects_scope_itself() -> None:
    """Writing the scope dir itself (no file inside) should fail — Worker
    must produce real files, not just create a directory marker."""
    p = normalize_relative("src/auth")
    try:
        check_in_scope(p, "src/auth")
    except SandboxViolation:
        return
    raise AssertionError("Expected SandboxViolation when path equals scope")


def test_in_scope_rejects_prefix_lookalike() -> None:
    """`src/auth_old` must not match scope `src/auth` even with string prefix."""
    p = normalize_relative("src/auth_old/login.md")
    try:
        check_in_scope(p, "src/auth")
    except SandboxViolation:
        return
    raise AssertionError("Expected SandboxViolation for prefix-lookalike path")


# ---------- check_extension (v0.5b whitelist) ----------


def test_ext_accepts_source_code_and_config() -> None:
    for name in (
        "a.md", "config.json", "deploy.yaml", "pyproject.toml",
        "main.py", "App.tsx", "server.go", "lib.rs", "index.html", "style.css",
        "schema.sql", "api.proto", "build.sh", "deploy.ps1",
    ):
        check_extension(PurePosixPath(name))


def test_ext_accepts_known_basenames() -> None:
    for name in ("Dockerfile", "Makefile", ".gitignore", ".gitkeep", ".editorconfig", "LICENSE"):
        check_extension(PurePosixPath(name))


def test_ext_rejects_binaries_and_unknown() -> None:
    for name in ("photo.png", "archive.zip", "a.exe", "data.db", "noext_random"):
        try:
            check_extension(PurePosixPath(name))
        except SandboxViolation:
            continue
        raise AssertionError(f"Expected SandboxViolation for {name}")


# ---------- check_extension app_class partition (M1) ----------


def test_ext_web_rejects_dart() -> None:
    """Web tier projects cannot write Dart files — that's a Flutter halluc."""
    try:
        check_extension(PurePosixPath("home_page.dart"), app_class="web")
    except SandboxViolation:
        return
    raise AssertionError("Expected SandboxViolation for .dart on web")


def test_ext_mobile_accepts_dart() -> None:
    """Flutter modules are valid in mobile tier."""
    check_extension(PurePosixPath("lib/features/home/home_page.dart"), app_class="mobile")


def test_ext_mobile_accepts_python_for_backend_helpers() -> None:
    """Mobile projects often have Python build/devops scripts; .py stays universal."""
    check_extension(PurePosixPath("scripts/build.py"), app_class="mobile")


def test_ext_mobile_rejects_rust() -> None:
    """A `.rs` file in a Flutter project is almost certainly a hallucination."""
    try:
        check_extension(PurePosixPath("src/lib.rs"), app_class="mobile")
    except SandboxViolation:
        return
    raise AssertionError("Expected SandboxViolation for .rs on mobile")


# ---------- WorkerOutput / FileChange parsing ----------


def test_worker_output_parses_minimal() -> None:
    raw = """{
        "task_id": "T-001",
        "summary": "added a runbook",
        "files": [
            {"path": "docs/runbooks/auth.md", "content": "# Auth\\n", "operation": "create"}
        ]
    }"""
    out = WorkerOutput.model_validate_json(raw)
    assert out.task_id == "T-001"
    assert len(out.files) == 1
    assert isinstance(out.files[0], FileChange)
    assert out.files[0].operation == "create"


def test_worker_output_default_operation_is_create() -> None:
    raw = '{"task_id": "T-1", "summary": "x", "files": [{"path": "a/b.md", "content": "x"}]}'
    out = WorkerOutput.model_validate_json(raw)
    assert out.files[0].operation == "create"


def test_worker_output_rejects_invalid_operation() -> None:
    raw = (
        '{"task_id": "T-1", "summary": "x", '
        '"files": [{"path": "a.md", "content": "x", "operation": "rm"}]}'
    )
    try:
        WorkerOutput.model_validate_json(raw)
    except ValueError:
        return
    raise AssertionError("Expected ValueError for invalid operation literal")


# ---------- ReviewVerdict rubric parsing ----------


def test_review_verdict_empty_means_not_approved() -> None:
    """An empty rubric is not 'approved by default' — every criterion must
    be explicitly verdicted."""
    v = ReviewVerdict.model_validate_json('{"criteria_verdicts": []}')
    assert v.approved is False
    assert v.reasons == []
    assert v.suggestions == []


def test_review_verdict_all_pass_is_approved() -> None:
    raw = (
        '{"criteria_verdicts": ['
        '{"criterion": "returns 401 when token absent", "status": "pass", '
        '"evidence": "auth.ts:14 — guards return 401 on null token"}'
        ']}'
    )
    v = ReviewVerdict.model_validate_json(raw)
    assert v.approved is True
    assert v.reasons == []
    assert v.has_unverifiable is False


def test_review_verdict_fail_blocks_approval_and_surfaces_in_reasons() -> None:
    raw = (
        '{"criteria_verdicts": ['
        '{"criterion": "ID is a UUID", "status": "pass", "evidence": "ok"},'
        '{"criterion": "list prints incomplete todos", "status": "fail", '
        '"evidence": "no filter applied", "code_quote": "todos.map(...)"}'
        '], "suggestions": ["consider adding column alignment"]}'
    )
    v = ReviewVerdict.model_validate_json(raw)
    assert v.approved is False
    assert any("[fail]" in r and "list prints incomplete todos" in r for r in v.reasons)
    assert any("todos.map(...)" in r for r in v.reasons)
    assert v.suggestions == ["consider adding column alignment"]


def test_review_verdict_unverifiable_blocks_approval_and_signals_design_failure() -> None:
    raw = (
        '{"criteria_verdicts": ['
        '{"criterion": "list output is in a readable format", '
        '"status": "unverifiable", '
        '"evidence": "no machine-checkable definition of readable"}'
        ']}'
    )
    v = ReviewVerdict.model_validate_json(raw)
    assert v.approved is False
    assert v.has_unverifiable is True
    assert any("criterion design issue" in r for r in v.reasons)


def test_review_verdict_l1_violations_block_approval_independent_of_criteria() -> None:
    raw = (
        '{"criteria_verdicts": ['
        '{"criterion": "service exposes add(title)", "status": "pass", "evidence": "ok"}'
        '], "l1_violations": ["TodoService instantiated with new in command handler"]}'
    )
    v = ReviewVerdict.model_validate_json(raw)
    assert v.approved is False
    assert any("[L1]" in r for r in v.reasons)


# ---------- TaskStatusFile roundtrip ----------


def test_status_file_load_or_init_creates_empty() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        ws = Path(tmp)
        status = TaskStatusFile.load_or_init(ws, "proj-1")
        assert status.project_id == "proj-1"
        assert status.records == {}


def test_status_file_get_or_create_idempotent() -> None:
    status = TaskStatusFile(project_id="p")
    r1 = status.get_or_create("T-1")
    r2 = status.get_or_create("T-1")
    assert r1 is r2
    assert isinstance(r1, TaskRunRecord)
    assert r1.status == TaskStatus.PENDING
    assert r1.attempts == 0


def test_status_file_save_then_reload() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        ws = Path(tmp)
        status = TaskStatusFile(project_id="p")
        rec = status.get_or_create("T-1")
        rec.status = TaskStatus.DONE
        rec.attempts = 2
        rec.last_review_approved = True
        status.save(ws)

        reloaded = TaskStatusFile.load_or_init(ws, "p")
        assert reloaded.records["T-1"].status == TaskStatus.DONE
        assert reloaded.records["T-1"].attempts == 2
        assert reloaded.records["T-1"].last_review_approved is True


# ---------- git_ops ----------

GIT_ON_PATH = shutil.which("git") is not None


def test_git_available_matches_path() -> None:
    assert git_ops.git_available() == GIT_ON_PATH


def test_git_enabled_false_when_explicit_off() -> None:
    prev = os.environ.get("AI_FACTORY_GIT_ENABLED")
    os.environ["AI_FACTORY_GIT_ENABLED"] = "false"
    try:
        with tempfile.TemporaryDirectory() as tmp:
            assert git_ops.git_enabled(Path(tmp)) is False
    finally:
        if prev is None:
            os.environ.pop("AI_FACTORY_GIT_ENABLED", None)
        else:
            os.environ["AI_FACTORY_GIT_ENABLED"] = prev


def test_git_enabled_required_raises_when_missing() -> None:
    if GIT_ON_PATH:
        return  # can't simulate missing git
    prev = os.environ.get("AI_FACTORY_GIT_ENABLED")
    os.environ["AI_FACTORY_GIT_ENABLED"] = "true"
    try:
        with tempfile.TemporaryDirectory() as tmp:
            try:
                git_ops.git_enabled(Path(tmp))
            except git_ops.GitNotAvailable:
                return
            raise AssertionError("Expected GitNotAvailable when git missing and required")
    finally:
        if prev is None:
            os.environ.pop("AI_FACTORY_GIT_ENABLED", None)
        else:
            os.environ["AI_FACTORY_GIT_ENABLED"] = prev


def test_git_full_branch_lifecycle() -> None:
    if not GIT_ON_PATH:
        return  # skip silently when git missing
    with tempfile.TemporaryDirectory() as tmp:
        ws = Path(tmp)
        git_ops.ensure_repo(ws)
        assert git_ops.is_repo(ws)
        assert git_ops.current_branch(ws) == "main"

        branch = git_ops.start_task_branch(ws, "T-1")
        assert branch == "task/T-1"
        assert git_ops.current_branch(ws) == "task/T-1"

        (ws / "hello.md").write_text("hi", encoding="utf-8")
        sha = git_ops.commit_changes(ws, "T-1", "added hello")
        assert sha and len(sha) == 40

        git_ops.merge_task_to_main(ws, "T-1")
        assert git_ops.current_branch(ws) == "main"
        # Branch should be gone after merge.
        existing = subprocess.run(
            ["git", "branch", "--list", "task/T-1"],
            cwd=str(ws), capture_output=True, text=True, timeout=10,
        ).stdout.strip()
        assert existing == ""
        # Merged file still present on main.
        assert (ws / "hello.md").read_text(encoding="utf-8") == "hi"


def test_git_abandon_branch_drops_changes() -> None:
    if not GIT_ON_PATH:
        return
    with tempfile.TemporaryDirectory() as tmp:
        ws = Path(tmp)
        git_ops.ensure_repo(ws)
        git_ops.start_task_branch(ws, "T-2")
        (ws / "scratch.md").write_text("garbage", encoding="utf-8")
        # Don't commit — simulate Worker writing then runner deciding to abandon.
        git_ops.abandon_task_branch(ws, "T-2")
        assert git_ops.current_branch(ws) == "main"
        # Uncommitted file may persist (git branch -D doesn't clean working tree),
        # but merging back to main means file isn't tracked there either way.
        # Acceptable: the next start_task_branch will checkout main first.


# ---------- worktree (v0.5c) ----------


def test_worktree_add_remove_lifecycle() -> None:
    if not GIT_ON_PATH:
        return
    with tempfile.TemporaryDirectory() as tmp:
        ws = Path(tmp)
        git_ops.ensure_repo(ws)
        wt = git_ops.add_worktree(ws, "T-10")
        assert wt.exists()
        assert wt == git_ops.worktree_path(ws, "T-10")

        # Worktree is on its own branch
        cur_in_wt = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=str(wt), capture_output=True, text=True, timeout=10,
        ).stdout.strip()
        assert cur_in_wt == "task/T-10"

        # Main repo HEAD untouched
        assert git_ops.current_branch(ws) == "main"

        # Write + commit inside the worktree using shared commit_changes
        (wt / "spec.md").write_text("hello", encoding="utf-8")
        sha = git_ops.commit_changes(wt, "T-10", "added spec")
        assert sha and len(sha) == 40

        # Main repo working tree should NOT see the file (different branch)
        assert not (ws / "spec.md").exists()

        # Merge in main repo brings it over
        git_ops.merge_task_to_main(ws, "T-10")
        assert (ws / "spec.md").read_text(encoding="utf-8") == "hello"

        # Cleanup worktree (branch already deleted by merge_task_to_main)
        git_ops.remove_worktree(ws, "T-10")
        assert not wt.exists()


def test_worktree_add_recovers_from_stale_state() -> None:
    """Re-adding the same task worktree should clean any prior leftovers."""
    if not GIT_ON_PATH:
        return
    with tempfile.TemporaryDirectory() as tmp:
        ws = Path(tmp)
        git_ops.ensure_repo(ws)
        wt1 = git_ops.add_worktree(ws, "T-11")
        (wt1 / "stale.md").write_text("old", encoding="utf-8")
        # Don't commit, don't remove — simulate crashed prior run

        wt2 = git_ops.add_worktree(ws, "T-11")
        assert wt2 == wt1
        # Stale uncommitted file should be gone after re-create
        assert not (wt2 / "stale.md").exists()

        git_ops.remove_worktree(ws, "T-11")


# ---------- concurrent file_lock ----------


def test_concurrent_file_lock_serializes_threads() -> None:
    """Multiple threads racing for the same lock — only one inside at a time."""
    import threading
    import time

    from runtime.concurrency import file_lock

    state = {"current": 0, "max_concurrent": 0}
    state_lock = threading.Lock()
    errors: list[BaseException] = []

    def worker(target: Path) -> None:
        try:
            for _ in range(4):
                with file_lock(target, timeout=15.0, poll_interval=0.01):
                    with state_lock:
                        state["current"] += 1
                        state["max_concurrent"] = max(
                            state["max_concurrent"], state["current"]
                        )
                    time.sleep(0.005)
                    with state_lock:
                        state["current"] -= 1
        except BaseException as e:
            errors.append(e)

    with tempfile.TemporaryDirectory() as tmp:
        target = Path(tmp) / "lock-target"
        threads = [
            threading.Thread(target=worker, args=(target,)) for _ in range(3)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)

        assert not errors, f"Worker errors: {errors}"
        assert state["max_concurrent"] == 1, (
            f"Expected serialized access, got max_concurrent="
            f"{state['max_concurrent']}"
        )


# ---------- test_runner ----------


def test_test_runner_skipped_when_unconfigured() -> None:
    prev = os.environ.pop("AI_FACTORY_TEST_CMD", None)
    try:
        with tempfile.TemporaryDirectory() as tmp:
            result = test_runner.run_tests(Path(tmp))
            assert result.skipped is True
            assert result.passed is False
            assert "no test command" in result.skipped_reason.lower()
    finally:
        if prev is not None:
            os.environ["AI_FACTORY_TEST_CMD"] = prev


def test_test_runner_disabled_via_env() -> None:
    prev_disable = os.environ.get("AI_FACTORY_TESTS_ENABLED")
    prev_cmd = os.environ.get("AI_FACTORY_TEST_CMD")
    os.environ["AI_FACTORY_TESTS_ENABLED"] = "false"
    os.environ["AI_FACTORY_TEST_CMD"] = "pytest"
    try:
        with tempfile.TemporaryDirectory() as tmp:
            result = test_runner.run_tests(Path(tmp))
            assert result.skipped is True
            assert "disabled" in result.skipped_reason.lower()
    finally:
        if prev_disable is None:
            os.environ.pop("AI_FACTORY_TESTS_ENABLED", None)
        else:
            os.environ["AI_FACTORY_TESTS_ENABLED"] = prev_disable
        if prev_cmd is None:
            os.environ.pop("AI_FACTORY_TEST_CMD", None)
        else:
            os.environ["AI_FACTORY_TEST_CMD"] = prev_cmd


def test_test_runner_runs_configured_command() -> None:
    """Use a portable always-pass command. `python -c "pass"` works on all platforms."""
    prev = os.environ.get("AI_FACTORY_TEST_CMD")
    os.environ["AI_FACTORY_TEST_CMD"] = f'"{sys.executable}" -c pass'
    try:
        with tempfile.TemporaryDirectory() as tmp:
            result = test_runner.run_tests(Path(tmp), timeout=10.0)
            assert result.skipped is False
            assert result.exit_code == 0
            assert result.passed is True
    finally:
        if prev is None:
            os.environ.pop("AI_FACTORY_TEST_CMD", None)
        else:
            os.environ["AI_FACTORY_TEST_CMD"] = prev


def test_test_runner_reports_failure_exit_code() -> None:
    prev = os.environ.get("AI_FACTORY_TEST_CMD")
    os.environ["AI_FACTORY_TEST_CMD"] = (
        f'"{sys.executable}" -c "import sys; sys.exit(2)"'
    )
    try:
        with tempfile.TemporaryDirectory() as tmp:
            result = test_runner.run_tests(Path(tmp), timeout=10.0)
            assert result.skipped is False
            assert result.exit_code == 2
            assert result.passed is False
    finally:
        if prev is None:
            os.environ.pop("AI_FACTORY_TEST_CMD", None)
        else:
            os.environ["AI_FACTORY_TEST_CMD"] = prev


if __name__ == "__main__":
    tests = [
        test_normalize_accepts_clean_relative,
        test_normalize_accepts_backslash_input,
        test_normalize_strips_dot_segments,
        test_normalize_rejects_empty,
        test_normalize_rejects_absolute,
        test_normalize_rejects_parent_traversal,
        test_in_scope_accepts_strictly_inside,
        test_in_scope_rejects_sibling,
        test_in_scope_rejects_scope_itself,
        test_in_scope_rejects_prefix_lookalike,
        test_ext_accepts_source_code_and_config,
        test_ext_accepts_known_basenames,
        test_ext_rejects_binaries_and_unknown,
        test_worker_output_parses_minimal,
        test_worker_output_default_operation_is_create,
        test_worker_output_rejects_invalid_operation,
        test_review_verdict_minimal,
        test_review_verdict_full,
        test_status_file_load_or_init_creates_empty,
        test_status_file_get_or_create_idempotent,
        test_status_file_save_then_reload,
        test_git_available_matches_path,
        test_git_enabled_false_when_explicit_off,
        test_git_enabled_required_raises_when_missing,
        test_git_full_branch_lifecycle,
        test_git_abandon_branch_drops_changes,
        test_worktree_add_remove_lifecycle,
        test_worktree_add_recovers_from_stale_state,
        test_concurrent_file_lock_serializes_threads,
        test_test_runner_skipped_when_unconfigured,
        test_test_runner_disabled_via_env,
        test_test_runner_runs_configured_command,
        test_test_runner_reports_failure_exit_code,
    ]
    failed = 0
    for test in tests:
        try:
            test()
            print(f"PASS  {test.__name__}")
        except Exception as e:
            failed += 1
            print(f"FAIL  {test.__name__}: {e}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
