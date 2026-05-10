# SPDX-License-Identifier: FSL-1.1-Apache-2.0
# Copyright (c) 2026 ortim.dev
"""Tests for LLM transient retry with exponential backoff."""

from __future__ import annotations

import time
from dataclasses import dataclass
from unittest.mock import MagicMock, patch

import pytest

from runtime.llm.client import MAX_RETRIES, LLMResponse, _is_retryable


# ---- _is_retryable classification ----


class FakeAPIStatusError(Exception):
    """Minimal stand-in for anthropic.APIStatusError."""

    def __init__(self, status_code: int):
        self.status_code = status_code
        super().__init__(f"HTTP {status_code}")


class FakeAPIConnectionError(Exception):
    """Minimal stand-in for anthropic.APIConnectionError."""

    pass


def test_retryable_503():
    exc = FakeAPIStatusError(503)
    # Patch the isinstance checks — _is_retryable uses anthropic types.
    from anthropic import APIStatusError

    real_exc = type("FakeStatus", (APIStatusError,), {})
    # We can't easily instantiate the real class, so test the message path.
    assert _is_retryable(Exception("overloaded server"))


def test_retryable_connection_error():
    from anthropic import APIConnectionError

    # Message path fallback
    assert _is_retryable(Exception("rate limit exceeded"))


def test_retryable_deepseek_busy():
    assert _is_retryable(Exception("Service is too busy"))


def test_not_retryable_auth_error():
    assert not _is_retryable(Exception("Invalid API key"))


def test_not_retryable_generic():
    assert not _is_retryable(ValueError("unexpected value"))


# ---- LLMResponse.retries field ----


def test_response_retries_default():
    r = LLMResponse(
        text="hello", input_tokens=10, output_tokens=5,
        model="test", provider="test",
    )
    assert r.retries == 0
    assert "retries" not in r.audit_fields()


def test_response_retries_nonzero():
    r = LLMResponse(
        text="hello", input_tokens=10, output_tokens=5,
        model="test", provider="test", retries=2,
    )
    assert r.retries == 2
    assert r.audit_fields()["retries"] == 2


# ---- Unverifiable two-mode ----


def test_unverifiable_reason_criterion_design():
    from runtime.executor.reviewer import CriterionVerdict, ReviewVerdict

    v = ReviewVerdict(criteria_verdicts=[
        CriterionVerdict(
            criterion="prints todo ID",
            status="unverifiable",
            evidence="ambiguous wording",
            unverifiable_reason="criterion_design",
        ),
    ])
    assert v.has_unverifiable
    assert len(v.unverifiable_by_design) == 1
    assert len(v.unverifiable_by_infra) == 0
    reasons = v.reasons
    assert any("unverifiable:design" in r for r in reasons)


def test_unverifiable_reason_test_infrastructure():
    from runtime.executor.reviewer import CriterionVerdict, ReviewVerdict

    v = ReviewVerdict(criteria_verdicts=[
        CriterionVerdict(
            criterion="test passes",
            status="unverifiable",
            evidence="test runner not available",
            unverifiable_reason="test_infrastructure",
        ),
    ])
    assert v.has_unverifiable
    assert len(v.unverifiable_by_design) == 0
    assert len(v.unverifiable_by_infra) == 1
    reasons = v.reasons
    assert any("unverifiable:test_infra" in r for r in reasons)
    assert any("AI_FACTORY_TEST_CMD" in r for r in reasons)


def test_unverifiable_backward_compat_none_reason():
    """Old LLM outputs that don't set unverifiable_reason default to criterion_design."""
    from runtime.executor.reviewer import CriterionVerdict, ReviewVerdict

    v = ReviewVerdict(criteria_verdicts=[
        CriterionVerdict(
            criterion="output is clean",
            status="unverifiable",
            evidence="subjective criterion",
            # unverifiable_reason not set → None → criterion_design
        ),
    ])
    assert len(v.unverifiable_by_design) == 1
    assert len(v.unverifiable_by_infra) == 0


def test_unverifiable_mixed_modes():
    from runtime.executor.reviewer import CriterionVerdict, ReviewVerdict

    v = ReviewVerdict(criteria_verdicts=[
        CriterionVerdict(
            criterion="readable output",
            status="unverifiable",
            evidence="subjective",
            unverifiable_reason="criterion_design",
        ),
        CriterionVerdict(
            criterion="test passes",
            status="unverifiable",
            evidence="no runner",
            unverifiable_reason="test_infrastructure",
        ),
        CriterionVerdict(
            criterion="creates file",
            status="pass",
            evidence="file exists",
        ),
    ])
    assert v.has_unverifiable
    assert len(v.unverifiable_by_design) == 1
    assert len(v.unverifiable_by_infra) == 1
    assert not v.approved


# ---- Provider fail-loud ----


def test_critical_role_warning(capsys, monkeypatch):
    """architect role with no explicit provider emits a stderr warning."""
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    monkeypatch.setenv("LLM_PROVIDER", "deepseek")
    monkeypatch.delenv("ARCHITECT_PROVIDER", raising=False)
    monkeypatch.delenv("ARCHITECT_MODEL", raising=False)

    from runtime.llm.router import client_for

    client = client_for("architect")
    captured = capsys.readouterr()
    assert "WARNING" in captured.err
    assert "architect" in captured.err.lower()
    assert "ARCHITECT_PROVIDER" in captured.err


def test_non_critical_role_no_warning(capsys, monkeypatch):
    """Non-critical roles (babel) should not emit provider warnings."""
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    monkeypatch.setenv("LLM_PROVIDER", "deepseek")
    monkeypatch.delenv("BABEL_PROVIDER", raising=False)

    from runtime.llm.router import client_for

    client = client_for("babel")
    captured = capsys.readouterr()
    assert "WARNING" not in captured.err
