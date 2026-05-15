# SPDX-License-Identifier: FSL-1.1-Apache-2.0
# Copyright (c) 2026 ortim.dev
"""M3.1.0d — delta_writer.append_delta_section + section_cycles_in.

Idempotency is the load-bearing property: re-running `ortim extend` for
the same cycle (e.g. after a transient LLM error) must not duplicate the
section in PRD.md / RFC.md.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from runtime.extend import (  # noqa: E402
    DeltaSectionMalformed,
    append_delta_section,
    section_cycles_in,
)


# ---- section_cycles_in ----


def test_section_cycles_in_empty_text() -> None:
    assert section_cycles_in("") == []


def test_section_cycles_in_finds_one_cycle() -> None:
    text = "# PRD\n\n## 1. Problem\n...\n\n## Extension 1 — Tagging\n..."
    assert section_cycles_in(text) == [1]


def test_section_cycles_in_finds_multiple_in_order() -> None:
    text = (
        "# PRD\n\n"
        "## 1. Problem\n...\n\n"
        "## Extension 1 — Tagging\n...\n\n"
        "## Extension 2 — Due dates\n...\n\n"
        "## Extension 5 — Bulk delete\n..."  # gap is OK
    )
    assert section_cycles_in(text) == [1, 2, 5]


def test_section_cycles_in_accepts_dash_variants() -> None:
    """LLM may use em-dash, hyphen, or colon after the cycle integer.
    Header detection must be lenient on the separator."""
    em = "## Extension 1 — Tagging\n..."
    hy = "## Extension 2 - Due dates\n..."
    co = "## Extension 3: Bulk delete\n..."
    # Even no separator is acceptable when the agent omits the title.
    bare = "## Extension 4\n..."
    assert section_cycles_in(em + "\n" + hy + "\n" + co + "\n" + bare) == [
        1, 2, 3, 4
    ]


def test_section_cycles_in_ignores_h3_extension_subsections() -> None:
    """Only H2 `## Extension N` headers count. An H3 `### Extension 1`
    nested inside is a sub-section, not a cycle marker."""
    text = (
        "## Extension 1 — Tagging\n\n"
        "### Extension 1 sub-rationale\n..."
    )
    assert section_cycles_in(text) == [1]


# ---- append_delta_section idempotency + validation ----


def _write(tmp_path: Path, name: str, content: str) -> Path:
    p = tmp_path / name
    p.write_text(content, encoding="utf-8")
    return p


def test_append_delta_section_writes_new_cycle(tmp_path: Path) -> None:
    target = _write(tmp_path, "PRD.md", "# PRD\n\n## 1. Problem\nUsers need todos.\n")
    section = "## Extension 1 — Tagging\n\n### Goal\nAdd tags.\n"
    written = append_delta_section(target, section, cycle=1)
    assert written is True
    final = target.read_text(encoding="utf-8")
    assert "Extension 1 — Tagging" in final
    assert "## 1. Problem" in final  # original preserved
    assert section_cycles_in(final) == [1]


def test_append_delta_section_idempotent_for_same_cycle(tmp_path: Path) -> None:
    """Second call with same cycle is a no-op. Critical: the section
    text BODY may differ between calls (e.g. agent retried with different
    output) but the cycle integer is the de-dupe key."""
    target = _write(tmp_path, "PRD.md", "# PRD\n\n## 1. Problem\n...\n")
    s1 = "## Extension 1 — Tagging\n\n### Goal\nAdd tags.\n"
    s2 = "## Extension 1 — Tagging\n\n### Goal\nAdd tags v2 — different text.\n"

    assert append_delta_section(target, s1, cycle=1) is True
    assert append_delta_section(target, s2, cycle=1) is False

    final = target.read_text(encoding="utf-8")
    # Original section content preserved (the second call did not
    # overwrite); cycle still appears exactly once.
    assert section_cycles_in(final) == [1]
    assert "Add tags." in final
    assert "v2 — different text" not in final


def test_append_delta_section_accepts_multiple_distinct_cycles(
    tmp_path: Path,
) -> None:
    """Each new cycle appends; cycles 1, 2, 3 should all coexist."""
    target = _write(tmp_path, "PRD.md", "# PRD\n\n## 1. Problem\n...\n")
    for n in (1, 2, 3):
        section = f"## Extension {n} — Feature {n}\n\n### Goal\n...\n"
        assert append_delta_section(target, section, cycle=n) is True

    final = target.read_text(encoding="utf-8")
    assert section_cycles_in(final) == [1, 2, 3]


def test_append_delta_section_rejects_missing_header(tmp_path: Path) -> None:
    target = _write(tmp_path, "PRD.md", "# PRD\n\n## 1. Problem\n...\n")
    with pytest.raises(DeltaSectionMalformed):
        append_delta_section(target, "Just some prose, no header.\n", cycle=1)


def test_append_delta_section_rejects_cycle_mismatch(tmp_path: Path) -> None:
    """Section header declares cycle 2 but caller said cycle 1 — that
    discrepancy is a Worker/runtime bug. Fail loud rather than write a
    section under the wrong cycle marker."""
    target = _write(tmp_path, "PRD.md", "# PRD\n\n## 1. Problem\n...\n")
    section = "## Extension 2 — Wrong cycle\n\n### Goal\n...\n"
    with pytest.raises(DeltaSectionMalformed):
        append_delta_section(target, section, cycle=1)


def test_append_delta_section_raises_when_target_missing(tmp_path: Path) -> None:
    """Extending a project whose PRD/RFC doesn't exist is a runtime bug
    (the project state machine would block this anyway). Surface the
    error rather than silently creating a stub file."""
    section = "## Extension 1 — Tagging\n\n### Goal\n...\n"
    with pytest.raises(FileNotFoundError):
        append_delta_section(tmp_path / "missing.md", section, cycle=1)


def test_append_delta_section_handles_no_trailing_newline(tmp_path: Path) -> None:
    """Existing file may or may not end with newline; appended section
    must always be separated by a blank line and end with newline."""
    target = tmp_path / "PRD.md"
    target.write_text("# PRD\nNo trailing newline", encoding="utf-8")
    section = "## Extension 1 — Tagging\n\n### Goal\n...\n"
    assert append_delta_section(target, section, cycle=1) is True
    final = target.read_text(encoding="utf-8")
    assert final.endswith("\n")
    assert "trailing newline\n\n## Extension 1" in final
