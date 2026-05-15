# SPDX-License-Identifier: FSL-1.1-Apache-2.0
# Copyright (c) 2026 ortim.dev
"""WorkerAgent.execute prior_task_exports injection.

Three guarantees:
  - non-empty prior_task_exports lands as a '## Prior task exports'
    block in the system prompt with module + signature visible
  - None / empty omits the block entirely (back-compat for greenfield
    runs with no prior DONE tasks)
  - the audit log captures the list of prior module scopes whose
    exports were surfaced
"""

from __future__ import annotations

import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from runtime.audit import AuditLogger  # noqa: E402
from runtime.codebase.exports import ExportSignature  # noqa: E402
from runtime.codebase.prior_tasks import ModuleExports  # noqa: E402
from runtime.executor.worker import WorkerAgent  # noqa: E402
from runtime.llm.client import LLMResponse  # noqa: E402
from runtime.memory import MemoryLoader  # noqa: E402
from runtime.orchestrator import TaskSpec  # noqa: E402


@dataclass
class CapturingLLM:
    response_text: str = (
        '{"task_id": "T-1", "summary": "ok", "files": []}'
    )
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


def _task() -> TaskSpec:
    return TaskSpec(
        id="T-2",
        title="impl",
        description="implement",
        module_scope="ui-components",
        rfc_section="§7",
        acceptance_criteria=["does X"],
        estimated_tokens=500,
    )


def _service_exports() -> dict[str, ModuleExports]:
    return {
        "task-service": ModuleExports(
            module="task-service",
            files={
                "task-service/index.ts": [
                    ExportSignature(
                        kind="function",
                        name="createTaskService",
                        signature="export function createTaskService(db: DbAdapter)",
                    ),
                    ExportSignature(
                        kind="type",
                        name="Task",
                        signature="export type Task = z.infer<typeof TaskSchema>",
                    ),
                ]
            },
        )
    }


def test_prior_outputs_block_lands_in_system_prompt() -> None:
    llm, memory, audit, _ = _setup()
    worker = WorkerAgent(llm, memory, audit)
    worker.execute(
        _task(),
        rfc_text="# RFC\n",
        project_id="P-1",
        prior_task_exports=_service_exports(),
    )

    assert llm.calls
    system_prompt, _ = llm.calls[0]
    assert "## Prior task exports" in system_prompt
    assert "### task-service" in system_prompt
    assert "createTaskService" in system_prompt
    assert "DbAdapter" in system_prompt
    assert "Task" in system_prompt


def test_prior_outputs_block_omitted_when_empty() -> None:
    llm, memory, audit, _ = _setup()
    worker = WorkerAgent(llm, memory, audit)
    worker.execute(
        _task(),
        rfc_text="# RFC\n",
        project_id="P-1",
        prior_task_exports=None,
    )
    system_prompt, _ = llm.calls[0]
    assert "## Prior task exports" not in system_prompt


def test_prior_outputs_audit_records_module_list() -> None:
    llm, memory, audit, audit_path = _setup()
    worker = WorkerAgent(llm, memory, audit)
    worker.execute(
        _task(),
        rfc_text="# RFC\n",
        project_id="P-1",
        prior_task_exports=_service_exports(),
    )
    log = audit_path.read_text(encoding="utf-8")
    assert "worker_output_ok" in log
    assert "task-service" in log
    assert "prior_task_modules" in log
