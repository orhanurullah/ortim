# SPDX-License-Identifier: FSL-1.1-Apache-2.0
# Copyright (c) 2026 ortim.dev
"""Schema for mutation testing — `MutationCase` and result records.

A mutation case is a hand-crafted pair of (correct, buggy) code for a
specific bug class. The `mutated_code` is fed to the Reviewer as if a
Worker had emitted it; the Reviewer's job is to mark the task NOT
approved and ideally name the bug. The original is kept for reference
and for the docs / report renderer to diff against.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

# Bug class taxonomy. New entries are allowed; this list is the
# canonical reporting axis. Keep it short and orthogonal so the catch
# rate per class stays interpretable.
BugClass = Literal[
    "off-by-one",
    "null-check-removed",
    "auth-bypass",
    "sql-injection",
    "missing-await",
    "wrong-operator",
]


@dataclass(frozen=True)
class MutationCase:
    """One mutation case.

    Fields are deliberately flat — a case slots directly into the
    Reviewer's call shape (TaskSpec + WorkerOutput) at runtime without
    extra translation. `bug_keywords` is what the strict scorer scans
    for in the verdict's evidence + code_quote text; lowercase
    substring match.
    """

    name: str
    """Unique within a bug class. Used in the report row."""

    bug_class: BugClass
    language: str
    """Free-form ("Python", "TypeScript"); informational, not enforced."""

    task_title: str
    task_description: str
    module_scope: str
    acceptance_criteria: list[str]
    rfc_section: str
    rfc_excerpt: str

    file_path: str
    """Path the mutated code is presented at. Should sit inside
    `module_scope` so the Reviewer's scope check doesn't flag it before
    the bug check runs."""

    original_code: str
    """Correct version — never sent to the Reviewer, used by the
    report renderer for the side-by-side diff."""

    mutated_code: str
    """The buggy version. Sent to the Reviewer as `worker_output.files[0].content`."""

    bug_keywords: list[str]
    """Phrases the Reviewer's verdict should mention to count as a
    STRICT catch (loose catch is just `approved=False`). Case-insensitive
    substring match against criteria_verdicts' evidence + code_quote +
    l1_violations."""


@dataclass(frozen=True)
class CatchResult:
    """Outcome of running one mutation case through the Reviewer."""

    case_name: str
    bug_class: str
    caught_loose: bool
    """True iff `verdict.approved is False`."""

    caught_strict: bool
    """True iff loose-caught AND evidence references at least one
    `bug_keyword`. False when loose=False (a strict catch implies a
    loose catch)."""

    verdict_summary: str
    """Short human-readable summary of the verdict — what status counts
    appeared, top reason text. Useful for log + report. Not the full
    verdict (which can be large)."""

    error: str | None = None
    """Populated when the Reviewer call raised. Both caught flags are
    False in that case — an exception is not a successful catch."""


@dataclass(frozen=True)
class CatchRateReport:
    """Aggregate over a mutation run."""

    total: int
    caught_loose: int
    caught_strict: int
    errors: int
    per_class: dict[str, tuple[int, int, int, int]]
    """Map bug_class → (caught_loose, caught_strict, errors, total).
    Order matches the dict insertion order: same as DEFAULT_CASES."""

    cases: list[CatchResult] = field(default_factory=list)

    @property
    def loose_rate(self) -> float:
        return self.caught_loose / self.total if self.total else 0.0

    @property
    def strict_rate(self) -> float:
        return self.caught_strict / self.total if self.total else 0.0

    @property
    def error_rate(self) -> float:
        return self.errors / self.total if self.total else 0.0

    def render(self) -> str:
        """One-block textual rendering for CLI / docs / commit message."""
        if not self.total:
            return "Mutation report: no cases run."
        lines = [
            f"Mutation report — {self.total} cases",
            f"  Caught (loose): {self.caught_loose}/{self.total} "
            f"({self.loose_rate:.0%})",
            f"  Caught (strict): {self.caught_strict}/{self.total} "
            f"({self.strict_rate:.0%})",
        ]
        if self.errors:
            lines.append(
                f"  Errors: {self.errors}/{self.total} ({self.error_rate:.0%})"
            )
        lines.append("")
        lines.append("  Per bug class:")
        for cls, (loose, strict, errors, total) in self.per_class.items():
            tag = "" if not errors else f", errors={errors}"
            lines.append(
                f"    {cls:22s} loose={loose}/{total}  strict={strict}/{total}{tag}"
            )
        return "\n".join(lines)
