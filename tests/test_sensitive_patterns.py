# SPDX-License-Identifier: FSL-1.1-Apache-2.0
# Copyright (c) 2026 ortim.dev
"""Tests for Faz 1.5 — sensitive_categories pattern detector + gate.

The gate's purpose: SecurityReviewer hard-vetoes bad code, but security-
sensitive task subject matter (auth flows, PII handling, payment) deserves
human review even when the Worker output reviews cleanly. The deterministic
detector reads task title + description + acceptance criteria and tags the
task; the runner gates the merge on `--human-reviewed`.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from ortim.orchestrator import TaskSpec  # noqa: E402
from ortim.security import (  # noqa: E402
    SENSITIVE_CATEGORIES,
    detect_sensitive_categories,
)


def _task(title: str = "x", description: str = "x", criteria: list[str] | None = None) -> TaskSpec:
    return TaskSpec(
        id="T-001",
        title=title,
        description=description,
        module_scope="m",
        acceptance_criteria=criteria or ["c"],
    )


def test_categories_exposed_for_skill_resolver() -> None:
    assert "auth" in SENSITIVE_CATEGORIES
    assert "pii" in SENSITIVE_CATEGORIES
    assert "payment" in SENSITIVE_CATEGORIES


def test_neutral_task_yields_no_categories() -> None:
    task = _task(
        title="Implement TodoRepository CRUD",
        description="Create a repository with add, list, complete, delete methods.",
        criteria=["file exports class TodoRepository"],
    )
    assert detect_sensitive_categories(task) == []


def test_auth_keyword_triggers_auth_category() -> None:
    task = _task(
        title="Implement JWT auth middleware",
        description="Verify Bearer token on every request",
        criteria=["middleware rejects requests with invalid token"],
    )
    cats = detect_sensitive_categories(task)
    assert "auth" in cats


def test_password_keyword_triggers_auth() -> None:
    task = _task(
        title="User registration endpoint",
        description="Accept email + password, hash with bcrypt, store user",
    )
    cats = detect_sensitive_categories(task)
    assert "auth" in cats


def test_pii_keyword_triggers_pii_category() -> None:
    task = _task(
        title="Patient record CRUD",
        description="Manage patient medical records with KVKK compliance",
        criteria=["patient.kvkk_consent stored alongside record"],
    )
    cats = detect_sensitive_categories(task)
    assert "pii" in cats


def test_payment_keyword_triggers_payment() -> None:
    task = _task(
        title="Stripe checkout integration",
        description="Accept credit card payments via Stripe Elements",
        criteria=["webhook signature verified"],
    )
    cats = detect_sensitive_categories(task)
    assert "payment" in cats


def test_multiple_categories_triggered() -> None:
    task = _task(
        title="Implement paid subscription with login + Stripe",
        description="JWT auth for users, Stripe checkout for billing, store email",
    )
    cats = detect_sensitive_categories(task)
    assert "auth" in cats
    assert "payment" in cats
    assert "pii" in cats


def test_word_boundary_prevents_substring_false_positive() -> None:
    """'authentic' should NOT trigger 'auth' as a generic substring — but
    'authentic' is explicitly in the auth keyword list (intentional —
    'authentic data' often appears in auth context). Test guards against
    the opposite: random words containing 'auth' should NOT trigger."""
    task = _task(
        title="Implement audio-thunder sound effect engine",
        description="Generate thunder sound from random seed for game scenes",
    )
    cats = detect_sensitive_categories(task)
    assert "auth" not in cats


def test_case_insensitive() -> None:
    task = _task(
        title="LOGIN ENDPOINT",
        description="USER PASSWORD AUTHENTICATION",
    )
    cats = detect_sensitive_categories(task)
    assert "auth" in cats


def test_keywords_in_acceptance_criteria_also_count() -> None:
    """Criterion text is part of the blob — auth keywords there should
    also trigger the category."""
    task = _task(
        title="Build user dashboard",
        description="Show user-specific data",
        criteria=["dashboard rejects unauthorized requests (401)"],
    )
    cats = detect_sensitive_categories(task)
    assert "auth" in cats


def test_sorted_output_for_stable_audit() -> None:
    """Multiple-category output sorted alphabetically so audit log is
    diff-friendly across runs."""
    task = _task(
        title="Payment + auth",
        description="JWT + Stripe",
    )
    cats = detect_sensitive_categories(task)
    assert cats == sorted(cats)


def test_task_spec_default_sensitive_categories_empty() -> None:
    """Backward-compat: pre-1.5 DAGs without this field load cleanly."""
    task = _task()
    assert task.sensitive_categories == []


def test_task_spec_accepts_sensitive_categories() -> None:
    task = TaskSpec(
        id="T-002",
        title="auth task",
        description="x",
        module_scope="m",
        sensitive_categories=["auth"],
    )
    assert task.sensitive_categories == ["auth"]
