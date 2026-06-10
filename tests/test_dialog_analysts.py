# SPDX-License-Identifier: FSL-1.1-Apache-2.0
# Copyright (c) 2026 ortim.dev
"""Smoke tests for the M2 dialog agents — IntentAnalyst, StackAnalyst,
PRDAnalyst — using a capturing LLM stub.

Goals:
  - IntentAnalyst.draft / refine wire prior_md and user_feedback into
    the user prompt (no silent feedback loss)
  - StackAnalyst.propose emits parseable LockedStack JSON; refine carries
    the user override into the prompt verbatim (so the LLM has to honor it)
  - PRDAnalyst.draft injects the locked stack's tech block into the prompt
    so the PRD's Tech Stack section can't drift from the locked stack
"""

from __future__ import annotations

import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from ortim.agents.intent_analyst import IntentAnalyst  # noqa: E402
from ortim.agents.prd_analyst import PRDAnalyst  # noqa: E402
from ortim.agents.stack_analyst import StackAnalyst  # noqa: E402
from ortim.architecture import LockedStack, Tier, TierScore  # noqa: E402
from ortim.audit import AuditLogger  # noqa: E402
from ortim.babel import StructuredIntent  # noqa: E402
from ortim.llm.client import LLMResponse  # noqa: E402
from ortim.memory import MemoryLoader  # noqa: E402


@dataclass
class CapturingLLM:
    """Records every call and returns a canned response."""

    response_text: str = "{}"
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
            text=self.response_text,
            input_tokens=10,
            output_tokens=5,
            model="fake-model",
            provider="fake",
        )


def _setup_llm(text: str) -> tuple[CapturingLLM, MemoryLoader, AuditLogger]:
    tmp = tempfile.mkdtemp()
    audit = AuditLogger(path=Path(tmp) / "audit.jsonl")
    memory = MemoryLoader(REPO_ROOT)
    return CapturingLLM(response_text=text), memory, audit


def _intent() -> StructuredIntent:
    return StructuredIntent(
        goal="A CLI notes app",
        target_users=["solo developer"],
        must_have_features=["add note", "list notes", "delete note"],
        explicit_non_goals=["multi-user sync"],
        constraints=["offline-first", "single-user"],
    )


def _tier_t0() -> TierScore:
    return TierScore(
        tier=Tier.T0,
        score=100,
        pros=["single binary", "no server"],
        cons=[],
    )


# ---------- IntentAnalyst ----------


def test_intent_analyst_draft_passes_structured_intent() -> None:
    """draft() must wire the StructuredIntent into the user prompt so
    the LLM has the authoritative source — not just the project name."""
    llm, memory, audit = _setup_llm("# Project Intent\nGoal: ...")
    agent = IntentAnalyst(llm, memory, audit)
    out = agent.draft(_intent(), project_name="notes", project_id="P-1")

    assert llm.calls, "IntentAnalyst should call LLM"
    _, user_prompt = llm.calls[0]
    assert "Structured intent" in user_prompt
    assert "A CLI notes app" in user_prompt
    assert "offline-first" in user_prompt
    assert out.startswith("# Project Intent")


def test_intent_analyst_refine_includes_feedback_and_previous() -> None:
    """refine() must inject both previous intent.md AND user feedback
    into the user prompt — otherwise the auto-retry-style loop loses
    its teeth (sandbox feedback bug, item 15, but for dialog)."""
    llm, memory, audit = _setup_llm("# Project Intent\nGoal: ...")
    agent = IntentAnalyst(llm, memory, audit)
    prev = "# Project Intent\n\n## Goal\nA single-user notes app.\n"
    feedback = "Add tagging support to must-have features."

    agent.refine(
        previous_md=prev,
        intent=_intent(),
        user_feedback=feedback,
        project_name="notes",
        project_id="P-1",
    )

    assert llm.calls, "IntentAnalyst.refine should call LLM"
    _, user_prompt = llm.calls[0]
    assert "Previous intent summary" in user_prompt
    assert "single-user notes app" in user_prompt
    assert "User feedback" in user_prompt
    assert "tagging support" in user_prompt


# ---------- StackAnalyst ----------


_STACK_JSON_TS = (
    '{"version": 1, "tier": "T0", "app_class": "web", '
    '"language": "TypeScript", "primary_framework": "Node CLI (tsx)", '
    '"package_manager": "npm", "test_cmd": "npx vitest run", '
    '"run_cmd": "npx tsx src/main.ts", "key_libraries": ["commander"], '
    '"deploy_target": "none", "rationale": "Single-binary friendly for solo CLI."}'
)


def test_stack_analyst_propose_returns_parseable_locked_stack() -> None:
    """propose() must return a LockedStack matching the schema and
    inject the intent + tier suggestion into the prompt."""
    llm, memory, audit = _setup_llm(_STACK_JSON_TS)
    agent = StackAnalyst(llm, memory, audit)
    intent_md = "# Project Intent\n\n## Goal\nA CLI notes app.\n"

    out = agent.propose(
        intent_md=intent_md,
        tier_suggestion=_tier_t0(),
        app_class="web",
        project_id="P-1",
    )

    assert isinstance(out, LockedStack)
    assert out.language == "TypeScript"
    assert out.test_cmd == "npx vitest run"

    sys_prompt, user_prompt = llm.calls[0]
    assert "Deterministic Tier Suggestion" in sys_prompt
    assert "T0" in sys_prompt
    assert "Locked intent" in user_prompt
    assert "A CLI notes app" in user_prompt


def test_stack_analyst_prompt_teaches_browser_only_intent_detection() -> None:
    """BaaS-drift fix: agents/stack_analyst.md must teach the LLM to
    distinguish browser-side persistence ("yerel veritabani", sql.js,
    IndexedDB) from "needs a server with a DB" so it stops proposing
    `Node + Hono` for offline single-user browser apps.

    Symptom (proof-points v1+v2+v3): same Turkish brief — local-database,
    offline, single-user todo — produced `Node + Hono` autonomously every
    time. Required user refine every time.
    """
    repo_root = Path(__file__).resolve().parent.parent
    prompt = (repo_root / "ortim" / "_assets" / "agents" / "stack_analyst.md").read_text(encoding="utf-8")
    p_lower = prompt.lower()

    # Section header naming the failure mode.
    assert "browser-only intent detection" in p_lower

    # Browser-only positive signals must be named explicitly.
    assert "sql.js" in p_lower
    assert "indexeddb" in p_lower
    assert "localstorage" in p_lower
    assert "yerel veritabani" in p_lower or "yerel veritabanı" in p_lower
    assert "offline-first" in p_lower or "offline" in p_lower

    # Backend signals must also be named explicitly (the counter-example
    # that ALLOWS server frameworks when intent actually demands them).
    assert "multi-user" in p_lower or "kullanıcılar arasında" in p_lower
    assert "auth" in p_lower
    assert "api" in p_lower or "rest" in p_lower

    # Forbidden picks named verbatim — the LLM must see the literal
    # framework names it's been silently choosing.
    for forbidden in ("hono", "express", "fastify", "koa"):
        assert forbidden in p_lower, f"{forbidden} must be named as forbidden"

    # The hard boundary in the top list must also reference the new section.
    assert "browser-only" in p_lower

    # Decision rule with a quantifier (≥2 browser AND 0 backend) must be
    # concrete enough to read as a rule, not just a vibe.
    assert "≥2" in prompt or ">= 2" in prompt or "two or more" in p_lower
    assert "0 backend" in p_lower or "no backend" in p_lower


def test_stack_analyst_refine_threads_user_override_into_prompt() -> None:
    """refine() must put the user feedback in the prompt VERBATIM. If
    the user says 'use Python', that string must appear — the LLM has
    to see the override to honor it (hard rule in stack_analyst.md)."""
    llm, memory, audit = _setup_llm(_STACK_JSON_TS)  # response doesn't matter here
    agent = StackAnalyst(llm, memory, audit)
    prev = LockedStack(
        tier="T0",
        app_class="web",
        language="TypeScript",
        primary_framework="Node CLI",
        package_manager="npm",
        test_cmd="npx vitest run",
        run_cmd="npx tsx src/main.ts",
    )

    agent.refine(
        previous_stack=prev,
        intent_md="# Project Intent\n",
        user_feedback="Use Python instead of TypeScript.",
        tier_suggestion=_tier_t0(),
        project_id="P-1",
    )

    _, user_prompt = llm.calls[0]
    assert "Previous stack proposal" in user_prompt
    assert '"language": "TypeScript"' in user_prompt
    assert "User feedback" in user_prompt
    assert "Use Python instead of TypeScript." in user_prompt


# ---------- PRDAnalyst ----------


def test_prd_analyst_draft_injects_locked_stack_block() -> None:
    """draft() must include the locked stack's prompt block so the
    PRD's Tech Stack section can't drift from the locked stack."""
    llm, memory, audit = _setup_llm("# PRD\n\n## Goals\n- ...")
    agent = PRDAnalyst(llm, memory, audit)
    stack = LockedStack(
        tier="T0",
        app_class="web",
        language="TypeScript",
        primary_framework="Node CLI (tsx)",
        package_manager="npm",
        test_cmd="npx vitest run",
        run_cmd="npx tsx src/main.ts",
        key_libraries=["commander"],
    )

    out = agent.draft(
        intent_md="# Project Intent\n\n## Goal\nA CLI notes app.\n",
        stack=stack,
        project_name="notes",
        project_id="P-1",
    )

    sys_prompt, user_prompt = llm.calls[0]
    assert "PRD Template" in sys_prompt
    assert "Locked intent" in user_prompt
    assert "Locked stack" in user_prompt
    # The stack block must surface specific stack fields, not just a generic mention.
    assert "TypeScript" in user_prompt
    assert "npx vitest run" in user_prompt
    assert out.startswith("# PRD")
