# SPDX-License-Identifier: FSL-1.1-Apache-2.0
# Copyright (c) 2026 ortim.dev
"""Tests for the Worker skill-acknowledgement gate (G-1 enforcement).

The contract is acknowledgement-level: every skill the resolver passes
into `WorkerAgent.execute(active_skills=...)` must appear by name in
`WorkerOutput.skills_consulted`. Missing entries raise
`WorkerSkillNotConsulted`, which the runner's auto-retry loop converts
to a `[skill]`-tagged `prior_reasons` entry for the next attempt.

Reviewer remains the second layer: even after acknowledgement, Reviewer
cross-checks that the skill was actually applied in the generated code.
This file tests the acknowledgement gate only.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import pytest  # noqa: E402

from ortim.audit import AuditLogger  # noqa: E402
from ortim.executor import TaskStatus, TaskStatusFile, execute_task  # noqa: E402
from ortim.executor.worker import (  # noqa: E402
    WorkerAgent,
    WorkerSkillNotConsulted,
)
from ortim.llm.client import LLMResponse  # noqa: E402
from ortim.memory import MemoryLoader  # noqa: E402
from ortim.orchestrator import TaskSpec  # noqa: E402
from ortim.skills import Skill, SkillTriggers  # noqa: E402


class FakeLLM:
    """Returns canned text on each call. The test seeds the queue so
    sequential calls (e.g. Worker → Reviewer, or Worker attempt 1 → attempt 2)
    each get a deterministic response."""

    def __init__(self, queue: list[str]) -> None:
        self.queue = list(queue)
        self.calls: list[str] = []

    def call(
        self,
        system: str,
        user: str,
        temperature: float = 0.0,
        max_tokens: int = 4096,
    ) -> LLMResponse:
        sys_lower = system.lower()
        if "code reviewer" in sys_lower:
            role = "code"
        elif "security reviewer" in sys_lower:
            role = "security"
        elif "test strategist" in sys_lower:
            role = "test"
        elif "performance reviewer" in sys_lower:
            role = "perf"
        else:
            role = "worker"
        self.calls.append(role)
        text = self.queue.pop(0) if self.queue else "{}"
        return LLMResponse(
            text=text,
            input_tokens=10,
            output_tokens=10,
            model="fake",
            provider="fake",
        )


def _task(scope: str = "src/auth") -> TaskSpec:
    return TaskSpec(
        id="T-001",
        title="Implement guard",
        description="Implement an auth guard with cleanup",
        module_scope=scope,
        rfc_section="§7",
        dependencies=[],
        acceptance_criteria=["guard rejects unauthed requests"],
        estimated_tokens=1000,
    )


def _skill(name: str, body: str = "Apply this pattern.") -> Skill:
    return Skill(
        name=name,
        description=f"Skill {name}",
        body=body,
        triggers=SkillTriggers(),
    )


def _worker_output(
    *,
    path: str = "src/auth/guard.py",
    skills_consulted: list[str] | None = None,
) -> str:
    payload = {
        "task_id": "T-001",
        "summary": "Added guard",
        "files": [
            {"path": path, "content": "GUARD = True\n", "operation": "create"},
        ],
    }
    if skills_consulted is not None:
        payload["skills_consulted"] = skills_consulted
    return json.dumps(payload)


def _make_worker() -> tuple[WorkerAgent, FakeLLM, AuditLogger]:
    tmp = tempfile.mkdtemp()
    audit = AuditLogger(path=Path(tmp) / "audit.jsonl")
    memory = MemoryLoader(REPO_ROOT)
    llm = FakeLLM([])
    return WorkerAgent(llm, memory, audit), llm, audit


# ---------------------------------------------------------------------
# Unit tests against WorkerAgent.execute()
# ---------------------------------------------------------------------


def test_passes_when_all_resolved_skills_acknowledged() -> None:
    worker, llm, _ = _make_worker()
    llm.queue.append(
        _worker_output(skills_consulted=["typescript-module-boundaries"])
    )
    output = worker.execute(
        _task(),
        "RFC text",
        "P1",
        active_skills=[_skill("typescript-module-boundaries")],
    )
    assert output.skills_consulted == ["typescript-module-boundaries"]


def test_raises_when_resolved_skill_missing_from_consulted() -> None:
    worker, llm, _ = _make_worker()
    llm.queue.append(
        _worker_output(skills_consulted=["sql-mock-patterns"])
    )
    with pytest.raises(WorkerSkillNotConsulted) as exc_info:
        worker.execute(
            _task(),
            "RFC text",
            "P1",
            active_skills=[
                _skill("typescript-module-boundaries"),
                _skill("sql-mock-patterns"),
            ],
        )
    assert "typescript-module-boundaries" in str(exc_info.value)


def test_extra_skills_in_consulted_do_not_fail() -> None:
    """Acknowledging skills NOT in the resolved set is allowed — the
    check is `expected ⊆ consulted`, not strict equality. This keeps
    Worker honest about extra skills it may have read elsewhere
    (e.g. inherited from prior conversation context)."""
    worker, llm, _ = _make_worker()
    llm.queue.append(
        _worker_output(
            skills_consulted=[
                "typescript-module-boundaries",
                "react-dependency-injection",
                "some-skill-not-in-active-set",
            ]
        )
    )
    output = worker.execute(
        _task(),
        "RFC text",
        "P1",
        active_skills=[
            _skill("typescript-module-boundaries"),
            _skill("react-dependency-injection"),
        ],
    )
    assert "some-skill-not-in-active-set" in output.skills_consulted


def test_check_skipped_when_no_active_skills() -> None:
    worker, llm, _ = _make_worker()
    llm.queue.append(_worker_output(skills_consulted=[]))
    # No active_skills passed — empty `skills_consulted` is fine.
    output = worker.execute(
        _task(),
        "RFC text",
        "P1",
        active_skills=None,
    )
    assert output.skills_consulted == []


def test_legacy_worker_output_without_field_parses_when_no_skills() -> None:
    """Backward-compat: pre-G1 Worker outputs omitted skills_consulted
    entirely. Pydantic default keeps them parsing as long as no skills
    are active (otherwise the gate fires, which is the correct
    behavior)."""
    worker, llm, _ = _make_worker()
    raw = json.dumps({
        "task_id": "T-001",
        "summary": "Added guard",
        "files": [
            {"path": "src/auth/guard.py", "content": "x\n", "operation": "create"},
        ],
    })
    llm.queue.append(raw)
    output = worker.execute(
        _task(),
        "RFC text",
        "P1",
        active_skills=None,
    )
    assert output.skills_consulted == []


def test_audit_log_records_missing_skills_on_failure() -> None:
    worker, llm, audit = _make_worker()
    llm.queue.append(
        _worker_output(skills_consulted=[])
    )
    with pytest.raises(WorkerSkillNotConsulted):
        worker.execute(
            _task(),
            "RFC text",
            "P1",
            active_skills=[_skill("typescript-module-boundaries")],
        )
    events = []
    with audit.path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                events.append(json.loads(line))
    skill_check_events = [e for e in events if e.get("event") == "worker_skill_check_failed"]
    assert len(skill_check_events) == 1
    e = skill_check_events[0]
    assert e["missing_skills"] == ["typescript-module-boundaries"]
    assert e["expected_skills"] == ["typescript-module-boundaries"]


# ---------------------------------------------------------------------
# Integration test via execute_task — verifies runner feeds [skill]-tagged
# prior_reasons on retry.
# ---------------------------------------------------------------------


def test_runner_retry_feeds_skill_tagged_prior_reasons() -> None:
    """Two Worker attempts: attempt 1 omits the skill (raises), attempt
    2 has it acknowledged. The runner's retry loop must surface
    `[skill] ...` in `record.last_review_reasons` BEFORE attempt 2, so
    the LLM sees concrete feedback rather than blind re-prompting."""

    def approved_verdict() -> str:
        return json.dumps({
            "criteria_verdicts": [
                {
                    "criterion": "guard rejects unauthed requests",
                    "status": "pass",
                    "evidence": "guard.py rejects with 401",
                },
            ],
        })

    canned = [
        _worker_output(skills_consulted=[]),  # attempt 1: missing skill
        _worker_output(skills_consulted=["sql-mock-patterns"]),  # attempt 2
        approved_verdict(),  # CodeReviewer approves attempt 2
    ]

    tmp = tempfile.mkdtemp()
    workspace = Path(tmp)
    status_file = TaskStatusFile.load_or_init(workspace, "P1")
    audit = AuditLogger(path=workspace / "audit.jsonl")
    memory = MemoryLoader(REPO_ROOT)
    llm = FakeLLM(canned)

    os.environ["ORTIM_GIT_ENABLED"] = "false"
    try:
        attempt_1 = execute_task(
            task=_task(),
            rfc_text="RFC",
            project_id="P1",
            workspace=workspace,
            status_file=status_file,
            llm=llm,
            memory=memory,
            audit=audit,
            max_attempts=3,
            reviewer_chain=None,
            skills=[_skill("sql-mock-patterns")],
        )

        assert attempt_1.status == TaskStatus.PENDING
        record = status_file.records["T-001"]
        assert record.last_review_reasons, "should have feedback after skill miss"
        feedback = record.last_review_reasons[0]
        assert feedback.startswith("[skill]"), (
            f"expected [skill]-tagged feedback, got: {feedback!r}"
        )
        assert "sql-mock-patterns" in feedback or "skills_consulted" in feedback

        attempt_2 = execute_task(
            task=_task(),
            rfc_text="RFC",
            project_id="P1",
            workspace=workspace,
            status_file=status_file,
            llm=llm,
            memory=memory,
            audit=audit,
            max_attempts=3,
            reviewer_chain=None,
            skills=[_skill("sql-mock-patterns")],
        )
        assert attempt_2.status == TaskStatus.DONE
    finally:
        os.environ.pop("ORTIM_GIT_ENABLED", None)
