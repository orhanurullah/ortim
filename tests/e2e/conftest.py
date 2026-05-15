# SPDX-License-Identifier: FSL-1.1-Apache-2.0
# Copyright (c) 2026 ortim.dev
"""Shared E2E fixture helpers.

Tests in this package are marked `@pytest.mark.e2e` and excluded from the
default run via `addopts = ["-m", "not e2e"]` in pyproject.toml. Run them
explicitly with `pytest -m e2e`.

Fixtures are frozen artifacts captured from real-LLM proof-point runs.
They live under `tests/e2e/fixtures/<workspace-id>/` and are loaded via
the `fixture_dir` helper. The aim is regression armor: a change that
silently alters the planning chain's output shape or the DAG's
structural invariants should make these tests fail loudly, not slip
through unit tests that only see synthetic inputs.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

E2E_ROOT = Path(__file__).resolve().parent
FIXTURES_ROOT = E2E_ROOT / "fixtures"
REPO_ROOT = E2E_ROOT.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def fixture_dir(name: str) -> Path:
    path = FIXTURES_ROOT / name
    if not path.exists():
        raise FileNotFoundError(
            f"E2E fixture '{name}' not found at {path}. Use "
            f"`scripts/record_e2e_fixture.py <workspace-id> <fixture-name>` "
            f"to record it from a live workspace."
        )
    return path


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


@pytest.fixture
def proofpoint48() -> Path:
    return fixture_dir("proofpoint48")


@pytest.fixture
def cli_greenfield() -> Path:
    """Pre-M2 greenfield CLI baseline (no stack.json)."""
    return fixture_dir("b8d60b6f5791")


@pytest.fixture
def pre_item48_extend() -> Path:
    """Pre-Item-48 extend cycle. Task count is the un-aggregated 16 (6
    baseline + 10 delta) — kept as a historical snapshot, NOT a
    correctness target. Tests on this fixture validate schema integrity
    and parser compatibility, not the over-granularization itself."""
    return fixture_dir("1b9c9f9ca18b")
