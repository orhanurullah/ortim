# SPDX-License-Identifier: FSL-1.1-Apache-2.0
# Copyright (c) 2026 ortim.dev
"""Smoke tests for ArchitectAgent's brownfield codebase integration (M1).

Three guarantees:
  - extract_inputs injects an "Existing codebase summary" block into the
    user prompt when a CodebaseSummary is provided
  - draft_rfc loads the tier-specific golden-path doc into the system prompt
    so the LLM can see Flutter-specific conventions for an M1 RFC
  - extract_inputs without a codebase keeps the user prompt clean — pre-M1
    callers must not see the new block
"""

from __future__ import annotations

import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from ortim.agents.architect import ArchitectAgent  # noqa: E402
from ortim.architecture import Tier, TierScore  # noqa: E402
from ortim.audit import AuditLogger  # noqa: E402
from ortim.codebase import (  # noqa: E402
    CodebaseSummary,
    FrameworkHint,
    ModuleSymbols,
)
from ortim.llm.client import LLMResponse  # noqa: E402
from ortim.memory import MemoryLoader  # noqa: E402


@dataclass
class CapturingLLM:
    """Stand-in for LLMClient that records every call's system+user prompt."""

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


def _flutter_summary() -> CodebaseSummary:
    return CodebaseSummary(
        root="/tmp/flutter-app",
        scanned_at="2026-05-08T00:00:00Z",
        file_count=42,
        truncated=False,
        languages={".dart": 30, ".yaml": 2, ".gradle": 3},
        frameworks=[
            FrameworkHint(
                name="flutter",
                confidence=1.0,
                evidence=["pubspec.yaml:flutter_sdk"],
                version="3.16.0",
            ),
        ],
        modules=[
            ModuleSymbols(
                path="lib/features/home/home_page.dart",
                public_names=["HomePage", "HomeController"],
                imports=[],
            ),
            ModuleSymbols(
                path="lib/features/auth/login_page.dart",
                public_names=["LoginPage", "AuthRepository"],
                imports=[],
            ),
        ],
        deps_manifests={"pubspec.yaml": "name: my_app\n"},
        app_class_hint="mobile",
    )


def _setup() -> tuple[CapturingLLM, ArchitectAgent]:
    tmp = tempfile.mkdtemp()
    audit = AuditLogger(path=Path(tmp) / "audit.jsonl")
    memory = MemoryLoader(REPO_ROOT)
    llm = CapturingLLM(
        response_text='{"has_persistent_state": false, "has_auth": false, '
        '"app_class": "mobile", "target_platforms": ["ios","android"]}'
    )
    return llm, ArchitectAgent(llm, memory, audit)


def test_extract_inputs_injects_codebase_block() -> None:
    """Test 22: brownfield → user prompt carries the summary block."""
    llm, architect = _setup()
    summary = _flutter_summary()

    architect.extract_inputs(
        prd_markdown="# PRD\nMobile app",
        project_id="P-brown",
        codebase=summary,
    )

    assert llm.calls, "Architect should have called the LLM"
    _, user_prompt = llm.calls[0]
    assert "Existing codebase summary" in user_prompt, user_prompt[:300]
    assert "flutter" in user_prompt.lower(), user_prompt[:500]
    assert "lib/features/home" in user_prompt, user_prompt[:500]


def test_draft_rfc_loads_tier_doc_into_system_prompt() -> None:
    """Test 23: M1 RFC drafting → Flutter golden-path doc lands in system."""
    llm, architect = _setup()
    llm.response_text = "# RFC\n\n## §7 Module Breakdown\n..."
    summary = _flutter_summary()
    tier_score = TierScore(
        tier=Tier.M1,
        score=85,
        pros=["cross-platform"],
        cons=[],
    )

    architect.draft_rfc(
        prd_markdown="# PRD\nFlutter todo app",
        tier_score=tier_score,
        project_name="todo-app",
        project_id="P-flutter",
        codebase=summary,
    )

    assert llm.calls, "Architect should have called the LLM"
    system_prompt, user_prompt = llm.calls[0]
    # M1 tier doc must be loaded — it mentions Flutter conventions
    assert "Selected Tier Reference Doc" in system_prompt, system_prompt[:400]
    # The M1 doc encodes Flutter conventions (Riverpod, features layout) —
    # if Architect is fed a generic tier brief we'd see neither token.
    sys_lower = system_prompt.lower()
    assert "riverpod" in sys_lower or "features/" in sys_lower, (
        "M1 tier doc should reference Flutter conventions (Riverpod / features layout)"
    )
    # Codebase summary lands in user prompt for §7 module grounding
    assert "Existing codebase summary" in user_prompt, user_prompt[:300]


def test_extract_inputs_without_codebase_omits_block() -> None:
    """Test 24: pre-M1 path (codebase=None) leaves the user prompt unchanged."""
    llm, architect = _setup()

    architect.extract_inputs(
        prd_markdown="# PRD\nA SaaS",
        project_id="P-greenfield",
        codebase=None,
    )

    assert llm.calls, "Architect should have called the LLM"
    _, user_prompt = llm.calls[0]
    assert "Existing codebase summary" not in user_prompt, user_prompt[:300]


# ---------- Item 17: Architect Call 2 tier × stack hard constraint ----------


def test_draft_rfc_t2_web_injects_hard_stack_constraint() -> None:
    """Greenfield T2/web: Architect Call 2 system prompt must carry the hard
    stack constraint from `stack_constraint("T2", "web")`. Without this,
    Architect can pick Go for a T2/web project (observed in
    todo-greenfield-3) and break bootstrap's Node/TS scaffolding."""
    llm, architect = _setup()
    llm.response_text = "# RFC\n..."
    tier_score = TierScore(tier=Tier.T2, score=100, pros=["BaaS"], cons=[])

    architect.draft_rfc(
        prd_markdown="# PRD\nA todo SaaS",
        tier_score=tier_score,
        project_name="todo-saas",
        project_id="P-greenfield-t2",
        app_class="web",
        codebase=None,
    )

    assert llm.calls, "Architect should have called the LLM"
    system_prompt, _ = llm.calls[0]
    assert "Tier × Stack Hard Constraint" in system_prompt, system_prompt[:600]
    assert "TypeScript" in system_prompt, system_prompt[-800:]
    assert "Supabase" in system_prompt, system_prompt[-800:]
    # Brownfield-only "advisory" wording must NOT appear on greenfield path
    assert "advisory for brownfield" not in system_prompt


def test_draft_rfc_brownfield_constraint_is_advisory_not_hard() -> None:
    """Brownfield: existing codebase already pins the stack — the (tier,
    app_class) constraint must be advisory ('prefer matching') so we don't
    contradict the detected frameworks."""
    llm, architect = _setup()
    llm.response_text = "# RFC\n..."
    summary = _flutter_summary()
    tier_score = TierScore(tier=Tier.T2, score=100, pros=["BaaS"], cons=[])

    architect.draft_rfc(
        prd_markdown="# PRD\nFeature X",
        tier_score=tier_score,
        project_name="extend-flutter",
        project_id="P-brownfield",
        app_class="mobile",  # M1 mobile not in matrix; T2 mobile is
        codebase=summary,
    )

    system_prompt, _ = llm.calls[0]
    # T2/mobile constraint is in the matrix; should appear with advisory wording
    assert "advisory for brownfield" in system_prompt, system_prompt[-1000:]
    assert "Hard Constraint" not in system_prompt
