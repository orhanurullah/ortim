# SPDX-License-Identifier: FSL-1.1-Apache-2.0
# Copyright (c) 2026 ortim.dev
"""ExtenderAgent — produces delta PRD/RFC sections for extend cycles.

Two methods, both LLM-backed:
- `draft_delta_prd(...)`  → markdown section to append to PRD.md
- `draft_delta_rfc(...)`  → markdown section to append to RFC.md

Both share a single system prompt at `agents/extender.md`. The agent
NEVER rewrites the original artifacts — output is the section appended,
nothing else changes the file.
"""

from __future__ import annotations

from runtime.architecture import LockedStack
from runtime.audit import AuditLogger
from runtime.codebase import CodebaseSummary
from runtime.llm import LLMClient
from runtime.memory import MemoryLoader

# Soft cap on existing-PRD/RFC content sent to the model. Prevents prompt
# bloat when projects accumulate many extend cycles. Truncation prefers
# the head (first cycle is most stable context); tail truncation is
# acceptable because newer cycles are visible in the user prompt's
# `cycle` argument anyway.
_EXISTING_ARTIFACT_BUDGET_BYTES = 12_000
_CODEBASE_PROMPT_BUDGET_BYTES = 2_000

# The marker the agent emits when a feature legitimately requires a
# library not in the locked stack. Runtime detects this and routes to
# HITL rather than appending the marker to PRD/RFC.
BLOCKED_STACK_MARKER = "**[BLOCKED-STACK]**"


def _truncate(text: str, budget: int) -> str:
    if len(text) <= budget:
        return text
    head = text[:budget]
    return (
        head
        + f"\n\n*(... truncated; original artifact is {len(text)} bytes, "
        + f"budget {budget})*"
    )


class ExtenderAgent:
    """Drafts delta PRD/RFC sections for `ortim extend` cycles."""

    def __init__(
        self,
        llm: LLMClient,
        memory: MemoryLoader,
        audit: AuditLogger,
    ) -> None:
        self.llm = llm
        self.memory = memory
        self.audit = audit

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def draft_delta_prd(
        self,
        feature_brief: str,
        existing_intent_md: str,
        existing_prd: str,
        locked_stack: LockedStack,
        cycle: int,
        project_id: str,
    ) -> str:
        """Returns markdown beginning with `## Extension <cycle> — ...`.

        If the feature legitimately requires a library outside the locked
        stack, the agent returns ONLY the `**[BLOCKED-STACK]**: <lib>` marker
        — the runtime detects this and routes to HITL instead of writing
        the marker into PRD.md.
        """
        sections: list[str] = [
            f"You are drafting Extension cycle {cycle} for project "
            f"{project_id}.\n",
            f"## New feature brief\n```\n{feature_brief.strip()}\n```\n",
            "## Locked intent (authoritative — do not contradict)\n"
            "```markdown\n" + existing_intent_md.strip() + "\n```\n",
            "## Existing PRD (authoritative — do not modify; reference only)\n"
            "```markdown\n"
            + _truncate(existing_prd.strip(), _EXISTING_ARTIFACT_BUDGET_BYTES)
            + "\n```\n",
            "## Locked stack (authoritative — never deviate)\n"
            + locked_stack.to_prompt_block(),
            "## Task\n"
            f"Produce a markdown section beginning with `## Extension {cycle} —"
            " <feature title>`. Follow the structure for `draft_delta_prd` in"
            " your system prompt. Output the section ONLY (or, if the feature"
            " requires a stack-not-listed library, output ONLY the"
            f" `{BLOCKED_STACK_MARKER}` marker).",
        ]
        user_prompt = "\n\n".join(sections)
        return self._call(
            user_prompt=user_prompt,
            event="extend_prd_delta_drafted",
            project_id=project_id,
            cycle=cycle,
            stack_tier=locked_stack.tier,
            stack_language=locked_stack.language,
        )

    def draft_delta_rfc(
        self,
        delta_prd_section: str,
        existing_rfc: str,
        existing_codebase_summary: CodebaseSummary | None,
        locked_stack: LockedStack,
        cycle: int,
        project_id: str,
    ) -> str:
        """Returns markdown beginning with `## Extension <cycle> — ...`.

        `existing_codebase_summary` is the M1 brownfield-style scan of the
        shipped workspace. Pass `None` only in tests; production callers
        always have it because the workspace exists by definition (it's
        the project being extended)."""
        codebase_block = ""
        if existing_codebase_summary is not None:
            codebase_block = (
                "## Existing codebase (ground truth for which modules exist)\n"
                + existing_codebase_summary.to_prompt_text(
                    _CODEBASE_PROMPT_BUDGET_BYTES
                )
                + "\n"
            )

        sections: list[str] = [
            f"You are drafting Extension cycle {cycle} RFC delta for project "
            f"{project_id}.\n",
            "## Delta PRD section (just approved at G1)\n"
            "```markdown\n" + delta_prd_section.strip() + "\n```\n",
            "## Existing RFC (authoritative — do not modify; reference only)\n"
            "```markdown\n"
            + _truncate(existing_rfc.strip(), _EXISTING_ARTIFACT_BUDGET_BYTES)
            + "\n```\n",
            codebase_block,
            "## Locked stack (authoritative — never deviate)\n"
            + locked_stack.to_prompt_block(),
            "## Task\n"
            f"Produce a markdown section beginning with `## Extension {cycle} —"
            " <feature title>`. Follow the structure for `draft_delta_rfc` in"
            " your system prompt. Output the section ONLY (or the"
            f" `{BLOCKED_STACK_MARKER}` marker if the feature requires an"
            " unsupported library).",
        ]
        user_prompt = "\n\n".join(s for s in sections if s)
        return self._call(
            user_prompt=user_prompt,
            event="extend_rfc_delta_drafted",
            project_id=project_id,
            cycle=cycle,
            stack_tier=locked_stack.tier,
            stack_language=locked_stack.language,
        )

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _call(
        self,
        *,
        user_prompt: str,
        event: str,
        project_id: str,
        cycle: int,
        stack_tier: str,
        stack_language: str,
    ) -> str:
        system_prompt = self.memory.load_agent_prompt("extender")
        principles = self.memory.load_l1_principles()
        full_system = (
            f"{system_prompt}\n\n"
            f"## L1 Immutable Principles\n\n{principles}"
        )
        response = self.llm.call(
            system=full_system,
            user=user_prompt,
            temperature=0.3,
            max_tokens=4000,
        )
        text = response.text.strip()
        is_blocked = text.startswith(BLOCKED_STACK_MARKER)
        self.audit.log(
            event,
            project_id=project_id,
            cycle=cycle,
            stack_tier=stack_tier,
            stack_language=stack_language,
            blocked_stack=is_blocked,
            **response.audit_fields(),
        )
        return text
