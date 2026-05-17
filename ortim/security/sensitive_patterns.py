# SPDX-License-Identifier: FSL-1.1-Apache-2.0
# Copyright (c) 2026 ortim.dev
"""Deterministic detector for security-sensitive task categories.

SecurityReviewer already hard-vetoes bad code (SQL injection, hardcoded
secrets, etc.). The gap this module closes: tasks whose **subject matter**
is sensitive — auth flows, payment integrations, PII handling — should
land in human review even when the Worker output reviews cleanly. The
liability cost of a missed bug here is much higher than for, say, a
todo-list CRUD task; the human gate is a deliberate slow-down.

The detector reads `TaskSpec.title + description + acceptance_criteria`
and returns the set of categories triggered. The runner uses the result
to escalate to AWAITING_HITL after reviewers approve. Bypass via
`ortim execute <id> <task> --human-reviewed` once a human has signed off.

Design notes:
  - Regex-only, deterministic. No LLM call. Cheap to run on every task.
  - Word-boundary anchors so "authentic" doesn't trigger "auth".
  - Category-keyword lists are conservative — false positives are
    cheaper than false negatives (a human reviews; that's the point).
  - Skills `auth-review-checklist.md` / `pii-review-checklist.md` /
    `payment-review-checklist.md` provide the human reviewer's checklist
    once a category is triggered; skill resolver consumes the categories.
"""

from __future__ import annotations

import re

from ortim.orchestrator import TaskSpec


# Category → keyword patterns. Each pattern is matched with `\b` word
# boundaries case-insensitively. Order is insignificant — multiple
# matches across categories simply yield multiple category tags.
_CATEGORY_PATTERNS: dict[str, tuple[str, ...]] = {
    "auth": (
        r"auth",
        r"login",
        r"logout",
        r"signin",
        r"sign[-_ ]in",
        r"signup",
        r"sign[-_ ]up",
        r"register",
        r"password",
        r"jwt",
        r"oauth",
        r"oidc",
        r"saml",
        r"session",
        r"token",
        r"bearer",
        r"refresh[-_ ]token",
        r"mfa",
        r"two[-_ ]factor",
        r"2fa",
        r"sso",
        r"authoriza?tion",
        r"authoriz\w*",        # authorize / authorized / unauthorized
        r"unauthorized",
        r"authentic",
        r"authenticat\w*",     # authenticate / authenticated / authenticating
        r"identity",
    ),
    "pii": (
        r"pii",
        r"personal[-_ ]data",
        r"personally[-_ ]identifiable",
        r"email",
        r"phone",
        r"address",
        r"ssn",
        r"social[-_ ]security",
        r"passport",
        r"government[-_ ]id",
        r"national[-_ ]id",
        r"tc[-_ ]kimlik",
        r"kimlik[-_ ]numarasi",
        r"kvkk",
        r"gdpr",
        r"hipaa",
        r"patient",
        r"medical[-_ ]record",
        r"health[-_ ]record",
    ),
    "payment": (
        r"payment",
        r"billing",
        r"invoice",
        r"checkout",
        r"credit[-_ ]card",
        r"debit[-_ ]card",
        r"pan\b",
        r"cvv",
        r"cvc",
        r"stripe",
        r"paypal",
        r"iyzico",
        r"iyzipay",
        r"adyen",
        r"braintree",
        r"square",
        r"refund",
        r"subscription",
        r"recurring[-_ ]charge",
        r"pci[-_ ]dss",
    ),
}

SENSITIVE_CATEGORIES: tuple[str, ...] = tuple(_CATEGORY_PATTERNS.keys())


# Pre-compile per-category to a single alternation regex. `\b` anchors so
# "authentic" still triggers "authentic" only via that explicit keyword,
# not via "auth" substring. Each compiled regex matches case-insensitively.
_COMPILED: dict[str, re.Pattern[str]] = {
    cat: re.compile(
        r"\b(?:" + "|".join(patterns) + r")\b",
        re.IGNORECASE,
    )
    for cat, patterns in _CATEGORY_PATTERNS.items()
}


def detect_sensitive_categories(task: TaskSpec) -> list[str]:
    """Return the set of sensitive categories triggered by a task's
    title + description + acceptance criteria, sorted alphabetically.

    Empty list = no trigger. Caller (Orchestrator post-process or the
    runner) writes the result into `TaskSpec.sensitive_categories`.
    """
    blob_parts: list[str] = [task.title, task.description]
    blob_parts.extend(task.acceptance_criteria)
    blob = " \n ".join(blob_parts)

    hit: list[str] = []
    for category, pattern in _COMPILED.items():
        if pattern.search(blob):
            hit.append(category)
    return sorted(hit)
