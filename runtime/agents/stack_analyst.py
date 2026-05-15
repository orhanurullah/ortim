# SPDX-License-Identifier: FSL-1.1-Apache-2.0
# Copyright (c) 2026 ortim.dev
"""StackAnalyst — second dialog state.

Proposes a LockedStack JSON object that downstream layers (bootstrap,
Architect Call 2, Documenter) treat as the single source of truth for
language, framework, test_cmd, run_cmd, and deploy target. User
override during `ortim refine` is FINAL — the agent must never silently
push back.
"""

from __future__ import annotations

from runtime.architecture import LockedStack, TierScore
from runtime.audit import AuditLogger
from runtime.babel.intent import _strip_code_fences
from runtime.llm import LLMClient
from runtime.memory import MemoryLoader


class StackAnalyst:
    def __init__(
        self,
        llm: LLMClient,
        memory: MemoryLoader,
        audit: AuditLogger,
    ) -> None:
        self.llm = llm
        self.memory = memory
        self.audit = audit

    def propose(
        self,
        intent_md: str,
        tier_suggestion: TierScore,
        app_class: str,
        project_id: str,
    ) -> LockedStack:
        """Initial stack proposal — no prior stack, no feedback."""
        return self._call(
            intent_md=intent_md,
            tier_suggestion=tier_suggestion,
            app_class=app_class,
            previous_stack=None,
            user_feedback=None,
            project_id=project_id,
            event="stack_analyst_propose",
        )

    def refine(
        self,
        previous_stack: LockedStack,
        intent_md: str,
        user_feedback: str,
        tier_suggestion: TierScore,
        project_id: str,
    ) -> LockedStack:
        """Apply user feedback. Override fields are FINAL — agent must
        not push back. See agents/stack_analyst.md hard rules."""
        return self._call(
            intent_md=intent_md,
            tier_suggestion=tier_suggestion,
            app_class=previous_stack.app_class,
            previous_stack=previous_stack,
            user_feedback=user_feedback,
            project_id=project_id,
            event="stack_analyst_refine",
        )

    def _call(
        self,
        *,
        intent_md: str,
        tier_suggestion: TierScore,
        app_class: str,
        previous_stack: LockedStack | None,
        user_feedback: str | None,
        project_id: str,
        event: str,
    ) -> LockedStack:
        system_prompt = self.memory.load_agent_prompt("stack_analyst")
        principles = self.memory.load_l1_principles()
        tier_brief = self._tier_brief(tier_suggestion)
        full_system = (
            f"{system_prompt}\n\n"
            f"## L1 Immutable Principles\n\n{principles}\n\n"
            f"## Deterministic Tier Suggestion (you may keep or override)\n\n"
            f"{tier_brief}\n"
            f"App class suggestion: {app_class}\n"
        )

        sections: list[str] = []
        sections.append(
            "Locked intent (authoritative — do not contradict):\n"
            "```markdown\n" + intent_md.strip() + "\n```\n"
        )
        if previous_stack is not None:
            sections.append(
                "Previous stack proposal:\n```json\n"
                + previous_stack.model_dump_json(indent=2)
                + "\n```\n"
            )
        if user_feedback:
            sections.append(
                "User feedback (FINAL — apply verbatim; this overrides the "
                "tier suggestion AND the previous stack wherever they "
                "conflict):\n```\n"
                + user_feedback.strip()
                + "\n```\n"
            )
        sections.append(
            "Emit ONLY the LockedStack JSON object matching the schema in "
            "your system prompt. No markdown fences, no prose."
        )
        user_prompt = "\n".join(sections)

        response = self.llm.call(
            system=full_system,
            user=user_prompt,
            temperature=0.0,
            max_tokens=1500,
        )
        cleaned = _strip_code_fences(response.text)
        stack = LockedStack.model_validate_json(cleaned)

        self.audit.log(
            event,
            project_id=project_id,
            tier_suggestion=tier_suggestion.tier.value,
            tier_chosen=stack.tier,
            app_class=stack.app_class,
            language=stack.language,
            had_previous=previous_stack is not None,
            had_feedback=bool(user_feedback),
            **response.audit_fields(),
        )
        return stack

    @staticmethod
    def _tier_brief(tier_score: TierScore) -> str:
        pros = "\n".join(f"- {p}" for p in tier_score.pros) or "- (none recorded)"
        cons = "\n".join(f"- {c}" for c in tier_score.cons) or "- (none recorded)"
        return (
            f"**Tier:** {tier_score.tier.value} — {tier_score.name}\n"
            f"**Score:** {tier_score.score}\n\n"
            f"**Pros:**\n{pros}\n\n"
            f"**Cons:**\n{cons}\n"
        )
