# SPDX-License-Identifier: FSL-1.1-Apache-2.0
# Copyright (c) 2026 ortim.dev
"""Worker agent — executes a single TaskSpec atomic task.

v0.5b scope: real source code (Python/TS/Go/Rust/...), config, and docs.
Files written to a per-task git branch (`task/<id>`); the runner runs the
configured test command before review. The sandbox still rejects out-of-scope
paths and non-whitelisted extensions.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from runtime.audit import AuditLogger
from runtime.babel.intent import _strip_code_fences
from runtime.codebase import ModuleExports, format_prior_outputs_block
from runtime.executor.sandbox import (
    SandboxViolation,
    check_extension,
    check_in_scope,
    normalize_relative,
)
from runtime.llm import LLMClient
from runtime.memory import MemoryLoader
from runtime.orchestrator import TaskSpec
from runtime.skills import Skill, format_skills_block


class FileChange(BaseModel):
    path: str
    content: str
    operation: Literal["create", "overwrite"] = "create"


class WorkerOutput(BaseModel):
    task_id: str
    summary: str
    files: list[FileChange] = Field(default_factory=list)
    # G-1 enforcement: every skill resolved for this task must appear here.
    # Default empty list keeps callers without resolved skills (legacy unit
    # tests, brownfield paths without an active skill set) parse-compatible.
    skills_consulted: list[str] = Field(default_factory=list)


class WorkerOutOfScope(Exception):
    """Worker emitted a path outside `module_scope` or with disallowed extension."""


class WorkerSkillNotConsulted(Exception):
    """Worker output omitted one or more resolved skills from `skills_consulted`.

    The runner's auto-retry loop (Item 7 / Item 15a pattern) feeds the
    missing skill list back through `prior_reasons`, tagged `[skill]`, so
    the next attempt is forced to read the `## Active Skills` block. This
    is acknowledgement-level enforcement — Reviewer remains the layer
    that checks whether skills were actually *applied* (G-1 two-layer
    defense: Worker acknowledges, Reviewer verifies).
    """


class WorkerAgent:
    def __init__(
        self,
        llm: LLMClient,
        memory: MemoryLoader,
        audit: AuditLogger,
    ) -> None:
        self.llm = llm
        self.memory = memory
        self.audit = audit

    def execute(
        self,
        task: TaskSpec,
        rfc_text: str,
        project_id: str,
        prior_review_reasons: list[str] | None = None,
        related_files: dict[str, str] | None = None,
        app_class: str = "web",
        active_skills: list[Skill] | None = None,
        prior_task_exports: dict[str, ModuleExports] | None = None,
    ) -> WorkerOutput:
        system_prompt = self.memory.load_agent_prompt("worker")
        principles = self.memory.load_l1_principles()
        skills_block = format_skills_block(active_skills or [], audience="worker")
        prior_outputs_block = format_prior_outputs_block(prior_task_exports or {})
        full_system = (
            f"{system_prompt}\n\n## L1 Immutable Principles\n\n{principles}"
        )
        if skills_block:
            full_system = f"{full_system}\n\n{skills_block}"
        if prior_outputs_block:
            full_system = f"{full_system}\n\n{prior_outputs_block}"

        retry_block = ""
        if prior_review_reasons:
            joined = "\n".join(f"  - {r}" for r in prior_review_reasons)
            retry_block = (
                "Previous attempt was rejected by the Code Reviewer. "
                "Reasons:\n" + joined + "\n\n"
            )

        related_block = ""
        if related_files:
            parts: list[str] = [
                "## Related existing files (read these — do not regenerate unrelated lines)\n"
            ]
            for path, content in related_files.items():
                parts.append(
                    f"// FILE: {path} ({len(content.encode('utf-8'))} bytes)\n"
                    f"```\n{content}\n```\n"
                )
            parts.append(
                "If your task is to modify any of these files, output "
                "`operation: overwrite` with the FULL new content. "
                "Preserve all unrelated logic exactly.\n"
            )
            related_block = "\n".join(parts) + "\n"

        skill_directive = ""
        if active_skills:
            names = ", ".join(f"`{s.name}`" for s in active_skills)
            skill_directive = (
                f"Active skills resolved for this task: {names}. Apply each "
                "one as described in the `## Active Skills` system block, "
                "then list every skill name in the output's "
                "`skills_consulted` field. Omitting a resolved skill from "
                "`skills_consulted` causes a retry — the runtime treats it "
                "as evidence you did not read the skill block.\n\n"
            )

        user_prompt = (
            f"Project ID: {project_id}\n\n"
            f"Task spec:\n{task.model_dump_json(indent=2)}\n\n"
            f"RFC section ({task.rfc_section}):\n```\n{rfc_text}\n```\n\n"
            f"{related_block}"
            f"{retry_block}"
            f"{skill_directive}"
            f"App class: {app_class} (sandbox enforces this set of file extensions)\n\n"
            "Allowed file types: source code (Python/TS/Go/Rust/...), "
            "config (json/yaml/toml/...), docs (md/rst/txt), schemas "
            "(sql/proto/graphql), and known basenames (Dockerfile, "
            "Makefile, .gitignore, ...). Binaries, archives, and images "
            "are rejected by the sandbox.\n\n"
            f"Every file path MUST be under module_scope: `{task.module_scope}`. "
            "Paths outside this prefix are rejected.\n\n"
            "If the runtime has a test command configured, your output is "
            "executed through it before review — broken tests cause "
            "rejection regardless of acceptance criteria.\n\n"
            "Emit WorkerOutput JSON. Output ONLY the JSON object."
        )

        response = self.llm.call(
            system=full_system,
            user=user_prompt,
            temperature=0.0,
            max_tokens=min(8000, task.estimated_tokens + 2000),
        )
        cleaned = _strip_code_fences(response.text)

        try:
            output = WorkerOutput.model_validate_json(cleaned)
        except ValueError as e:
            self.audit.log(
                "worker_output_parse_failed",
                project_id=project_id,
                task_id=task.id,
                error=str(e)[:300],
                raw=cleaned[:500],
                **response.audit_fields(),
            )
            raise

        # G-1 enforcement: acknowledge every resolved skill BEFORE sandbox
        # checks. Sandbox failures are about WHAT was emitted; the skill
        # gate is about whether the Worker even looked at the rule set.
        # Running it first lets us emit a clean signal in `prior_reasons`
        # — otherwise a Worker that ignored skills AND wrote out-of-scope
        # files would only learn about the sandbox issue on retry, never
        # the skill issue.
        if active_skills:
            expected = {s.name for s in active_skills}
            consulted = {n.strip() for n in output.skills_consulted if n.strip()}
            missing = sorted(expected - consulted)
            if missing:
                self.audit.log(
                    "worker_skill_check_failed",
                    project_id=project_id,
                    task_id=task.id,
                    expected_skills=sorted(expected),
                    consulted_skills=sorted(consulted),
                    missing_skills=missing,
                    **response.audit_fields(),
                )
                raise WorkerSkillNotConsulted(
                    f"missing skills in skills_consulted: {missing}"
                )

        violations: list[str] = []
        for f in output.files:
            try:
                rel = normalize_relative(f.path)
                check_in_scope(rel, task.module_scope)
                check_extension(rel, app_class)
            except SandboxViolation as e:
                violations.append(f"{f.path}: {e}")

        if violations:
            self.audit.log(
                "worker_sandbox_violation",
                project_id=project_id,
                task_id=task.id,
                violations=violations,
                **response.audit_fields(),
            )
            raise WorkerOutOfScope("; ".join(violations))

        self.audit.log(
            "worker_output_ok",
            project_id=project_id,
            task_id=task.id,
            file_count=len(output.files),
            attempt_after_review=bool(prior_review_reasons),
            active_skills=[s.name for s in (active_skills or [])],
            prior_task_modules=sorted((prior_task_exports or {}).keys()),
            **response.audit_fields(),
        )
        return output
