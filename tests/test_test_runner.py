# SPDX-License-Identifier: FSL-1.1-Apache-2.0
# Copyright (c) 2026 ortim.dev
"""Tests for runtime.executor.test_runner.configured_plan workspace fallback.

Phase 0 (9c) introduces a workspace-scoped fallback: if `AI_FACTORY_TEST_CMD`
is not set as an env var, but a `.ai-factory.env` file exists in the
workspace root and defines `AI_FACTORY_TEST_CMD`, that value is used.

Together with bootstrap auto-writing `.ai-factory.env` at scaffold time,
this closes the silent-skip loophole: a freshly bootstrapped T2/web project
runs `vitest` even if the user never exports the env var.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from runtime.executor.test_runner import configured_plan


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AI_FACTORY_TEST_CMD", raising=False)
    monkeypatch.delenv("AI_FACTORY_TESTS_ENABLED", raising=False)


def test_env_var_wins_over_workspace_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / ".ai-factory.env").write_text(
        'AI_FACTORY_TEST_CMD="from-file"\n', encoding="utf-8"
    )
    monkeypatch.setenv("AI_FACTORY_TEST_CMD", "from-env")
    plan = configured_plan(tmp_path)
    assert plan is not None
    assert plan.cmd == ["from-env"]
    assert "AI_FACTORY_TEST_CMD" in plan.rationale


def test_workspace_file_used_when_env_unset(tmp_path: Path) -> None:
    (tmp_path / ".ai-factory.env").write_text(
        'AI_FACTORY_TEST_CMD="npx vitest run"\n', encoding="utf-8"
    )
    plan = configured_plan(tmp_path)
    assert plan is not None
    assert plan.cmd == ["npx", "vitest", "run"]
    assert ".ai-factory.env" in plan.rationale


def test_no_env_no_file_returns_none(tmp_path: Path) -> None:
    plan = configured_plan(tmp_path)
    assert plan is None


def test_workspace_file_missing_key_returns_none(tmp_path: Path) -> None:
    (tmp_path / ".ai-factory.env").write_text(
        "# only comments and unrelated keys\nFOO=bar\n", encoding="utf-8"
    )
    plan = configured_plan(tmp_path)
    assert plan is None


def test_workspace_file_handles_quoted_values(tmp_path: Path) -> None:
    (tmp_path / ".ai-factory.env").write_text(
        "AI_FACTORY_TEST_CMD='pytest -q'\n", encoding="utf-8"
    )
    plan = configured_plan(tmp_path)
    assert plan is not None
    assert plan.cmd == ["pytest", "-q"]


def test_disabled_via_env_overrides_everything(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / ".ai-factory.env").write_text(
        'AI_FACTORY_TEST_CMD="vitest"\n', encoding="utf-8"
    )
    monkeypatch.setenv("AI_FACTORY_TESTS_ENABLED", "false")
    assert configured_plan(tmp_path) is None
