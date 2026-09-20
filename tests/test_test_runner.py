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

import subprocess
import sys
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


class _FakePopen:
    """Stand-in for `subprocess.Popen` — `run_tests` now drives the child
    itself (Popen + communicate) instead of the one-shot `subprocess.run`,
    so process-tree cleanup on timeout works (see `_kill_tree`)."""

    def __init__(self, returncode: int, stdout: str = "", stderr: str = "") -> None:
        self.returncode = returncode
        self._stdout = stdout
        self._stderr = stderr
        self.pid = 4242

    def communicate(self, timeout: float | None = None):  # type: ignore[no-untyped-def]
        return self._stdout, self._stderr


def _fake_popen_factory(returncode: int, stdout: str = "", stderr: str = ""):
    def _factory(cmd, **kw):  # type: ignore[no-untyped-def]
        return _FakePopen(returncode, stdout, stderr)

    return _factory


def test_run_tests_normalizes_pytest_exit_5_when_scoped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """pytest exits 5 when no tests were collected. Under a per-task scope
    that just means 'this module has no tests' — neutral, not failure."""
    monkeypatch.setenv("ORTIM_TEST_CMD", "pytest -q")
    monkeypatch.setattr(
        subprocess, "Popen", _fake_popen_factory(5, "no tests ran in 0.01s", "")
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
    monkeypatch.setattr(subprocess, "Popen", _fake_popen_factory(5, "no tests ran", ""))
    result = run_tests(tmp_path, scope=None)
    assert result.exit_code == 5
    assert not result.passed


def test_run_tests_passes_scoped_cmd_to_subprocess(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """End-to-end shape check: the cmd that Popen sees actually contains the
    scope token. This is the integration glue between _apply_scope and
    run_tests."""
    monkeypatch.setenv("ORTIM_TEST_CMD", "npx vitest run")
    captured: dict[str, list[str]] = {}

    def _spy(cmd, **kw):  # type: ignore[no-untyped-def]
        captured["cmd"] = list(cmd)
        return _FakePopen(0)

    monkeypatch.setattr(subprocess, "Popen", _spy)
    run_tests(tmp_path, scope="task-service")
    assert "task-service" in captured["cmd"]
    assert "--passWithNoTests" in captured["cmd"]


# ---------------------------------------------------------------------------
# Timeout tree-kill — Faz-0 execution-sandbox hardening. `run_tests` must
# kill the whole process tree it spawned, not just the direct child, or a
# grandchild (watch-mode wrapper, `npx` launcher shim) survives as an
# orphan after the reported timeout. Uses real subprocesses — this is the
# one behavior a mock can't prove.
# ---------------------------------------------------------------------------


@pytest.mark.skipif(sys.platform.startswith("win"), reason="POSIX process-group test")
def test_run_tests_kills_grandchild_on_timeout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    marker = tmp_path / "grandchild_alive.txt"
    # Parent immediately backgrounds a grandchild that ticks a counter file
    # forever, then itself sleeps well past our timeout — mirrors a
    # watch-mode test runner that spawns a long-lived worker.
    script = (
        f"(while true; do date +%s%N >> {marker!s}; sleep 0.05; done & "
        f"disown; sleep 30)"
    )
    monkeypatch.setenv("ORTIM_TEST_CMD", f"sh -c '{script}'")

    result = run_tests(tmp_path, timeout=0.6)
    assert result.exit_code == 124

    # Give the grandchild a moment to have been reaped, then confirm the
    # counter file stopped growing — proof it was actually killed, not
    # just detached from the (already-dead) parent.
    import time

    assert marker.exists(), "grandchild never started"
    size_after_kill = marker.stat().st_size
    time.sleep(0.5)
    assert marker.stat().st_size == size_after_kill, (
        "grandchild kept writing after run_tests() timed out — "
        "process tree was not fully killed"
    )


@pytest.mark.skipif(not sys.platform.startswith("win"), reason="Windows taskkill /T test")
def test_run_tests_kills_grandchild_on_timeout_windows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Same guarantee as the POSIX test above, via `taskkill /F /T`.

    Note: this covers the realistic shape (a child that itself spawns a
    normal subprocess, e.g. `npx` -> `node` -> worker). A grandchild
    explicitly detached with `start /b` can still escape `taskkill /T` —
    a known Windows quirk, not something this fix claims to close;
    ortim's actual test-runner commands (pytest/vitest/flutter/cargo/go)
    don't self-detach like that.
    """
    import time

    marker = tmp_path / "grandchild_alive.txt"
    worker_script = tmp_path / "_worker.py"
    worker_script.write_text(
        "import time\n"
        f"f = open(r'{marker}', 'a')\n"
        "while True:\n"
        "    f.write('x')\n"
        "    f.flush()\n"
        "    time.sleep(0.05)\n",
        encoding="utf-8",
    )
    spawner_script = tmp_path / "_spawner.py"
    spawner_script.write_text(
        "import subprocess, sys\n"
        f"gc = subprocess.Popen([sys.executable, r'{worker_script}'])\n"
        "gc.wait()\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("ORTIM_TEST_CMD", f'"{sys.executable}" "{spawner_script}"')

    result = run_tests(tmp_path, timeout=0.8)
    assert result.exit_code == 124

    assert marker.exists(), "grandchild never started"
    size_after_kill = marker.stat().st_size
    time.sleep(0.6)
    assert marker.stat().st_size == size_after_kill, (
        "grandchild kept writing after run_tests() timed out — "
        "process tree was not fully killed"
    )
