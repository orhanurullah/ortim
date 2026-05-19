# SPDX-License-Identifier: FSL-1.1-Apache-2.0
# Copyright (c) 2026 ortim.dev
"""Tests for ortim.executor.test_runner.configured_plan workspace fallback.

Phase 0 (9c) introduces a workspace-scoped fallback: if `ORTIM_TEST_CMD`
is not set as an env var, but a `.ortim.env` file exists in the
workspace root and defines `ORTIM_TEST_CMD`, that value is used.

Together with bootstrap auto-writing `.ortim.env` at scaffold time,
this closes the silent-skip loophole: a freshly bootstrapped T2/web project
runs `vitest` even if the user never exports the env var.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from ortim.executor.test_runner import (
    _apply_scope,
    _detect_runner,
    configured_plan,
    run_tests,
)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ORTIM_TEST_CMD", raising=False)
    monkeypatch.delenv("AI_FACTORY_TESTS_ENABLED", raising=False)


def test_env_var_wins_over_workspace_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / ".ortim.env").write_text(
        'ORTIM_TEST_CMD="from-file"\n', encoding="utf-8"
    )
    monkeypatch.setenv("ORTIM_TEST_CMD", "from-env")
    plan = configured_plan(tmp_path)
    assert plan is not None
    assert plan.cmd == ["from-env"]
    assert "ORTIM_TEST_CMD" in plan.rationale


def test_workspace_file_used_when_env_unset(tmp_path: Path) -> None:
    (tmp_path / ".ortim.env").write_text(
        'ORTIM_TEST_CMD="npx vitest run"\n', encoding="utf-8"
    )
    plan = configured_plan(tmp_path)
    assert plan is not None
    # plan.cmd[0] is resolved through shutil.which so subprocess can find
    # `.cmd` shims on Windows. We don't assert the exact path (varies per
    # machine) — only that the basename matches and the rest is untouched.
    assert Path(plan.cmd[0]).stem.lower() == "npx"
    assert plan.cmd[1:] == ["vitest", "run"]
    assert ".ortim.env" in plan.rationale


def test_no_env_no_file_returns_none(tmp_path: Path) -> None:
    plan = configured_plan(tmp_path)
    assert plan is None


def test_workspace_file_missing_key_returns_none(tmp_path: Path) -> None:
    (tmp_path / ".ortim.env").write_text(
        "# only comments and unrelated keys\nFOO=bar\n", encoding="utf-8"
    )
    plan = configured_plan(tmp_path)
    assert plan is None


def test_workspace_file_handles_quoted_values(tmp_path: Path) -> None:
    (tmp_path / ".ortim.env").write_text(
        "ORTIM_TEST_CMD='pytest -q'\n", encoding="utf-8"
    )
    plan = configured_plan(tmp_path)
    assert plan is not None
    # `_resolve_binary` calls `shutil.which("pytest")` which returns the full
    # path on systems where pytest is on PATH (e.g. `C:\...\pytest.EXE` on
    # Windows). Compare on the basename so the test passes on both POSIX
    # and Windows. The assertion that matters here is that the quoted
    # `'pytest -q'` got split into two tokens — not that the first one is
    # literally "pytest".
    assert len(plan.cmd) == 2
    assert Path(plan.cmd[0]).stem.lower() == "pytest"
    assert plan.cmd[1] == "-q"


def test_disabled_via_env_overrides_everything(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / ".ortim.env").write_text(
        'ORTIM_TEST_CMD="vitest"\n', encoding="utf-8"
    )
    monkeypatch.setenv("AI_FACTORY_TESTS_ENABLED", "false")
    assert configured_plan(tmp_path) is None


# ---------------------------------------------------------------------------
# Item 39b — per-task scope. The runner appends `task.module_scope` to test
# commands that support positional path filtering. Without this, ONE broken
# test contaminates every downstream task's verdict (see tespit.md item 39b).
# ---------------------------------------------------------------------------


def test_apply_scope_appends_to_vitest_with_passwithnotests() -> None:
    result = _apply_scope(["npx", "vitest", "run"], "task-service")
    assert result == ["npx", "vitest", "run", "task-service", "--passWithNoTests"]


def test_apply_scope_vitest_passwithnotests_idempotent() -> None:
    # If the operator already configured --passWithNoTests in their env,
    # we shouldn't double-add it.
    result = _apply_scope(["npx", "vitest", "run", "--passWithNoTests"], "ui")
    assert result.count("--passWithNoTests") == 1
    assert "ui" in result


def test_apply_scope_appends_to_pytest() -> None:
    assert _apply_scope(["pytest", "-q"], "task_service") == [
        "pytest",
        "-q",
        "task_service",
    ]


def test_apply_scope_appends_to_flutter_test() -> None:
    assert _apply_scope(["flutter", "test"], "lib/widgets") == [
        "flutter",
        "test",
        "lib/widgets",
    ]


def test_apply_scope_cargo_left_unchanged_legacy() -> None:
    # cargo uses package-name flag (-p name), not a path. Per item 39b' the
    # cargo adapter is deferred — workspace-wide behavior preserved.
    cmd = ["cargo", "test"]
    assert _apply_scope(cmd, "some-crate") == cmd


def test_apply_scope_go_test_left_unchanged_legacy() -> None:
    # go test uses ./<pkg>/... pattern, not append. Deferred to 39b'.
    cmd = ["go", "test", "./..."]
    assert _apply_scope(cmd, "store") == cmd


def test_apply_scope_none_or_empty_is_noop() -> None:
    cmd = ["pytest", "-q"]
    assert _apply_scope(cmd, None) is cmd
    assert _apply_scope(cmd, "") is cmd


def test_detect_runner_recognizes_resolved_paths() -> None:
    # shutil.which resolves `pytest` to `C:\Python\Scripts\pytest.exe` on
    # Windows; the detection logic must look at basename.stem.
    assert _detect_runner(["C:\\Python\\Scripts\\pytest.exe", "-q"]) == "pytest"
    assert _detect_runner(["/usr/local/bin/npx", "vitest", "run"]) == "vitest"


def _fake_completed(returncode: int, stdout: str = "", stderr: str = ""):
    """Build a subprocess.CompletedProcess stand-in for monkeypatch."""

    class _Stub:
        def __init__(self) -> None:
            self.returncode = returncode
            self.stdout = stdout
            self.stderr = stderr

    return _Stub()


def test_run_tests_normalizes_pytest_exit_5_when_scoped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """pytest exits 5 when no tests were collected. Under a per-task scope
    that just means 'this module has no tests' — neutral, not failure."""
    monkeypatch.setenv("ORTIM_TEST_CMD", "pytest -q")
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *a, **kw: _fake_completed(5, "no tests ran in 0.01s", ""),
    )
    result = run_tests(tmp_path, scope="empty_module")
    assert result.exit_code == 0
    assert result.passed
    assert "normalized" in result.stdout_tail


def test_run_tests_does_not_normalize_pytest_exit_5_when_unscoped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Workspace-wide pytest returning 5 means the project has zero tests
    — genuinely suspicious. Don't normalize that away."""
    monkeypatch.setenv("ORTIM_TEST_CMD", "pytest -q")
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *a, **kw: _fake_completed(5, "no tests ran", ""),
    )
    result = run_tests(tmp_path, scope=None)
    assert result.exit_code == 5
    assert not result.passed


def test_run_tests_passes_scoped_cmd_to_subprocess(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """End-to-end shape check: the cmd that subprocess.run sees actually
    contains the scope token. This is the integration glue between
    _apply_scope and run_tests."""
    monkeypatch.setenv("ORTIM_TEST_CMD", "npx vitest run")
    captured: dict[str, list[str]] = {}

    def _spy(cmd, **kw):  # type: ignore[no-untyped-def]
        captured["cmd"] = list(cmd)
        return _fake_completed(0)

    monkeypatch.setattr(subprocess, "run", _spy)
    run_tests(tmp_path, scope="task-service")
    assert "task-service" in captured["cmd"]
    assert "--passWithNoTests" in captured["cmd"]
