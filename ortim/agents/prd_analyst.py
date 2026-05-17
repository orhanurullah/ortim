# SPDX-License-Identifier: FSL-1.1-Apache-2.0
# Copyright (c) 2026 ortim.dev
"""PRDAnalyst — third dialog state.

Draws on locked intent + locked stack to produce the PRD. Mirrors the
boundary of the legacy AnalystAgent (no tech invention beyond what the
stack already named) but gains a refine loop for user-driven iteration.
"""

from __future__ import annotations

from ortim.architecture import LockedStack
from ortim.audit import AuditLogger
from ortim.llm import LLMClient
from ortim.memory import MemoryLoader


class PRDAnalyst:
    def __init__(
        self,
        llm: LLMClient,
        memory: MemoryLoader,
        audit: AuditLogger,
    ) -> None:
        self.llm = llm
        self.memory = memory
        self.audit = audit

    def draft(
        self,
        intent_md: str,
        stack: LockedStack,
        project_name: str,
        project_id: str,
    ) -> str:
        """First PRD draft from locked intent + locked stack."""
        return self._call(
            intent_md=intent_md,
            stack=stack,
            project_name=project_name,
            project_id=project_id,
            previous_prd=None,
            user_feedback=None,
            event="prd_analyst_draft",
        )

    def refine(
        self,
        previous_prd: str,
        intent_md: str,
        stack: LockedStack,
        user_feedback: str,
        project_name: str,
        project_id: str,
    ) -> str:
        """Apply user feedback to an earlier PRD. Locked intent/stack
        are still authoritative; if the feedback would change them, the
        agent must emit a `**[BLOCKED]**` marker rather than rewrite."""
        return self._call(
            intent_md=intent_md,
            stack=stack,
            project_name=project_name,
            project_id=project_id,
            previous_prd=previous_prd,
            user_feedback=user_feedback,
            event="prd_analyst_refine",
        )

    def _call(
        self,
        *,
        intent_md: str,
        stack: LockedStack,
        project_name: str,
        project_id: str,
        previous_prd: str | None,
        user_feedback: str | None,
        event: str,
    ) -> str:
        system_prompt = self.memory.load_agent_prompt("prd_analyst")
        principles = self.memory.load_l1_principles()
        template = self.memory.load_template("PRD")

        full_system = (
            f"{system_prompt}\n\n"
            f"## L1 Immutable Principles\n\n{principles}\n\n"
            f"## PRD Template (use this exact structure)\n\n{template}"
        )

        sections: list[str] = [f"Project name: {project_name}\n"]
        sections.append(
            "Locked intent (authoritative — drives Goals / Users / Features):\n"
            "```markdown\n" + intent_md.strip() + "\n```\n"
        )
        sections.append(
            "Locked stack (authoritative — Tech Stack section copies from here):\n"
            + stack.to_prompt_block()
        )
        if previous_prd:
            sections.append(
                "Previous PRD (refine — preserve unrelated sections verbatim):\n"
                "```markdown\n" + previous_prd.strip() + "\n```\n"
            )
        if user_feedback:
            sections.append(
                "User feedback (apply if it stays inside the locked "
                "intent + stack; otherwise emit `**[BLOCKED]**`):\n"
                "```\n" + user_feedback.strip() + "\n```\n"
            )
        sections.append(
            "Produce the PRD as markdown using the template structure exactly. "
            "Acceptance Criteria MUST be binary-checkable (regex / exit code / "
            "JSON shape / file existence / function signature). Avoid the "
            "banned wording list in your system prompt."
        )
        user_prompt = "\n".join(sections)

        response = self.llm.call(
            system=full_system,
            user=user_prompt,
            temperature=0.3,
            max_tokens=4000,
        )

        self.audit.log(
            event,
            project_id=project_id,
            had_previous=previous_prd is not None,
            had_feedback=bool(user_feedback),
            stack_tier=stack.tier,
            stack_language=stack.language,
            **response.audit_fields(),
        )
        return response.text
