# SPDX-License-Identifier: FSL-1.1-Apache-2.0
# Copyright (c) 2026 ortim.dev
"""Tests for ortim.scope — Faz 1.1 ScopeManifest schema + helpers."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from ortim.scope import (  # noqa: E402
    ScopeManifest,
    ScopedFeature,
    load_scope,
    save_scope,
    suggest_initial_scope,
)
from ortim.scope.schema import scope_path  # noqa: E402


def test_suggest_initial_scope_maps_must_to_phase_1_and_nice_to_phase_2() -> None:
    m = suggest_initial_scope(
        project_id="abc123",
        must_have_features=["task creation", "task listing"],
        nice_to_have_features=["tagging"],
    )
    assert len(m.features) == 3
    by_desc = {f.description: f for f in m.features}
    assert by_desc["task creation"].phase == 1
    assert by_desc["task creation"].priority == "must"
    assert by_desc["task creation"].source == "intent"
    assert by_desc["tagging"].phase == 2
    assert by_desc["tagging"].priority == "later"
    assert m.locked_at is None
    assert m.max_phase() == 2


def test_phase_1_and_deferred_partition() -> None:
    m = suggest_initial_scope(
        project_id="p",
        must_have_features=["a", "b"],
        nice_to_have_features=["c"],
    )
    assert {f.description for f in m.phase_1_features()} == {"a", "b"}
    assert {f.description for f in m.deferred_features()} == {"c"}


def test_lock_stamps_iso_timestamp_once() -> None:
    m = ScopeManifest(project_id="x", features=[])
    assert m.locked_at is None
    m.lock()
    first = m.locked_at
    assert first is not None
    m.lock()
    assert m.locked_at == first


def test_phase_must_be_positive() -> None:
    with pytest.raises(ValueError):
        ScopedFeature(description="foo", phase=0)
    with pytest.raises(ValueError):
        ScopedFeature(description="foo", phase=-1)


def test_description_must_be_nonblank() -> None:
    with pytest.raises(ValueError):
        ScopedFeature(description="   ")


def test_to_prompt_block_groups_phase_2_under_deferred() -> None:
    m = suggest_initial_scope(
        project_id="p",
        must_have_features=["login"],
        nice_to_have_features=["social"],
    )
    block = m.to_prompt_block()
    assert "Phase 1 (MVP)" in block
    assert "Deferred" in block
    assert "[P2] social" in block
    assert "- login" in block


def test_to_prompt_block_omits_deferred_section_when_empty() -> None:
    m = suggest_initial_scope(
        project_id="p",
        must_have_features=["login"],
        nice_to_have_features=[],
    )
    block = m.to_prompt_block()
    assert "Phase 1 (MVP)" in block
    assert "Deferred" not in block


def test_to_prompt_block_empty_when_no_features() -> None:
    m = ScopeManifest(project_id="p", features=[])
    assert "no features scoped" in m.to_prompt_block()


def test_save_and_load_roundtrip_preserves_lock_state() -> None:
    with tempfile.TemporaryDirectory() as td:
        ws = Path(td)
        m = suggest_initial_scope(
            project_id="p", must_have_features=["a"], nice_to_have_features=[]
        )
        m.lock()
        save_scope(ws, m)
        assert scope_path(ws).exists()

        reloaded = load_scope(ws)
        assert reloaded.locked_at == m.locked_at
        assert len(reloaded.features) == 1
        assert reloaded.features[0].description == "a"


def test_load_scope_missing_raises_file_not_found() -> None:
    with tempfile.TemporaryDirectory() as td:
        with pytest.raises(FileNotFoundError):
            load_scope(Path(td))


def test_manual_features_keep_source_tag() -> None:
    """Auto-suggested features are tagged source=intent; the CLI may
    append manual features later — those must keep source=manual."""
    f = ScopedFeature(description="ad hoc", source="manual")
    assert f.source == "manual"
