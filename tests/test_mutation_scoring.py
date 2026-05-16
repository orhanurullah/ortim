# SPDX-License-Identifier: FSL-1.1-Apache-2.0
# Copyright (c) 2026 ortim.dev
"""Mutation scorer — `score_case(case, verdict) -> (loose, strict)`."""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from runtime.executor.reviewer import CriterionVerdict, ReviewVerdict  # noqa: E402
from runtime.mutation import MutationCase, score_case  # noqa: E402


def _case(bug_keywords: list[str]) -> MutationCase:
    return MutationCase(
        name="x",
        bug_class="off-by-one",
        language="Python",
        task_title="t",
        task_description="d",
        module_scope="m",
        acceptance_criteria=["c1", "c2"],
        rfc_section="§1",
        rfc_excerpt="r",
        file_path="m/x.py",
        original_code="o",
        mutated_code="m",
        bug_keywords=bug_keywords,
    )


# ---------------------------------------------------------------------------
# Loose catch — verdict.approved drives the primary signal
# ---------------------------------------------------------------------------


def test_approved_verdict_means_no_catch() -> None:
    case = _case(bug_keywords=["index"])
    verdict = ReviewVerdict(
        criteria_verdicts=[
            CriterionVerdict(criterion="c1", status="pass", evidence="ok"),
            CriterionVerdict(criterion="c2", status="pass", evidence="ok"),
        ],
    )
    assert verdict.approved is True  # sanity
    loose, strict = score_case(case, verdict)
    assert loose is False
    assert strict is False


def test_fail_verdict_means_loose_catch() -> None:
    case = _case(bug_keywords=["anything"])
    verdict = ReviewVerdict(
        criteria_verdicts=[
            CriterionVerdict(criterion="c1", status="pass", evidence="ok"),
            CriterionVerdict(
                criterion="c2",
                status="fail",
                evidence="some unrelated reason",
            ),
        ],
    )
    loose, strict = score_case(case, verdict)
    assert loose is True
    assert strict is False  # no keyword match in evidence


def test_l1_violation_only_still_counts_loose_catch() -> None:
    """A verdict with all criteria pass but an L1 violation is still
    not approved — should count as a loose catch."""
    case = _case(bug_keywords=["di", "dependency injection"])
    verdict = ReviewVerdict(
        criteria_verdicts=[
            CriterionVerdict(criterion="c1", status="pass", evidence="ok"),
            CriterionVerdict(criterion="c2", status="pass", evidence="ok"),
        ],
        l1_violations=["DI violation: service instantiated in constructor"],
    )
    assert verdict.approved is False
    loose, strict = score_case(case, verdict)
    assert loose is True
    # L1 text contains "di" via "dependency" but the keyword "di" is a
    # 2-char substring — would match "service". Better assertion:
    # the more specific keyword does match the evidence.
    assert strict is True


# ---------------------------------------------------------------------------
# Strict catch — keyword search in failing criterion evidence + L1 text
# ---------------------------------------------------------------------------


def test_strict_catch_when_evidence_mentions_a_keyword() -> None:
    case = _case(bug_keywords=["IndexError", "out of bound"])
    verdict = ReviewVerdict(
        criteria_verdicts=[
            CriterionVerdict(
                criterion="c1",
                status="fail",
                evidence="The loop reaches one past the last index, producing IndexError on the final iteration.",
            ),
            CriterionVerdict(criterion="c2", status="pass", evidence="ok"),
        ],
    )
    loose, strict = score_case(case, verdict)
    assert loose is True
    assert strict is True


def test_strict_catch_when_code_quote_mentions_a_keyword() -> None:
    case = _case(bug_keywords=["range(len"])
    verdict = ReviewVerdict(
        criteria_verdicts=[
            CriterionVerdict(
                criterion="c1",
                status="fail",
                evidence="loop bound is off by one",
                code_quote="for i in range(len(nums)):",
            ),
        ],
    )
    loose, strict = score_case(case, verdict)
    assert loose is True
    assert strict is True


def test_strict_catch_keyword_matching_is_case_insensitive() -> None:
    case = _case(bug_keywords=["INDEXERROR"])
    verdict = ReviewVerdict(
        criteria_verdicts=[
            CriterionVerdict(
                criterion="c1",
                status="fail",
                evidence="this would raise indexerror at runtime",
            ),
        ],
    )
    _, strict = score_case(case, verdict)
    assert strict is True


def test_pass_status_evidence_is_not_scanned_for_strict_catch() -> None:
    """A `pass` criterion's evidence text doesn't contribute to the
    strict catch — only failing-criterion evidence + L1 + code quotes
    do. A defensive Reviewer that mentions the bug pattern in a
    'looks fine' justification should not score as a strict catch."""
    case = _case(bug_keywords=["IndexError"])
    verdict = ReviewVerdict(
        criteria_verdicts=[
            CriterionVerdict(
                criterion="c1",
                status="pass",
                evidence="No IndexError observed in the loop body",
            ),
            CriterionVerdict(
                criterion="c2",
                status="fail",
                evidence="completely unrelated reason",
            ),
        ],
    )
    loose, strict = score_case(case, verdict)
    assert loose is True
    assert strict is False


def test_unverifiable_only_verdict_counts_loose_not_strict() -> None:
    """All-unverifiable verdict is not approved (has_unverifiable wins).
    Counts as a loose catch — the Reviewer didn't bless the buggy
    code — but no failing-criterion evidence exists, so strict is False.
    This is the 'defensive but not diagnostic' shape the scorer needs
    to distinguish from real catches."""
    case = _case(bug_keywords=["anything"])
    verdict = ReviewVerdict(
        criteria_verdicts=[
            CriterionVerdict(
                criterion="c1",
                status="unverifiable",
                evidence="cannot determine without running tests",
                unverifiable_reason="test_infrastructure",
            ),
            CriterionVerdict(
                criterion="c2",
                status="unverifiable",
                evidence="ambiguous criterion wording",
                unverifiable_reason="criterion_design",
            ),
        ],
    )
    assert verdict.approved is False  # sanity
    loose, strict = score_case(case, verdict)
    assert loose is True
    assert strict is False


def test_empty_verdict_is_not_approved_so_counts_loose_not_strict() -> None:
    """A verdict with no criteria_verdicts is not approved by design.
    Loose catch, no strict (no evidence to scan)."""
    case = _case(bug_keywords=["anything"])
    verdict = ReviewVerdict()
    assert verdict.approved is False
    loose, strict = score_case(case, verdict)
    assert loose is True
    assert strict is False
