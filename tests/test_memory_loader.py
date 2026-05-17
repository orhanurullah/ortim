# SPDX-License-Identifier: FSL-1.1-Apache-2.0
# Copyright (c) 2026 ortim.dev
"""Tests memory loader can read all the docs we wrote."""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from ortim.memory import MemoryLoader  # noqa: E402


def test_l1_principles_loads_and_is_nontrivial() -> None:
    ml = MemoryLoader(REPO_ROOT)
    text = ml.load_l1_principles()
    assert len(text) > 500, "L1 principles seem empty or too short"
    assert "Dependency Injection" in text


def test_glossary_loads() -> None:
    ml = MemoryLoader(REPO_ROOT)
    text = ml.load_glossary()
    assert "KVKK" in text


def test_prd_template_loads() -> None:
    ml = MemoryLoader(REPO_ROOT)
    text = ml.load_template("PRD")
    assert "Acceptance Criteria" in text


def test_rfc_template_loads() -> None:
    ml = MemoryLoader(REPO_ROOT)
    text = ml.load_template("RFC")
    assert "Golden Path" in text


def test_task_template_loads() -> None:
    ml = MemoryLoader(REPO_ROOT)
    text = ml.load_template("Task")
    assert "Worker Constraints" in text


def test_babel_agent_prompt_loads() -> None:
    ml = MemoryLoader(REPO_ROOT)
    text = ml.load_agent_prompt("babel")
    assert "StructuredIntent" in text


def test_analyst_agent_prompt_loads() -> None:
    ml = MemoryLoader(REPO_ROOT)
    text = ml.load_agent_prompt("analyst")
    assert "PRD" in text


def test_unknown_template_raises() -> None:
    ml = MemoryLoader(REPO_ROOT)
    try:
        ml.load_template("DoesNotExist")
    except FileNotFoundError:
        return
    raise AssertionError("Expected FileNotFoundError")


if __name__ == "__main__":
    tests = [
        test_l1_principles_loads_and_is_nontrivial,
        test_glossary_loads,
        test_prd_template_loads,
        test_rfc_template_loads,
        test_task_template_loads,
        test_babel_agent_prompt_loads,
        test_analyst_agent_prompt_loads,
        test_unknown_template_raises,
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
