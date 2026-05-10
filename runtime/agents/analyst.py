# SPDX-License-Identifier: FSL-1.1-Apache-2.0
# Copyright (c) 2026 ortim.dev
"""Analyst agent — converts StructuredIntent to a PRD draft.

Boundary: the Analyst MUST NOT make technical or architectural decisions.
That is the Architect's job (next iteration). Boundary is enforced via:
1. Analyst system prompt (agents/analyst.md) explicitly forbids it
2. PRD template lacks tech-stack sections
3. Code Reviewer (future iter) flags any tech-stack mention in PRD
"""

from __future__ import annotations

from runtime.audit import AuditLogger
from runtime.babel import StructuredIntent
from runtime.llm import LLMClient
from runtime.memory import MemoryLoader


class AnalystAgent:
    def __init__(
        self,
        llm: LLMClient,
        memory: MemoryLoader,
        audit: AuditLogger,
    ) -> None:
        self.llm = llm
        self.memory = memory
        self.audit = audit

    def draft_prd(
        self,
        intent: StructuredIntent,
        project_name: str,
        project_id: str,
    ) -> str:
        system_prompt = self.memory.load_agent_prompt("analyst")
        principles = self.memory.load_l1_principles()
        template = self.memory.load_template("PRD")

        full_system = (
            f"{system_prompt}\n\n"
            f"## L1 Immutable Principles\n\n{principles}\n\n"
            f"## PRD Template (use this exact structure)\n\n{template}"
        )

        user_prompt = (
            f"Project name: {project_name}\n\n"
            "Structured intent (from Babel):\n"
            f"{intent.model_dump_json(indent=2)}\n\n"
            "Produce the PRD as markdown using the template above. "
            "For any field not derivable from the intent, write `**[NEEDS-INPUT]**` "
            "followed by a specific question to the user. Do not invent requirements."
        )

        response = self.llm.call(
            system=full_system,
            user=user_prompt,
            temperature=0.3,
            max_tokens=4000,
        )

        self.audit.log(
            "analyst_prd_draft",
            project_id=project_id,
            **response.audit_fields(),
        )
        return response.text
