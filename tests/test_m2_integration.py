# SPDX-License-Identifier: FSL-1.1-Apache-2.0
# Copyright (c) 2026 ortim.dev
"""M2 cross-layer integration: LockedStack is the single source of truth
for bootstrap test-cmd selection, Architect Call 2 hard constraint, and
Documenter README install/test/run commands.

These guarantees replace the legacy heuristic stack opinion layers
(_LANG_STACK_BY_TIER_APP, _infer_test_cmd_from_rfc, _TEST_CMD_BY_TIER_APP)
for the dialog flow — closing items 17 + 18a structurally.
"""

from __future__ import annotations

import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from ortim.agents.architect import ArchitectAgent  # noqa: E402
from ortim.agents.documenter import DocumenterAgent  # noqa: E402
from ortim.architecture import (  # noqa: E402
    LockedStack,
    Tier,
    TierScore,
    bootstrap_workspace_layout,
)
from ortim.audit import AuditLogger  # noqa: E402
from ortim.llm.client import LLMResponse  # noqa: E402
from ortim.memory import MemoryLoader  # noqa: E402


@dataclass
class CapturingLLM:
    response_text: str = "# RFC\n..."
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


def _go_stack() -> LockedStack:
    """User negotiated Go for a T0 CLI — the canonical case where the
    deterministic _LANG_STACK_BY_TIER_APP matrix would have picked
    something else (Python OR Bash OR Go), and the test-cmd heuristic
    might have written `npx vitest run` from RFC scan. With a
    LockedStack, neither heuristic runs."""
    return LockedStack(
        tier="T0",
        app_class="web",
        language="Go",
        primary_framework="Cobra CLI",
        package_manager="go modules",
        test_cmd="go test ./...",
        run_cmd="./bin/app",
        key_libraries=["cobra"],
        deploy_target="none",
        rationale="Single-binary CLI for solo developer; user prefers Go.",
    )


def _flutter_stack() -> LockedStack:
    return LockedStack(
        tier="M1",
        app_class="mobile",
        language="Dart",
        primary_framework="Flutter",
        package_manager="pub",
        test_cmd="flutter test",
        run_cmd="flutter run",
        key_libraries=["riverpod", "dio"],
        deploy_target="app-store",
        rationale="Cross-platform mobile, single codebase.",
    )


# ---- Bootstrap × LockedStack ----


def test_bootstrap_uses_locked_stack_test_cmd_over_matrix() -> None:
    """T2/web matrix entry says `npx vitest run`. With a LockedStack
    picking Go, bootstrap must write the LockedStack test cmd instead —
    otherwise we re-introduce the item-17 mismatch."""
    ws = Path(tempfile.mkdtemp())
    bootstrap_workspace_layout(
        ws,
        modules=["cmd"],
        tier="T2",          # matrix would suggest npx vitest run
        app_class="web",
        project_name="testproj",
        locked_stack=_go_stack(),
    )
    env_path = ws / ".ai-factory.env"
    assert env_path.exists(), ".ai-factory.env should be written"
    body = env_path.read_text(encoding="utf-8")
    assert 'AI_FACTORY_TEST_CMD="go test ./..."' in body, body
    assert "vitest" not in body, "matrix value must be overridden"


def test_bootstrap_falls_back_to_matrix_when_no_locked_stack() -> None:
    """Legacy AI_FACTORY_DIALOG_MODE=off and brownfield-no-stack flows
    must still use the matrix. Regression guard for items already shipped."""
    ws = Path(tempfile.mkdtemp())
    bootstrap_workspace_layout(
        ws,
        modules=["api"],
        tier="T2",
        app_class="web",
        project_name="legacyproj",
        locked_stack=None,
    )
    env_path = ws / ".ai-factory.env"
    assert env_path.exists()
    body = env_path.read_text(encoding="utf-8")
    assert "vitest" in body, "matrix value must surface when no LockedStack"


def test_bootstrap_locked_stack_test_cmd_works_for_mobile() -> None:
    """M1/mobile matrix has flutter test, but the LockedStack path
    should still source from the stack — confirming the override is
    universal, not just for unmatched matrix entries."""
    ws = Path(tempfile.mkdtemp())
    bootstrap_workspace_layout(
        ws,
        modules=["lib"],
        tier="M1",
        app_class="mobile",
        project_name="todoflutter",
        locked_stack=_flutter_stack(),
    )
    env_path = ws / ".ai-factory.env"
    body = env_path.read_text(encoding="utf-8")
    assert 'AI_FACTORY_TEST_CMD="flutter test"' in body


# ---- Architect Call 2 × LockedStack ----


def _setup_architect() -> tuple[CapturingLLM, ArchitectAgent]:
    tmp = tempfile.mkdtemp()
    audit = AuditLogger(path=Path(tmp) / "audit.jsonl")
    memory = MemoryLoader(REPO_ROOT)
    llm = CapturingLLM()
    return llm, ArchitectAgent(llm, memory, audit)


def test_architect_draft_rfc_with_locked_stack_injects_verbatim_block() -> None:
    """LockedStack must reach the Architect system prompt as a HARD
    constraint, NOT through the _LANG_STACK_BY_TIER_APP heuristic. The
    locked stack fields must appear in the prompt so the LLM cannot
    silently switch stacks (item 17 structural fix)."""
    llm, architect = _setup_architect()
    tier_score = TierScore(tier=Tier.T0, score=100, pros=["single binary"], cons=[])

    architect.draft_rfc(
        prd_markdown="# PRD\nA CLI todo",
        tier_score=tier_score,
        project_name="todo",
        project_id="P-locked",
        app_class="web",
        codebase=None,
        locked_stack=_go_stack(),
    )

    system_prompt, _ = llm.calls[0]
    assert "Locked Stack (HARD" in system_prompt, system_prompt[-600:]
    assert "**Language:** Go" in system_prompt
    assert "go test ./..." in system_prompt
    # The heuristic constraint block must NOT also appear — that would
    # mean we're showing two stack opinions, defeating the point.
    assert "Tier × Stack Hard Constraint" not in system_prompt
    assert "Tier × Stack Constraint (advisory" not in system_prompt


def test_architect_draft_rfc_without_locked_stack_still_uses_heuristic() -> None:
    """Greenfield-no-dialog flow must still get the heuristic constraint.
    Regression guard for shipped item 17 fix."""
    llm, architect = _setup_architect()
    tier_score = TierScore(tier=Tier.T2, score=100, pros=["BaaS"], cons=[])

    architect.draft_rfc(
        prd_markdown="# PRD\nA SaaS",
        tier_score=tier_score,
        project_name="saas",
        project_id="P-greenfield",
        app_class="web",
        codebase=None,
        locked_stack=None,
    )

    system_prompt, _ = llm.calls[0]
    assert "Tier × Stack Hard Constraint" in system_prompt
    assert "Locked Stack (HARD" not in system_prompt


# ---- Documenter × LockedStack ----


def test_documenter_locked_stack_lands_in_prompt() -> None:
    """README must derive install/test/run commands from the LockedStack,
    not guess them from a language heuristic. The stack block needs to
    reach the user prompt verbatim so the LLM honors it."""
    tmp = tempfile.mkdtemp()
    audit = AuditLogger(path=Path(tmp) / "audit.jsonl")
    memory = MemoryLoader(REPO_ROOT)
    llm = CapturingLLM(response_text="# Project\n\n## Run\n`go run main.go`\n")
    documenter = DocumenterAgent(llm, memory, audit)

    documenter.generate_readme(
        project_name="todo",
        prd_text="# PRD\n",
        rfc_text="# RFC\n",
        project_id="P-doc",
        locked_stack=_go_stack(),
    )

    _, user_prompt = llm.calls[0]
    assert "Locked Stack" in user_prompt
    assert "go test ./..." in user_prompt
    assert "./bin/app" in user_prompt
    assert "**Language:** Go" in user_prompt


def test_documenter_without_locked_stack_omits_block() -> None:
    """Legacy / brownfield calls (no LockedStack) get the prior README
    behavior — no stack block injected. The Documenter must remain a
    drop-in replacement when no stack is available."""
    tmp = tempfile.mkdtemp()
    audit = AuditLogger(path=Path(tmp) / "audit.jsonl")
    memory = MemoryLoader(REPO_ROOT)
    llm = CapturingLLM(response_text="# Project\n")
    documenter = DocumenterAgent(llm, memory, audit)

    documenter.generate_readme(
        project_name="legacy",
        prd_text="# PRD\n",
        rfc_text="# RFC\n",
        project_id="P-doc-legacy",
        locked_stack=None,
    )

    _, user_prompt = llm.calls[0]
    assert "Locked Stack" not in user_prompt
