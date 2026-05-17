# SPDX-License-Identifier: FSL-1.1-Apache-2.0
# Copyright (c) 2026 ortim.dev
"""Scoring logic — given a ReviewVerdict + a MutationCase, was the bug caught?

Two definitions of "caught":

- **Loose:** the Reviewer marked the task NOT approved. This is the
  primary signal — a buggy diff should never be approved.
- **Strict:** loose AND the Reviewer's evidence text references at least
  one of the case's `bug_keywords`. This proves the Reviewer not only
  rejected the diff but understood WHY.

A high loose rate with a low strict rate means the Reviewer is
defensive (rejects on noise) but not diagnostic — a regression risk
for the auto-retry loop, which relies on `last_review_reasons` carrying
actionable feedback (Item 15a pattern).
"""

from __future__ import annotations

from ortim.executor.reviewer import ReviewVerdict
from ortim.mutation.case import MutationCase


def score_case(case: MutationCase, verdict: ReviewVerdict) -> tuple[bool, bool]:
    """Return `(caught_loose, caught_strict)` for one case+verdict pair.

    A strict catch always implies a loose catch — if the verdict
    approves the buggy code, no keyword search can rescue it.
    """
    caught_loose = not verdict.approved
    if not caught_loose:
        return (False, False)

    haystack_parts: list[str] = []
    for cv in verdict.criteria_verdicts:
        if cv.status in ("fail", "partial"):
            haystack_parts.append(cv.evidence or "")
            if cv.code_quote:
                haystack_parts.append(cv.code_quote)
    haystack_parts.extend(verdict.l1_violations)
    haystack = " ".join(haystack_parts).lower()

    if not haystack:
        # Loose catch but no failing-criterion evidence — strict miss.
        # This happens when only unverifiable criteria exist; we count
        # those as loose catches but not strict ones.
        return (True, False)

    caught_strict = any(
        kw.lower() in haystack for kw in case.bug_keywords
    )
    return (True, caught_strict)
