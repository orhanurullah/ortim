# SPDX-License-Identifier: FSL-1.1-Apache-2.0
# Copyright (c) 2026 ortim.dev
"""M3.1.0c — ExtenderAgent prompt + audit + BLOCKED_STACK detection.

FakeLLM-driven tests; no API key needed. Pins:
- agents/extender.md is loaded into the system prompt.
- Locked artifacts (intent + PRD + stack) reach the user prompt verbatim.
- `cycle` reaches the prompt as a literal integer.
- BLOCKED-STACK marker round-trips through the agent without mangling.
- audit event includes cycle + blocked_stack flag.
"""

from __future__ import annotations

import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from ortim.architecture import LockedStack  # noqa: E402
from ortim.audit import AuditLogger  # noqa: E402
from ortim.codebase import CodebaseSummary  # noqa: E402
from ortim.extend import BLOCKED_STACK_MARKER, ExtenderAgent  # noqa: E402
from ortim.llm.client import LLMResponse  # noqa: E402
from ortim.memory import MemoryLoader  # noqa: E402


@dataclass
class FakeLLM:
    response_text: str = "## Extension 1 — placeholder\n"
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


def _setup(text: str = "## Extension 1 — placeholder\n") -> tuple[
    FakeLLM, ExtenderAgent, AuditLogger, Path
]:
    tmp = Path(tempfile.mkdtemp())
    audit = AuditLogger(path=tmp / "audit.jsonl")
    memory = MemoryLoader(REPO_ROOT)
    llm = FakeLLM(response_text=text)
    agent = ExtenderAgent(llm, memory, audit)
    return llm, agent, audit, tmp


def _stack() -> LockedStack:
    return LockedStack(
        tier="T2",
        app_class="web",
        language="TypeScript",
        primary_framework="React + Vite",
        package_manager="npm",
        test_cmd="npx vitest run",
        run_cmd="npm run dev",
        key_libraries=["idb", "zod"],
    )


# ---- Loading + prompt assembly ----


def test_extender_agent_loads_extender_md_into_system_prompt() -> None:
    """The system prompt must include the body of agents/extender.md so
    the LLM gets the role + Hard Boundaries + delta section structure."""
    llm, agent, _, _ = _setup()
    agent.draft_delta_prd(
        feature_brief="Add tagging to tasks",
        existing_intent_md="# Project Intent\n\n## Goal\nA todo app.\n",
        existing_prd="# PRD\n## 1. Problem\nUsers need todos.\n",
        locked_stack=_stack(),
        cycle=1,
        project_id="P-1",
    )
    system, _ = llm.calls[0]
    # Marker phrases from agents/extender.md.
    assert "Extender Agent" in system
    assert "Hard Boundaries" in system
    assert "draft_delta_prd" in system
    assert "draft_delta_rfc" in system
    assert "BLOCKED-STACK" in system or BLOCKED_STACK_MARKER in system


def test_extender_agent_includes_l1_principles_block() -> None:
    """Like other agents, the L1 principles block is appended so the
    Extender doesn't silently drop project-wide invariants in deltas."""
    llm, agent, _, _ = _setup()
    agent.draft_delta_prd(
        feature_brief="Add archive",
        existing_intent_md="# Project Intent\n",
        existing_prd="# PRD\n",
        locked_stack=_stack(),
        cycle=1,
        project_id="P-1",
    )
    system, _ = llm.calls[0]
    assert "L1 Immutable Principles" in system


# ---- draft_delta_prd ----


def test_draft_delta_prd_threads_brief_and_locked_artifacts() -> None:
    """The user prompt must carry the new feature brief verbatim plus
    the entire existing intent + PRD + stack."""
    llm, agent, _, _ = _setup()
    agent.draft_delta_prd(
        feature_brief="Add tagging to tasks so users can categorize todos",
        existing_intent_md="# Project Intent\n\n## Goal\nA personal todo app.\n",
        existing_prd="# PRD: web-todo\n\n## 1. Problem\nUsers need todos.\n",
        locked_stack=_stack(),
        cycle=2,
        project_id="P-1",
    )
    _, user = llm.calls[0]
    # Brief verbatim
    assert "Add tagging to tasks so users can categorize todos" in user
    # Existing artifacts present (substrings)
    assert "personal todo app" in user
    assert "web-todo" in user
    # Stack content
    assert "TypeScript" in user
    assert "idb" in user and "zod" in user
    # Cycle number reaches prompt as literal — header instruction must
    # name "Extension 2" so the LLM produces the right header.
    assert "Extension 2" in user


def test_draft_delta_prd_truncates_oversized_existing_artifact() -> None:
    """When existing PRD exceeds the budget, prompt must include a
    truncation marker so the LLM knows it's not seeing the whole thing
    (and the operator sees it in audits)."""
    llm, agent, _, _ = _setup()
    huge_prd = "# PRD\n\n" + ("padding line " * 100 + "\n") * 200  # ~250 KB
    agent.draft_delta_prd(
        feature_brief="add archive",
        existing_intent_md="# intent\n",
        existing_prd=huge_prd,
        locked_stack=_stack(),
        cycle=1,
        project_id="P-1",
    )
    _, user = llm.calls[0]
    assert "truncated" in user.lower()


# ---- draft_delta_rfc ----


def test_draft_delta_rfc_threads_delta_prd_and_existing_rfc() -> None:
    """RFC delta drafting must see the just-approved delta PRD section
    AND the existing shipped RFC so it can produce a coherent module
    breakdown delta."""
    llm, agent, _, _ = _setup(
        text="## Extension 1 — Tagging\n\n### Module Breakdown (delta)\n"
    )
    delta_prd = "## Extension 1 — Tagging\n\n### Goal\nAdd tags.\n"
    existing_rfc = "# RFC\n\n## 4. Tech Stack\n- TypeScript / React + Vite\n"
    agent.draft_delta_rfc(
        delta_prd_section=delta_prd,
        existing_rfc=existing_rfc,
        existing_codebase_summary=None,
        locked_stack=_stack(),
        cycle=1,
        project_id="P-1",
    )
    _, user = llm.calls[0]
    assert "Tagging" in user
    assert "## 4. Tech Stack" in user
    # Cycle 1 wired into instruction
    assert "Extension 1" in user


def test_draft_delta_rfc_includes_codebase_summary_when_present() -> None:
    """When CodebaseSummary is provided, it must reach the prompt under
    the 'existing codebase' header so the LLM can ground the module
    breakdown in real on-disk modules."""
    from ortim.codebase.schema import FrameworkHint, ModuleSymbols

    llm, agent, _, _ = _setup()
    summary = CodebaseSummary(
        root="/tmp/fake",
        scanned_at="2026-05-14T00:00:00Z",
        file_count=2,
        truncated=False,
        languages={".ts": 1, ".tsx": 1},
        modules=[
            ModuleSymbols(
                path="task-service/index.ts",
                public_names=["createTask", "deleteTask"],
            ),
            ModuleSymbols(
                path="task-ui/App.tsx",
                public_names=["App"],
            ),
        ],
        frameworks=[FrameworkHint(name="react", confidence=1.0, evidence=[])],
        app_class_hint="web",
    )
    agent.draft_delta_rfc(
        delta_prd_section="## Extension 1 — Archive\n",
        existing_rfc="# RFC\n",
        existing_codebase_summary=summary,
        locked_stack=_stack(),
        cycle=1,
        project_id="P-1",
    )
    _, user = llm.calls[0]
    assert "task-service" in user or "task-ui" in user
    assert "ground truth" in user.lower() or "existing codebase" in user.lower()


def test_draft_delta_rfc_omits_codebase_block_when_summary_is_none() -> None:
    """When summary=None (test-only case), prompt must NOT contain the
    'existing codebase' header — the LLM shouldn't be told 'here are the
    existing modules' if we don't actually know."""
    llm, agent, _, _ = _setup()
    agent.draft_delta_rfc(
        delta_prd_section="## Extension 1 — Archive\n",
        existing_rfc="# RFC\n",
        existing_codebase_summary=None,
        locked_stack=_stack(),
        cycle=1,
        project_id="P-1",
    )
    _, user = llm.calls[0]
    assert "Existing codebase" not in user


# ---- BLOCKED-STACK detection ----


def test_blocked_stack_marker_round_trips_and_audits() -> None:
    """When the LLM emits ONLY the BLOCKED-STACK marker, the agent must
    return that marker verbatim and the audit event must carry
    blocked_stack=true so downstream HITL routing fires."""
    blocked_response = (
        f"{BLOCKED_STACK_MARKER}: lodash — feature requires deep object diffing"
    )
    llm, agent, audit, tmp = _setup(text=blocked_response)
    out = agent.draft_delta_prd(
        feature_brief="add deep undo/redo with lodash",
        existing_intent_md="# Intent\n",
        existing_prd="# PRD\n",
        locked_stack=_stack(),
        cycle=1,
        project_id="P-1",
    )
    assert out.startswith(BLOCKED_STACK_MARKER)
    # Audit log line carries the blocked_stack flag.
    log_lines = (tmp / "audit.jsonl").read_text(encoding="utf-8").splitlines()
    assert any('"blocked_stack": true' in line for line in log_lines), log_lines


def test_normal_section_response_audits_blocked_stack_false() -> None:
    """Counter-example: a normal markdown section MUST NOT trigger the
    blocked-stack flag, otherwise every successful extension would be
    misrouted to HITL."""
    normal = "## Extension 1 — Tagging\n\n### Goal\nAdd tags.\n"
    llm, agent, audit, tmp = _setup(text=normal)
    agent.draft_delta_prd(
        feature_brief="add tagging",
        existing_intent_md="# Intent\n",
        existing_prd="# PRD\n",
        locked_stack=_stack(),
        cycle=1,
        project_id="P-1",
    )
    log_lines = (tmp / "audit.jsonl").read_text(encoding="utf-8").splitlines()
    assert any('"blocked_stack": false' in line for line in log_lines), log_lines
