# SPDX-License-Identifier: FSL-1.1-Apache-2.0
# Copyright (c) 2026 ortim.dev
"""Tests for the AI_FACTORY_* → ORTIM_* env-var compatibility shim.

Locks the contract for R7 cleanup: when shim is removed, these tests
should be the canary that flags any code path still relying on legacy
names.
"""

from __future__ import annotations

import os

from ortim.env import env_get, reset_deprecation_warnings


def test_new_name_wins_over_legacy(monkeypatch) -> None:
    monkeypatch.setenv("ORTIM_TEST_VAR", "new-value")
    monkeypatch.setenv("AI_FACTORY_TEST_VAR", "legacy-value")
    assert env_get("ORTIM_TEST_VAR") == "new-value"


def test_legacy_name_used_when_new_unset(monkeypatch) -> None:
    monkeypatch.delenv("ORTIM_TEST_VAR", raising=False)
    monkeypatch.setenv("AI_FACTORY_TEST_VAR", "legacy-value")
    reset_deprecation_warnings()
    assert env_get("ORTIM_TEST_VAR") == "legacy-value"


def test_default_returned_when_both_unset(monkeypatch) -> None:
    monkeypatch.delenv("ORTIM_TEST_VAR", raising=False)
    monkeypatch.delenv("AI_FACTORY_TEST_VAR", raising=False)
    assert env_get("ORTIM_TEST_VAR", "fallback") == "fallback"
    assert env_get("ORTIM_TEST_VAR") is None


def test_legacy_fallback_emits_deprecation_warning_once(monkeypatch, capsys) -> None:
    monkeypatch.delenv("ORTIM_DEPREC_TEST", raising=False)
    monkeypatch.setenv("AI_FACTORY_DEPREC_TEST", "x")
    reset_deprecation_warnings()

    env_get("ORTIM_DEPREC_TEST")
    env_get("ORTIM_DEPREC_TEST")  # second read should not double-warn

    captured = capsys.readouterr()
    occurrences = captured.err.count("AI_FACTORY_DEPREC_TEST is deprecated")
    assert occurrences == 1, captured.err


def test_test_runner_reads_legacy_env_file(tmp_path, monkeypatch) -> None:
    """Workspace `.ai-factory.env` file is still consulted as fallback
    when `.ortim.env` is missing — covers users with legacy bootstrap
    output sitting in their workspaces."""
    from ortim.executor.test_runner import _read_workspace_test_cmd

    monkeypatch.delenv("ORTIM_TEST_CMD", raising=False)
    monkeypatch.delenv("AI_FACTORY_TEST_CMD", raising=False)

    (tmp_path / ".ai-factory.env").write_text(
        'AI_FACTORY_TEST_CMD="legacy-runner -q"\n', encoding="utf-8"
    )
    cmd, source = _read_workspace_test_cmd(tmp_path)
    assert cmd == "legacy-runner -q"
    assert source == ".ai-factory.env"


def test_test_runner_prefers_new_env_file(tmp_path, monkeypatch) -> None:
    """When both `.ortim.env` and `.ai-factory.env` exist, the new file
    wins."""
    from ortim.executor.test_runner import _read_workspace_test_cmd

    monkeypatch.delenv("ORTIM_TEST_CMD", raising=False)
    monkeypatch.delenv("AI_FACTORY_TEST_CMD", raising=False)

    (tmp_path / ".ortim.env").write_text(
        'ORTIM_TEST_CMD="new-runner -q"\n', encoding="utf-8"
    )
    (tmp_path / ".ai-factory.env").write_text(
        'AI_FACTORY_TEST_CMD="legacy-runner -q"\n', encoding="utf-8"
    )
    cmd, source = _read_workspace_test_cmd(tmp_path)
    assert cmd == "new-runner -q"
    assert source == ".ortim.env"


def test_test_runner_reads_new_key_from_legacy_filename(tmp_path, monkeypatch) -> None:
    """A user manually renamed the file but kept the legacy key — the
    file content's preferred key still wins over the legacy key in the
    same file."""
    from ortim.executor.test_runner import _read_workspace_test_cmd

    monkeypatch.delenv("ORTIM_TEST_CMD", raising=False)
    monkeypatch.delenv("AI_FACTORY_TEST_CMD", raising=False)

    (tmp_path / ".ai-factory.env").write_text(
        'ORTIM_TEST_CMD="from-new-key"\n'
        'AI_FACTORY_TEST_CMD="from-legacy-key"\n',
        encoding="utf-8",
    )
    cmd, source = _read_workspace_test_cmd(tmp_path)
    assert cmd == "from-new-key"
    assert source == ".ai-factory.env"


def test_unrelated_env_name_returns_none_without_warning(monkeypatch, capsys) -> None:
    """env_get for a name that doesn't have the ORTIM_ prefix returns
    None and doesn't warn — it's not part of the shim contract."""
    monkeypatch.delenv("SOME_OTHER_VAR", raising=False)
    reset_deprecation_warnings()
    assert env_get("SOME_OTHER_VAR") is None
    captured = capsys.readouterr()
    assert "deprecated" not in captured.err
    # And clearly no env_get reads of a non-prefixed name should pick
    # up "AI_FACTORY_SOME_OTHER_VAR" via accidental string surgery.
    os.environ["AI_FACTORY_SOME_OTHER_VAR"] = "leaky"
    try:
        assert env_get("SOME_OTHER_VAR") is None
    finally:
        os.environ.pop("AI_FACTORY_SOME_OTHER_VAR", None)
