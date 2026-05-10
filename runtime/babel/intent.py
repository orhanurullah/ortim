# SPDX-License-Identifier: FSL-1.1-Apache-2.0
# Copyright (c) 2026 ortim.dev
"""Babel layer — Turkish brief → structured English intent.

Solves the L1-token-cost-of-non-English problem by normalizing the user's
free-form Turkish into a strict English JSON schema that all downstream
agents consume.

Round-trip TR validation lets the user catch misinterpretation before any
PRD/RFC/code is written.
"""

from __future__ import annotations

from pydantic import BaseModel, Field, ValidationError

from runtime.audit import AuditLogger
from runtime.llm import LLMClient
from runtime.memory import MemoryLoader


class StructuredIntent(BaseModel):
    goal: str
    target_users: list[str] = Field(default_factory=list)
    must_have_features: list[str] = Field(default_factory=list)
    nice_to_have_features: list[str] = Field(default_factory=list)
    explicit_non_goals: list[str] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)
    inferred_compliance: list[str] = Field(default_factory=list)
    inferred_scale: str = "unknown"
    open_questions: list[str] = Field(default_factory=list)


def _strip_code_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        first_newline = text.find("\n")
        if first_newline != -1:
            text = text[first_newline + 1 :]
        if text.endswith("```"):
            text = text[: -3]
    return text.strip()


class BabelLayer:
    def __init__(
        self,
        llm: LLMClient,
        memory: MemoryLoader,
        audit: AuditLogger,
    ) -> None:
        self.llm = llm
        self.memory = memory
        self.audit = audit

    def extract(self, turkish_brief: str, project_id: str) -> StructuredIntent:
        system_prompt = self.memory.load_agent_prompt("babel")
        glossary = self.memory.load_glossary()
        if glossary:
            system_prompt = f"{system_prompt}\n\n## Glossary (TR-EN)\n\n{glossary}"

        user_prompt = (
            "Turkish brief from user:\n\n"
            f"```\n{turkish_brief}\n```\n\n"
            "Extract structured intent. Output ONLY a valid JSON object matching the "
            "StructuredIntent schema. No prose, no markdown fences, no explanation."
        )

        response = self.llm.call(
            system=system_prompt,
            user=user_prompt,
            temperature=0.0,
            max_tokens=2000,
        )

        cleaned = _strip_code_fences(response.text)
        try:
            intent = StructuredIntent.model_validate_json(cleaned)
        except (ValidationError, ValueError) as e:
            self.audit.log(
                "babel_extract_failed",
                project_id=project_id,
                error=str(e),
                raw=cleaned[:500],
                **response.audit_fields(),
            )
            raise

        self.audit.log(
            "babel_extract_ok",
            project_id=project_id,
            intent=intent.model_dump(),
            **response.audit_fields(),
        )
        return intent

    def round_trip(self, intent: StructuredIntent, project_id: str) -> str:
        """Translate intent back to Turkish so the user can confirm or correct."""
        response = self.llm.call(
            system=(
                "You translate structured English intent JSON into clear, concise "
                "Turkish prose for user validation. Maximum 150 words. "
                "Use bullet points where it helps clarity."
            ),
            user=(
                "Aşağıdaki intent JSON'unu kullanıcıya doğrulatmak için Türkçe özetle. "
                "Eksik/belirsiz noktaları açıkça belirt.\n\n"
                f"{intent.model_dump_json(indent=2)}"
            ),
            temperature=0.2,
            max_tokens=600,
        )
        self.audit.log(
            "babel_round_trip",
            project_id=project_id,
            **response.audit_fields(),
        )
        return response.text
