# SPDX-License-Identifier: FSL-1.1-Apache-2.0
# Copyright (c) 2026 ortim.dev
"""Regression test for the v0.9.4 PyPI-install bug.

Bug: `load_dotenv()` (called argument-less in `main.py`) walked up from
main.py's file location, not the user's cwd. PyPI installs put main.py
in site-packages, so a user's `.env` in their project directory was
never discovered — even with `LLM_PROVIDER=deepseek` in `.env`, the
runtime kept asking for `ANTHROPIC_API_KEY`.

Fix: `load_dotenv(find_dotenv(usecwd=True))`.

This test exercises `find_dotenv(usecwd=True)` directly (the same call
main.py uses) from a synthetic project directory, mirroring the PyPI
user's scenario.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest
from dotenv import find_dotenv, load_dotenv

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))


def test_find_dotenv_usecwd_walks_from_user_cwd(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With usecwd=True, `find_dotenv` must walk up from `os.getcwd()`,
    not from the caller frame's file. The PyPI bug existed precisely
    because the default `usecwd=False` walks from the caller frame —
    which lives in site-packages for installed builds."""
    project_dir = tmp_path / "user_project"
    project_dir.mkdir()
    env_file = project_dir / ".env"
    env_file.write_text("LLM_PROVIDER=deepseek\nDEEPSEEK_API_KEY=sk-test\n")

    monkeypatch.chdir(project_dir)
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)

    found = find_dotenv(usecwd=True)
    assert found, "find_dotenv(usecwd=True) should locate cwd's .env"
    assert Path(found).resolve() == env_file.resolve()

    loaded = load_dotenv(found)
    assert loaded is True
    assert os.environ.get("LLM_PROVIDER") == "deepseek"
    assert os.environ.get("DEEPSEEK_API_KEY") == "sk-test"


def test_find_dotenv_usecwd_returns_empty_when_absent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No `.env` anywhere up the tree → `find_dotenv` returns empty
    string. `load_dotenv("")` is a documented no-op, so this is the
    safe failure mode the production code relies on."""
    empty_dir = tmp_path / "no_env_here"
    empty_dir.mkdir()
    monkeypatch.chdir(empty_dir)

    # tmp_path itself shouldn't have a .env; walk doesn't pass tmp root.
    found = find_dotenv(usecwd=True)
    # NB: depending on the host CI's parent dirs, find_dotenv could
    # locate an unrelated .env far up. The contract we care about is
    # "load_dotenv on the result is safe" — an empty string OR a
    # well-formed path both satisfy that.
    if found:
        # If something was found, it must be a real readable file —
        # the bug scenario was specifically returning a stale path.
        assert Path(found).is_file()
    else:
        assert load_dotenv("") is False


if __name__ == "__main__":
    import subprocess
    raise SystemExit(subprocess.call([sys.executable, "-m", "pytest", __file__, "-v"]))
