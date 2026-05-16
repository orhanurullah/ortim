# SPDX-License-Identifier: FSL-1.1-Apache-2.0
# Copyright (c) 2026 ortim.dev
"""Tests for Faz 1.2 B-2 — user_stack_hints flow.

`bf761fff02b0` proof-point showed that when the user wrote "Python +
FastAPI + SQLite" in the brief, the T2/BaaS tier default silently
substituted Supabase+PostgreSQL. The fix:
  1. Babel captures explicit stack names in `StructuredIntent.user_stack_hints`
  2. Architect.draft_rfc (legacy/dialog-off path) injects them as a HARD
     binding above the tier-default constraint

These tests pin both layers — the schema + the prompt injection.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from dataclasses import dataclass, field  # noqa: E402

from runtime.architecture import GoldenPathInputs, Tier, select_tier  # noqa: E402
from runtime.audit import AuditLogger  # noqa: E402
from runtime.babel import StructuredIntent  # noqa: E402
from runtime.llm.client import LLMResponse  # noqa: E402
from runtime.memory import MemoryLoader  # noqa: E402


# ---------- Schema layer ----------------------------------------------------


def test_structured_intent_defaults_to_empty_user_stack_hints() -> None:
    s = StructuredIntent(goal="x")
    assert s.user_stack_hints == []


def test_structured_intent_serializes_user_stack_hints() -> None:
    s = StructuredIntent(goal="x", user_stack_hints=["Python", "FastAPI", "SQLite"])
    j = s.model_dump_json()
    reloaded = StructuredIntent.model_validate_json(j)
    assert reloaded.user_stack_hints == ["Python", "FastAPI", "SQLite"]


def test_legacy_intent_json_without_hints_loads_clean() -> None:
    """Pre-1.2 intent.json files have no `user_stack_hints` key. Pydantic
    default must keep them loading without migration."""
    legacy = """{"goal": "legacy project", "must_have_features": ["x"]}"""
    s = StructuredIntent.model_validate_json(legacy)
    assert s.user_stack_hints == []


# ---------- Architect prompt injection --------------------------------------


@dataclass
class CapturingFakeLLM:
    """LLM stub that records every `call(system, user)` so the test can
    assert the prompt contains the user-named stack hints."""

    rfc_text: str = "# RFC stub\n## 4. Tech Stack\n- **Key libraries:** (none specified)\n"
    calls: list[tuple[str, str]] = field(default_factory=list)

    def call(
        self,
        system: str,
        user: str,
        temperature: float = 0.0,
        max_tokens: int = 4096,
    ) -> LLMResponse:
        self.calls.append((system, user))
        return LLMResponse(
            text=self.rfc_text,
            input_tokens=10,
            output_tokens=5,
            model="fake",
            provider="fake",
        )


def _tier_score() -> object:
    """Pick a tier deterministically using a T2-shaped GoldenPathInputs.
    The B-2 bug was specifically tier=T2 substituting Supabase; pinning
    that tier here keeps the regression test representative."""
    inputs = GoldenPathInputs(
        has_persistent_state=True,
        has_auth=True,
        compliance=[],
        expected_scale="small",
        team_size="solo",
        app_class="web",
    )
    return select_tier(inputs)


def test_draft_rfc_injects_user_stack_hints_into_prompt() -> None:
    from runtime.agents.architect import ArchitectAgent

    fake = CapturingFakeLLM()
    memory = MemoryLoader(REPO_ROOT)
    audit = AuditLogger()
    agent = ArchitectAgent(fake, memory, audit)

    tier_score = _tier_score()
    agent.draft_rfc(
        prd_markdown="# PRD stub\nminimal PRD",
        tier_score=tier_score,
        project_name="t",
        project_id="test-hints-001",
        app_class="web",
        codebase=None,
        locked_stack=None,
        scope=None,
        user_stack_hints=["Python", "FastAPI", "SQLite"],
    )

    assert fake.calls, "Architect did not call the LLM"
    system, _ = fake.calls[0]
    assert "User-Named Stack" in system, "hint section header missing"
    assert "Python" in system and "FastAPI" in system and "SQLite" in system
    # The whole point: hints must outrank the tier default. Verify the
    # override sentence is present so the LLM sees both signals.
    assert "Never SUBSTITUTE" in system or "user-named tool" in system


def test_draft_rfc_omits_hint_block_when_no_hints() -> None:
    from runtime.agents.architect import ArchitectAgent

    fake = CapturingFakeLLM()
    memory = MemoryLoader(REPO_ROOT)
    audit = AuditLogger()
    agent = ArchitectAgent(fake, memory, audit)

    agent.draft_rfc(
        prd_markdown="# PRD stub",
        tier_score=_tier_score(),
        project_name="t",
        project_id="test-no-hints-001",
        app_class="web",
        codebase=None,
        locked_stack=None,
        scope=None,
        user_stack_hints=[],
    )

    system, _ = fake.calls[0]
    assert "User-Named Stack" not in system
