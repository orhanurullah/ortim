# SPDX-License-Identifier: FSL-1.1-Apache-2.0
# Copyright (c) 2026 ortim.dev
"""Tests for `ortim demo` — the end-to-end planning walkthrough.

The demo command spawns subprocesses for the underlying `run` / `advance`
steps, so its real value (LLM-driven chain produces a workspace) is
validated by a separate live run, not by unit tests.

These tests pin the things we *can* check deterministically:

  * Pre-flight: aborts cleanly when no LLM API key is set.
  * Project creation: the demo creates a project + workspace before
    delegating to subprocesses.
  * Default brief: the hardcoded brief is non-empty and stable.
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import pytest  # noqa: E402
from typer.testing import CliRunner  # noqa: E402

from ortim.main import _DEMO_DEFAULT_BRIEF, app  # noqa: E402
from ortim.orchestrator import Project  # noqa: E402


def _runner() -> CliRunner:
    # mix_stderr=False so we can read stderr separately if needed
    return CliRunner()


def test_demo_default_brief_is_non_empty_english() -> None:
    """The default brief ships to every user — verify it's a real
    sentence so the demo doesn't accidentally pass `""` to Babel."""
    assert _DEMO_DEFAULT_BRIEF.strip()
    assert len(_DEMO_DEFAULT_BRIEF) > 30
    assert "todo" in _DEMO_DEFAULT_BRIEF.lower()


def test_demo_aborts_when_no_llm_key_present(monkeypatch: pytest.MonkeyPatch) -> None:
    """No DEEPSEEK_API_KEY and no ANTHROPIC_API_KEY → exit code 1 with
    a pointer to `ortim doctor`. Critical: this runs in CI / fresh
    machines where neither key is set and we want a friendly error,
    not a stack trace from the Babel layer.

    The demo command reads `os.environ` directly (not CliRunner's env=),
    so we monkeypatch the actual process environment."""
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    runner = _runner()
    result = runner.invoke(app, ["demo"], catch_exceptions=False)
    assert result.exit_code == 1
    assert "No LLM API key" in result.stdout
    assert "ortim doctor" in result.stdout


def test_demo_creates_project_workspace_before_running_subprocesses(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Mock `subprocess.run` to short-circuit the chain after the first
    call and verify the project + state.json landed on disk. Proves the
    in-process project bootstrap happens before any subprocess fires,
    so a subprocess failure doesn't leave the user with no workspace.

    `WORKSPACE_ROOT` is a module-level constant resolved at import time,
    so we monkeypatch the binding in `ortim.main` directly rather than
    relying on env var propagation."""
    with tempfile.TemporaryDirectory() as tmp:
        ws_root = Path(tmp) / "workspaces"
        monkeypatch.setattr("ortim.main.WORKSPACE_ROOT", ws_root)
        monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test-stub")
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

        class _Result:
            returncode = 1

        with patch("subprocess.run", return_value=_Result()):
            result = _runner().invoke(
                app, ["demo", "--brief", "test brief"],
                catch_exceptions=False,
            )

        assert result.exit_code == 1
        assert ws_root.exists()
        candidates = [p for p in ws_root.iterdir() if p.is_dir()]
        assert len(candidates) == 1
        project = Project.load(candidates[0].name, ws_root)
        assert project.name.startswith("demo-")
        assert project.initial_brief_tr == "test brief"


def test_demo_chain_uses_project_flag_for_advance_and_execute(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """0.9.0 moved `advance` and `execute` to a 1-positional + `--project`
    flag signature. Demo spawns subprocesses against the same CLI surface,
    so it must use the flag form — passing the workspace id as a second
    positional makes typer raise `Got unexpected extra argument`.

    Capture the args every subprocess call would have received and assert
    each `advance`/`execute` invocation carries `--project` (not a bare
    positional UUID after the state/task argument)."""
    captured: list[list[str]] = []

    class _Result:
        returncode = 0

    def _capture(args: list[str], **kwargs: object) -> _Result:
        captured.append(list(args))
        return _Result()

    with tempfile.TemporaryDirectory() as tmp:
        ws_root = Path(tmp) / "workspaces"
        monkeypatch.setattr("ortim.main.WORKSPACE_ROOT", ws_root)
        monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test-stub")
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

        with patch("subprocess.run", side_effect=_capture):
            _runner().invoke(
                app, ["demo", "--brief", "x", "--execute"],
                catch_exceptions=False,
            )

    # Pull out the command name (first token after `-m ortim.main`).
    def _command(call: list[str]) -> str:
        # call looks like [sys.executable, "-m", "ortim.main", <cmd>, ...]
        for i, tok in enumerate(call):
            if tok == "ortim.main" and i + 1 < len(call):
                return call[i + 1]
        return ""

    advance_calls = [c for c in captured if _command(c) == "advance"]
    execute_calls = [c for c in captured if _command(c) == "execute"]

    assert advance_calls, "demo chain must include advance steps"
    assert execute_calls, "demo chain with --execute must include execute step"

    for c in advance_calls + execute_calls:
        assert "--project" in c, (
            f"chain call missing --project flag (would fail typer parse): {c}"
        )


def test_demo_restores_dialog_mode_env_var(monkeypatch: pytest.MonkeyPatch) -> None:
    """Demo sets `ORTIM_DIALOG_MODE=off` for its own run; if the
    operator had set it to `on` before, the original value must be
    restored on exit. Otherwise running `demo` inside an interactive
    shell would silently disable dialog mode for every subsequent
    command in that shell session."""
    with tempfile.TemporaryDirectory() as tmp:
        ws_root = Path(tmp) / "workspaces"
        monkeypatch.setattr("ortim.main.WORKSPACE_ROOT", ws_root)
        monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test-stub")
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.setenv("ORTIM_DIALOG_MODE", "on")

        class _Result:
            returncode = 1

        with patch("subprocess.run", return_value=_Result()):
            _runner().invoke(
                app, ["demo", "--brief", "x"],
                catch_exceptions=False,
            )

        # finally-block restored the marker rather than leaving it at
        # 'off' (which the demo had set internally).
        assert os.environ.get("ORTIM_DIALOG_MODE") == "on"
