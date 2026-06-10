# SPDX-License-Identifier: FSL-1.1-Apache-2.0
# Copyright (c) 2026 ortim.dev
"""Item 40 — Architect must not introduce libraries beyond the locked stack.

Proof-point E2E (workspace `ed9f6074f1b8`, 2026-05-14) showed the Architect
silently adding `zustand` to RFC §4 'Key libraries' even though the
STACK_DIALOG-locked stack listed only `[sql.js, zod]`. The new defense is
two-layered: stronger prompt + post-draft `_find_phantom_libraries`
validator + bounded retry-with-correction loop (matching the reviewer
length-validator pattern from item 21).
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from ortim.agents.architect import (  # noqa: E402
    ArchitectAgent,
    _find_phantom_libraries,
    _parse_rfc_key_libraries,
)
from ortim.architecture import LockedStack, Tier, TierScore  # noqa: E402
from ortim.audit import AuditLogger  # noqa: E402
from ortim.llm.client import LLMResponse  # noqa: E402
from ortim.memory import MemoryLoader  # noqa: E402


# ---------------------------------------------------------------------------
# Parser unit tests
# ---------------------------------------------------------------------------


def test_parse_rfc_key_libraries_extracts_simple_list() -> None:
    rfc = (
        "# RFC\n\n"
        "## 4. Tech Stack\n\n"
        "- **Language:** TypeScript\n"
        "- **Primary framework:** React + Vite\n"
        "- **Key libraries:** sql.js, zod, zustand\n"
        "- **Deploy target:** Static hosting\n\n"
        "## 5. Data Model\n\n"
    )
    assert _parse_rfc_key_libraries(rfc) == ["sql.js", "zod", "zustand"]


def test_parse_rfc_key_libraries_strips_parenthetical_notes() -> None:
    rfc = (
        "## 4. Tech Stack\n\n"
        "- **Key libraries:** sql.js, zod (validation), zustand (state management)\n"
    )
    assert _parse_rfc_key_libraries(rfc) == ["sql.js", "zod", "zustand"]


def test_parse_rfc_key_libraries_returns_none_when_section_missing() -> None:
    rfc = "# RFC\n\n## 5. Data Model\n\n(no tech stack section)\n"
    assert _parse_rfc_key_libraries(rfc) is None


def test_parse_rfc_key_libraries_returns_none_when_line_missing() -> None:
    rfc = (
        "## 4. Tech Stack\n\n"
        "- **Language:** Go\n"
        "- **Primary framework:** Cobra\n"
        "(no key libraries line)\n"
    )
    assert _parse_rfc_key_libraries(rfc) is None


# ---------------------------------------------------------------------------
# Validator unit tests
# ---------------------------------------------------------------------------


def _stack(key_libraries: list[str]) -> LockedStack:
    return LockedStack(
        tier="T2",
        app_class="web",
        language="TypeScript",
        primary_framework="React + Vite",
        package_manager="npm",
        test_cmd="npx vitest run",
        run_cmd="npm run dev",
        key_libraries=key_libraries,
    )


def test_find_phantom_libraries_empty_when_subset() -> None:
    rfc = "## 4. Tech Stack\n\n- **Key libraries:** sql.js, zod\n"
    assert _find_phantom_libraries(rfc, _stack(["sql.js", "zod"])) == []


def test_find_phantom_libraries_detects_extra() -> None:
    rfc = "## 4. Tech Stack\n\n- **Key libraries:** sql.js, zod, zustand\n"
    phantoms = _find_phantom_libraries(rfc, _stack(["sql.js", "zod"]))
    assert phantoms == ["zustand"]


def test_find_phantom_libraries_case_insensitive() -> None:
    rfc = "## 4. Tech Stack\n\n- **Key libraries:** SQL.js, Zod\n"
    assert _find_phantom_libraries(rfc, _stack(["sql.js", "zod"])) == []


# ---------------------------------------------------------------------------
# Integration tests for draft_rfc retry loop
# ---------------------------------------------------------------------------


@dataclass
class _SequentialLLM:
    """LLM stand-in that returns a pre-baked sequence of responses, one per
    `call(...)`. Used to simulate first-attempt drift + clean retry."""

    responses: list[str]
    calls: list[tuple[str, str]] = field(default_factory=list)
    _idx: int = 0

    def call(
        self,
        system: str,
        user: str,
        temperature: float = 0.0,
        max_tokens: int = 4096,
    ) -> LLMResponse:
        self.calls.append((system, user))
        text = self.responses[self._idx]
        self._idx += 1
        return LLMResponse(
            text=text,
            input_tokens=10,
            output_tokens=5,
            model="fake-model",
            provider="fake",
        )


def _tier_score() -> TierScore:
    return TierScore(tier=Tier.T2, score=100, pros=[], cons=[])


def _agent(llm) -> ArchitectAgent:
    return ArchitectAgent(llm=llm, memory=MemoryLoader(REPO_ROOT), audit=AuditLogger())


def _clean_rfc() -> str:
    return (
        "# RFC: test\n\n"
        "## 1. Context\nbrief\n\n"
        "## 4. Tech Stack\n\n"
        "- **Language:** TypeScript\n"
        "- **Primary framework:** React + Vite\n"
        "- **Key libraries:** sql.js, zod\n\n"
        "## 7. Module Breakdown\n"
        "| Module | Responsibility |\n|---|---|\n| store | state |\n"
    )


def _drifted_rfc() -> str:
    return _clean_rfc().replace(
        "**Key libraries:** sql.js, zod",
        "**Key libraries:** sql.js, zod, zustand",
    )


def test_draft_rfc_retries_on_phantom_library_then_succeeds(tmp_path: Path) -> None:
    """First attempt sneaks in zustand; second attempt honors the locked
    stack. Loop must accept the second attempt and return it."""
    llm = _SequentialLLM(responses=[_drifted_rfc(), _clean_rfc()])
    agent = _agent(llm)

    rfc = agent.draft_rfc(
        prd_markdown="A simple todo app.",
        tier_score=_tier_score(),
        project_name="todo",
        project_id="proj-test",
        app_class="web",
        locked_stack=_stack(["sql.js", "zod"]),
    )

    assert "zustand" not in rfc, "Final RFC must be the second (clean) attempt"
    assert len(llm.calls) == 2, "Loop should call LLM exactly twice (1 drift + 1 clean)"
    # Second call's user prompt must carry the structured correction
    second_user = llm.calls[1][1]
    assert "RETRY" in second_user
    assert "zustand" in second_user


def test_draft_rfc_raises_after_three_phantom_attempts(tmp_path: Path) -> None:
    """If the LLM keeps drifting for the full retry budget, `draft_rfc`
    raises RuntimeError rather than returning a corrupt RFC."""
    llm = _SequentialLLM(
        responses=[_drifted_rfc(), _drifted_rfc(), _drifted_rfc()]
    )
    agent = _agent(llm)

    with pytest.raises(RuntimeError, match="zustand"):
        agent.draft_rfc(
            prd_markdown="A simple todo app.",
            tier_score=_tier_score(),
            project_name="todo",
            project_id="proj-test",
            app_class="web",
            locked_stack=_stack(["sql.js", "zod"]),
        )
    assert len(llm.calls) == 3, "Loop must consume the full retry budget"


def test_draft_rfc_without_locked_stack_skips_validation(tmp_path: Path) -> None:
    """Pre-M2 callers (no locked_stack) should not be subject to the
    subset check — the constraint only makes sense when a stack was
    locked via STACK_DIALOG."""
    # Even a "drifted" RFC is acceptable when there's no locked stack
    # because there's nothing to drift FROM.
    llm = _SequentialLLM(responses=[_drifted_rfc()])
    agent = _agent(llm)
    rfc = agent.draft_rfc(
        prd_markdown="A simple todo app.",
        tier_score=_tier_score(),
        project_name="todo",
        project_id="proj-test",
        app_class="web",
        locked_stack=None,
    )
    assert "zustand" in rfc
    assert len(llm.calls) == 1, "No retry without a locked_stack"


def test_draft_rfc_prompt_includes_key_libraries_hard_rule(tmp_path: Path) -> None:
    """The Architect prompt must spell out the exact allowed library list
    so the LLM has the constraint in context BEFORE the validator catches
    drift on retry. Otherwise the loop wastes a turn just teaching the
    rule."""
    llm = _SequentialLLM(responses=[_clean_rfc()])
    agent = _agent(llm)
    agent.draft_rfc(
        prd_markdown="A simple todo app.",
        tier_score=_tier_score(),
        project_name="todo",
        project_id="proj-test",
        app_class="web",
        locked_stack=_stack(["sql.js", "zod"]),
    )
    system = llm.calls[0][0]
    assert "HARD RULE FOR §4" in system
    assert "sql.js, zod" in system
    assert "zustand" in system  # Listed as a counter-example in the hard rule


# ---------------------------------------------------------------------------
# Item 45 — extract_inputs derivation rules
# ---------------------------------------------------------------------------


def test_architect_prompt_teaches_single_user_derivation_rules() -> None:
    """Item 45 fix: agents/architect.md Call 1 must include derivation
    rules that resolve common implicit signals (single-user, team SaaS,
    enterprise, browser-only) to canonical GoldenPathInputs values BEFORE
    falling back to `"unknown"`.

    Symptom (proof-point v3 vs v1/v2/v4): same Turkish single-user
    browser-todo brief produced `expected_scale/team_size/ops_capacity =
    small/solo/low` in 3/4 runs, and `unknown/unknown/unknown` in 1/4
    runs. The variant produced a different deterministic tier (T4 vs T2),
    breaking the planning chain downstream. Root cause: prompt Rule 2
    said "use unknown when not sure" without bridging implicit signals
    (single-user → obviously small/solo/low) to canonical values, so the
    LLM oscillated between conservative and inferential readings.
    """
    repo_root = Path(__file__).resolve().parent.parent
    prompt = (repo_root / "ortim" / "_assets" / "agents" / "architect.md").read_text(encoding="utf-8")
    p_lower = prompt.lower()

    # New derivation-rules section must exist by header.
    assert "derivation rules" in p_lower, (
        "Call 1 prompt must declare derivation rules section"
    )

    # The four named cases must all be present.
    for case in (
        "single-user / personal apps",
        "team / saas apps",
        "enterprise / regulated",
        "browser-only / offline-first",
    ):
        assert case in p_lower, f"Derivation rule case missing: {case!r}"

    # The single-user → small/solo/low chain must be stated explicitly,
    # since that's the exact v3 regression case.
    assert "single-user" in p_lower
    assert "expected_scale = \"small\"" in prompt
    assert "team_size = \"solo\"" in prompt
    assert "ops_capacity = \"low\"" in prompt

    # Rule 2 must explicitly subordinate to derivation rules — otherwise
    # the LLM still defaults to `"unknown"` first.
    assert "no signal in §6" in prompt or "no signal in section 6" in p_lower or (
        "use these derivations" in p_lower and "first" in p_lower
    ), (
        "Rule 2 must reference §6 derivation rules as the precedence path "
        "for implicit signals; otherwise unknown-bias remains."
    )


def test_architect_prompt_includes_extract_inputs_few_shot_examples() -> None:
    """Item 45 fix: a single-user todo example must appear verbatim so the
    LLM has a concrete pattern to match the v3-class brief against. Pure
    rules without examples were not enough — v3 still fell to `unknown`
    despite Rule 4 ('small < 1K users') technically resolving it."""
    repo_root = Path(__file__).resolve().parent.parent
    prompt = (repo_root / "ortim" / "_assets" / "agents" / "architect.md").read_text(encoding="utf-8")

    # Examples header must exist.
    assert "Examples — apply the derivation rules consistently" in prompt

    # Example A is the v3 regression case verbatim — must lock the expected
    # output JSON shape so the LLM sees the canonical answer.
    assert "single-user personal todo (browser-only)" in prompt.lower()
    assert '"expected_scale": "small"' in prompt
    assert '"team_size": "solo"' in prompt
    assert '"ops_capacity": "low"' in prompt

    # Counter-example C — genuinely vague brief — must show that `unknown`
    # is still the right answer when no signal is present. Without this,
    # the derivation rules read as "always infer" and the LLM may
    # over-infer on truly empty briefs.
    assert "vague brief" in prompt.lower() or "genuinely vague" in prompt.lower()
