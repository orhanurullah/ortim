# SPDX-License-Identifier: FSL-1.1-Apache-2.0
# Copyright (c) 2026 ortim.dev
"""Documenter agent — generates post-run documentation like README.md."""

from __future__ import annotations

from runtime.audit import AuditLogger
from runtime.llm import LLMClient
from runtime.memory import MemoryLoader


class DocumenterAgent:
    def __init__(
        self,
        llm: LLMClient,
        memory: MemoryLoader,
        audit: AuditLogger,
    ) -> None:
        self.llm = llm
        self.memory = memory
        self.audit = audit

    def generate_readme(
        self,
        project_name: str,
        prd_text: str,
        rfc_text: str,
        project_id: str,
    ) -> str:
        system = (
            "You are an expert technical writer. Your job is to produce a comprehensive, "
            "production-ready README.md for a newly generated application.\n\n"
            "Rules:\n"
            "1. Output ONLY the raw Markdown content. Do NOT wrap it in markdown code blocks like ```markdown.\n"
            "2. Determine the primary language of the PRD and write the README in that same language.\n"
            "3. Include an architecture summary based on the RFC.\n"
            "4. Include usage examples, installation instructions, and tech stack details."
        )

        user_prompt = (
            f"Project name: {project_name}\n\n"
            "PRD:\n"
            f"{prd_text}\n\n"
            "RFC:\n"
            f"{rfc_text}\n\n"
            "Generate the README.md content."
        )

        response = self.llm.call(
            system=system,
            user=user_prompt,
            temperature=0.3,
            max_tokens=4000,
        )

        self.audit.log(
            "documenter_readme_generated",
            project_id=project_id,
            **response.audit_fields(),
        )
        
        # Clean up any potential markdown fencing if the LLM ignores rule 1
        text = response.text.strip()
        if text.startswith("```markdown"):
            text = text[11:]
        elif text.startswith("```"):
            text = text[3:]
        if text.endswith("```"):
            text = text[:-3]
            
        return text.strip()

