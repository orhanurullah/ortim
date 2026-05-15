# SPDX-License-Identifier: FSL-1.1-Apache-2.0
# Copyright (c) 2026 ortim.dev
"""IntentAnalyst — first dialog state.

Refines `StructuredIntent` (from Babel) into a markdown intent summary
the user can iterate on via `ortim refine <id>`. The boundary mirrors
agents/analyst.md: no tech stack here. That is the StackAnalyst's job.
"""

from __future__ import annotations

from runtime.audit import AuditLogger
from runtime.babel import StructuredIntent
from runtime.llm import LLMClient
from runtime.memory import MemoryLoader


class IntentAnalyst:
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
        intent: StructuredIntent,
        project_name: str,
        project_id: str,
    ) -> str:
        """Initial intent summary from Babel output — no prior md, no feedback."""
        return self._call(
            project_name=project_name,
            project_id=project_id,
            structured_intent=intent,
            previous_md=None,
            user_feedback=None,
            event="intent_analyst_draft",
        )

    def refine(
        self,
        previous_md: str,
        intent: StructuredIntent,
        user_feedback: str,
        project_name: str,
        project_id: str,
    ) -> str:
        """Apply user feedback to the prior intent.md. Empty feedback is
        treated the same as a regenerate request — caller should usually
        prevent that at the CLI layer."""
        return self._call(
            project_name=project_name,
            project_id=project_id,
            structured_intent=intent,
            previous_md=previous_md,
            user_feedback=user_feedback,
            event="intent_analyst_refine",
        )

    def _call(
        self,
        *,
        project_name: str,
        project_id: str,
        structured_intent: StructuredIntent,
        previous_md: str | None,
        user_feedback: str | None,
        event: str,
    ) -> str:
        system_prompt = self.memory.load_agent_prompt("intent_analyst")
        principles = self.memory.load_l1_principles()
        full_system = (
            f"{system_prompt}\n\n"
            f"## L1 Immutable Principles\n\n{principles}"
        )

        sections: list[str] = [f"Project name: {project_name}\n"]
        sections.append(
            "Structured intent (from Babel — authoritative source):\n"
            f"{structured_intent.model_dump_json(indent=2)}\n"
        )
        if previous_md:
            sections.append(
                "Previous intent summary (refine this — do not rewrite "
                "unrelated sections):\n```markdown\n"
                + previous_md.strip()
                + "\n```\n"
            )
        if user_feedback:
            sections.append(
                "User feedback (apply verbatim; overrides earlier turns "
                "wherever they conflict):\n"
                f"```\n{user_feedback.strip()}\n```\n"
            )
        sections.append(
            "Produce the intent summary as markdown using the template "
            "in your system prompt. Mark genuinely missing fields as "
            "`**[NEEDS-INPUT]**` with a specific clarifying question."
        )
        user_prompt = "\n".join(sections)

        response = self.llm.call(
            system=full_system,
            user=user_prompt,
            temperature=0.3,
            max_tokens=2000,
        )

        self.audit.log(
            event,
            project_id=project_id,
            had_previous=previous_md is not None,
            had_feedback=bool(user_feedback),
            **response.audit_fields(),
        )
        return response.text.strip()
