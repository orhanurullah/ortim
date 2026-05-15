# SPDX-License-Identifier: FSL-1.1-Apache-2.0
# Copyright (c) 2026 ortim.dev
"""Worker + Reviewer skill injection.

Three guarantees:
  - WorkerAgent.execute injects the skill body into the system prompt
    under '## Active Skills' when active_skills is non-empty
  - CodeReviewerAgent.review does the same with the reviewer-flavored
    header
  - Worker output audit log includes active_skills=[skill names]
"""

from __future__ import annotations

import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from runtime.audit import AuditLogger  # noqa: E402
from runtime.executor.reviewer import CodeReviewerAgent  # noqa: E402
from runtime.executor.worker import WorkerAgent  # noqa: E402
from runtime.llm.client import LLMResponse  # noqa: E402
from runtime.memory import MemoryLoader  # noqa: E402
from runtime.orchestrator import TaskSpec  # noqa: E402
from runtime.skills.schema import Skill, SkillTriggers  # noqa: E402


@dataclass
class CapturingLLM:
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


def _setup() -> tuple[CapturingLLM, MemoryLoader, AuditLogger, Path]:
    tmp = Path(tempfile.mkdtemp())
    audit_path = tmp / "audit.jsonl"
    audit = AuditLogger(path=audit_path)
    memory = MemoryLoader(REPO_ROOT)
    return CapturingLLM(), memory, audit, audit_path


def _skill(name: str, body: str = "rule body content") -> Skill:
    return Skill(
        name=name,
        description=f"desc for {name}",
        audience=["worker", "reviewer"],
        triggers=SkillTriggers(language=["TypeScript"]),
        body=body,
        path=f"skills/test/{name}.md",
    )


def _task() -> TaskSpec:
    return TaskSpec(
        id="T-001",
        title="impl",
        description="implement the thing",
        module_scope="x",
        rfc_section="§7",
        acceptance_criteria=["thing works"],
        estimated_tokens=500,
    )


def test_worker_injects_active_skills_into_system_prompt() -> None:
    llm, memory, audit, _ = _setup()
    llm.response_text = (
        '{"task_id": "T-001", "summary": "ok", "files": [], '
        '"skills_consulted": ["ts-modules", "ts-imports"]}'
    )
    worker = WorkerAgent(llm, memory, audit)
    skills = [_skill("ts-modules", body="Use barrel imports.")]

    worker.execute(
        _task(),
        rfc_text="# RFC\n",
        project_id="P-1",
        active_skills=skills,
    )

    assert llm.calls, "Worker should have called the LLM"
    system_prompt, _ = llm.calls[0]
    assert "## Active Skills" in system_prompt
    assert "HARD rules" in system_prompt
    assert "ts-modules" in system_prompt
    assert "Use barrel imports." in system_prompt


def test_worker_skill_audit_records_active_skill_names() -> None:
    llm, memory, audit, audit_path = _setup()
    llm.response_text = (
        '{"task_id": "T-001", "summary": "ok", "files": [], '
        '"skills_consulted": ["ts-modules", "ts-imports"]}'
    )
    worker = WorkerAgent(llm, memory, audit)
    skills = [_skill("ts-modules"), _skill("ts-imports")]

    worker.execute(
        _task(),
        rfc_text="# RFC\n",
        project_id="P-1",
        active_skills=skills,
    )

    log_text = audit_path.read_text(encoding="utf-8")
    assert "worker_output_ok" in log_text
    # active_skills array is serialized JSON-style in the log
    assert "ts-modules" in log_text
    assert "ts-imports" in log_text


def test_worker_no_skills_means_no_skill_block_in_prompt() -> None:
    """When active_skills is None or empty, the system prompt must NOT
    contain the Active Skills header (back-compat with all pre-M3 tests)."""
    llm, memory, audit, _ = _setup()
    llm.response_text = (
        '{"task_id": "T-001", "summary": "ok", "files": [], '
        '"skills_consulted": ["ts-modules", "ts-imports"]}'
    )
    worker = WorkerAgent(llm, memory, audit)

    worker.execute(
        _task(),
        rfc_text="# RFC\n",
        project_id="P-1",
        active_skills=None,
    )

    system_prompt, _ = llm.calls[0]
    # The agent's prompt template (`agents/worker.md`) references the
    # `## Active Skills` block by name in its Skill Acknowledgement
    # section, so a naive substring check picks up that reference. The
    # actual injected skills block is uniquely identified by the
    # resolver-written intro line below.
    assert "The following project-specific patterns are HARD rules" not in system_prompt


def test_reviewer_injects_active_skills_with_reviewer_header() -> None:
    llm, memory, audit, _ = _setup()
    # Build a rubric-shaped verdict so the reviewer's length validator
    # accepts on first try (single criterion → single verdict).
    llm.response_text = (
        '{"criteria_verdicts": [{"criterion": "thing works", '
        '"status": "pass", "evidence": "code OK", "code_quote": null, '
        '"unverifiable_reason": null}], '
        '"l1_violations": [], "suggestions": []}'
    )
    reviewer = CodeReviewerAgent(llm, memory, audit)
    from runtime.executor.worker import WorkerOutput

    worker_output = WorkerOutput(task_id="T-001", summary="ok", files=[])
    reviewer.review(
        _task(),
        worker_output,
        rfc_text="# RFC\n",
        project_id="P-1",
        active_skills=[_skill("ts-modules", body="Barrel only.")],
    )

    system_prompt, _ = llm.calls[0]
    assert "## Active Skills" in system_prompt
    assert "Acceptance criteria are interpreted" in system_prompt
    assert "ts-modules" in system_prompt
    assert "Barrel only." in system_prompt
