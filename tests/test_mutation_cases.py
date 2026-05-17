# SPDX-License-Identifier: FSL-1.1-Apache-2.0
# Copyright (c) 2026 ortim.dev
"""Mutation case sanity tests — every shipped case has the required
fields populated, original ≠ mutated, and bug_keywords non-empty so
the strict scorer has something to look for."""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from ortim.mutation import DEFAULT_CASES  # noqa: E402


def test_default_cases_cover_six_bug_classes() -> None:
    """One case per bug class — keeps the catch-rate report rows
    interpretable. Adding new cases is fine but the bug_class taxonomy
    stays the canonical reporting axis."""
    classes = {c.bug_class for c in DEFAULT_CASES}
    assert classes == {
        "off-by-one",
        "null-check-removed",
        "auth-bypass",
        "sql-injection",
        "missing-await",
        "wrong-operator",
    }


def test_every_case_has_distinct_original_and_mutated() -> None:
    """A case where original == mutated would produce a meaningless
    catch rate (the Reviewer is reviewing correct code)."""
    for case in DEFAULT_CASES:
        assert case.original_code != case.mutated_code, (
            f"{case.bug_class}/{case.name} has identical original and mutated"
        )


def test_every_case_has_non_empty_bug_keywords() -> None:
    """The strict scorer needs at least one keyword per case."""
    for case in DEFAULT_CASES:
        assert case.bug_keywords, (
            f"{case.bug_class}/{case.name} has no bug_keywords"
        )


def test_every_case_has_at_least_two_acceptance_criteria() -> None:
    """Single-criterion cases produce a degenerate verdict shape and
    don't exercise the rubric the Reviewer was hardened against (Item
    21 length validation). All shipped cases must carry ≥ 2."""
    for case in DEFAULT_CASES:
        assert len(case.acceptance_criteria) >= 2, (
            f"{case.bug_class}/{case.name} has fewer than 2 criteria"
        )


def test_every_case_has_required_string_fields_non_empty() -> None:
    for case in DEFAULT_CASES:
        for fname in (
            "name", "language", "task_title", "task_description",
            "module_scope", "rfc_section", "rfc_excerpt", "file_path",
            "original_code", "mutated_code",
        ):
            value = getattr(case, fname)
            assert isinstance(value, str) and value.strip(), (
                f"{case.bug_class}/{case.name}.{fname} is empty or non-string"
            )


def test_file_path_is_inside_module_scope() -> None:
    """The mutated file must live under module_scope so the Reviewer's
    sandbox-shaped checks don't flag scope violation BEFORE the bug
    check fires. The catch rate must reflect bug detection, not scope."""
    for case in DEFAULT_CASES:
        assert case.file_path.startswith(f"{case.module_scope}/"), (
            f"{case.bug_class}/{case.name}: file_path={case.file_path!r} "
            f"not under module_scope={case.module_scope!r}"
        )
