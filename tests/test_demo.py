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


def test_demo_falls_back_to_recorded_replay_when_no_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No credential + no explicit --provider → the demo must NOT abort;
    it switches to the replay provider (recorded run) with a visible
    badge, and pins every role to replay for the subprocess chain so an
    operator's ARCHITECT_PROVIDER etc. can't punch through to a live
    endpoint mid-replay. This is the `pip install ortim && ortim demo`
    keyless activation path."""
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("LLM_PROVIDER", "anthropic")
    monkeypatch.setenv("ARCHITECT_PROVIDER", "deepseek")

    seen_env: list[dict[str, str]] = []

    class _Result:
        returncode = 1  # short-circuit after the first chain step

    def _capture(args: list[str], **kwargs: object) -> _Result:
        seen_env.append(dict(os.environ))
        return _Result()

    with tempfile.TemporaryDirectory() as tmp:
        ws_root = Path(tmp) / "workspaces"
        monkeypatch.setattr("ortim.cli._globals.WORKSPACE_ROOT", ws_root)
        with patch("subprocess.run", side_effect=_capture):
            result = _runner().invoke(app, ["demo"], catch_exceptions=False)

    assert "Recorded demo" in result.stdout
    assert "is not set" not in result.stdout
    assert seen_env, "chain did not start — replay fallback aborted early"
    assert seen_env[0]["LLM_PROVIDER"] == "replay"
    assert seen_env[0]["ARCHITECT_PROVIDER"] == "replay"
    assert "ORTIM_REPLAY_STATE" in seen_env[0]
    # finally-block restored the operator's env after the run.
    assert os.environ.get("LLM_PROVIDER") == "anthropic"
    assert os.environ.get("ARCHITECT_PROVIDER") == "deepseek"


def test_demo_hard_errors_when_explicit_provider_has_no_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`--provider deepseek` without DEEPSEEK_API_KEY stays a hard error —
    silently swapping an explicitly requested provider for the recording
    would misrepresent what ran."""
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    result = _runner().invoke(
        app, ["demo", "--provider", "deepseek"], catch_exceptions=False
    )
    assert result.exit_code == 1
    assert "DEEPSEEK_API_KEY is not set" in result.stdout
    assert "ortim config init" in result.stdout


def test_demo_keyless_custom_brief_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The recording only covers the default brief — replaying it against
    a different brief would show answers to a question the user didn't
    ask. Clear error instead."""
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("LLM_PROVIDER", "anthropic")
    result = _runner().invoke(
        app, ["demo", "--brief", "build a chat app"], catch_exceptions=False
    )
    assert result.exit_code == 1
    assert "default brief" in result.stdout


def test_demo_keyless_execute_downgrades_to_planning_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """--execute without a key: warn + run the planning replay rather
    than aborting or replaying an execution that wasn't recorded."""
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("LLM_PROVIDER", "anthropic")

    captured: list[list[str]] = []

    class _Result:
        returncode = 0

    def _capture(args: list[str], **kwargs: object) -> _Result:
        captured.append(list(args))
        return _Result()

    with tempfile.TemporaryDirectory() as tmp:
        ws_root = Path(tmp) / "workspaces"
        monkeypatch.setattr("ortim.cli._globals.WORKSPACE_ROOT", ws_root)
        with patch("subprocess.run", side_effect=_capture):
            result = _runner().invoke(
                app, ["demo", "--execute"], catch_exceptions=False
            )

    assert result.exit_code == 0
    assert "planning chain only" in result.stdout
    assert captured, "planning chain should still run"
    assert not any("execute" in c for c in captured)
    assert "recorded run" in result.stdout


def test_demo_passes_when_provider_needs_no_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`--provider ollama` (local, key-free) must bypass the key
    pre-flight. Otherwise a PyPI user with no Anthropic/DeepSeek
    account cannot try the demo at all."""
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with tempfile.TemporaryDirectory() as tmp:
        ws_root = Path(tmp) / "workspaces"
        monkeypatch.setattr("ortim.cli._globals.WORKSPACE_ROOT", ws_root)

        class _Result:
            returncode = 1  # short-circuit the subprocess chain

        with patch("subprocess.run", return_value=_Result()):
            result = _runner().invoke(
                app, ["demo", "--brief", "x", "--provider", "ollama"],
                catch_exceptions=False,
            )

        # Assert INSIDE the `with` so the tmpdir hasn't been cleaned up.
        # We care that the pre-flight did NOT abort with a key error —
        # the abort path returns before `_ensure_workspace_root()` runs,
        # so a missing ws_root indicates a false-positive key block.
        assert ws_root.exists(), (
            f"ws_root not created; demo aborted early. "
            f"stdout=\n{result.stdout}"
        )
        assert "is not set" not in result.stdout


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
        monkeypatch.setattr("ortim.cli._globals.WORKSPACE_ROOT", ws_root)
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
        monkeypatch.setattr("ortim.cli._globals.WORKSPACE_ROOT", ws_root)
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
        monkeypatch.setattr("ortim.cli._globals.WORKSPACE_ROOT", ws_root)
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
