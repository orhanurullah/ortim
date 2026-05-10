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
from runtime.executor.sandbox import (
    SandboxViolation,
    check_extension,
    check_in_scope,
    normalize_relative,
)
from runtime.llm import LLMClient
from runtime.memory import MemoryLoader
from runtime.orchestrator import TaskSpec


class FileChange(BaseModel):
    path: str
    content: str
    operation: Literal["create", "overwrite"] = "create"


class WorkerOutput(BaseModel):
    task_id: str
    summary: str
    files: list[FileChange] = Field(default_factory=list)


class WorkerOutOfScope(Exception):
    """Worker emitted a path outside `module_scope` or with disallowed extension."""


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
    ) -> WorkerOutput:
        system_prompt = self.memory.load_agent_prompt("worker")
        principles = self.memory.load_l1_principles()
        full_system = (
            f"{system_prompt}\n\n## L1 Immutable Principles\n\n{principles}"
        )

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

        user_prompt = (
            f"Project ID: {project_id}\n\n"
            f"Task spec:\n{task.model_dump_json(indent=2)}\n\n"
            f"RFC section ({task.rfc_section}):\n```\n{rfc_text}\n```\n\n"
            f"{related_block}"
            f"{retry_block}"
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
            **response.audit_fields(),
        )
        return output
