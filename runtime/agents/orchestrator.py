# SPDX-License-Identifier: FSL-1.1-Apache-2.0
# Copyright (c) 2026 ortim.dev
"""Orchestrator agent — RFC → TaskDAG.

LLM produces the candidate DAG; deterministic validation rejects cycles,
missing deps, and over-budget tasks. On validation failure, the agent
retries with the error message included in the prompt (max 3 attempts).
"""

from __future__ import annotations

from runtime.audit import AuditLogger
from runtime.babel.intent import _strip_code_fences
from runtime.llm import LLMClient
from runtime.memory import MemoryLoader
from runtime.orchestrator import CyclicDAG, MissingDependency, TaskDAG


class OrchestratorAgent:
    MAX_RETRIES = 3

    def __init__(
        self,
        llm: LLMClient,
        memory: MemoryLoader,
        audit: AuditLogger,
    ) -> None:
        self.llm = llm
        self.memory = memory
        self.audit = audit

    def generate_dag(
        self,
        rfc_markdown: str,
        project_id: str,
    ) -> TaskDAG:
        system_prompt = self.memory.load_agent_prompt("orchestrator")
        principles = self.memory.load_l1_principles()
        full_system = (
            f"{system_prompt}\n\n## L1 Immutable Principles\n\n{principles}"
        )

        previous_error: str | None = None
        for attempt in range(1, self.MAX_RETRIES + 1):
            user_prompt = (
                f"Project ID: {project_id}\n\n"
                "RFC:\n\n```\n" + rfc_markdown + "\n```\n\n"
            )
            if previous_error:
                user_prompt += (
                    f"Previous attempt failed validation:\n  {previous_error}\n"
                    "Fix the issue and emit a corrected DAG. Output ONLY JSON.\n\n"
                )
            user_prompt += "Emit the TaskDAG JSON. Output ONLY the JSON object."

            response = self.llm.call(
                system=full_system,
                user=user_prompt,
                temperature=0.0,
                max_tokens=8000,
            )
            cleaned = _strip_code_fences(response.text)

            try:
                dag = TaskDAG.model_validate_json(cleaned)
                dag.validate_dag()
                self.audit.log(
                    "orchestrator_dag_ok",
                    project_id=project_id,
                    attempt=attempt,
                    task_count=len(dag.tasks),
                    estimated_tokens_total=dag.total_estimated_tokens(),
                    **response.audit_fields(),
                )
                return dag
            except (ValueError, CyclicDAG, MissingDependency) as e:
                previous_error = str(e)
                self.audit.log(
                    "orchestrator_dag_validation_failed",
                    project_id=project_id,
                    attempt=attempt,
                    error=previous_error,
                    **response.audit_fields(),
                )

        raise RuntimeError(
            f"Orchestrator failed to produce a valid DAG after "
            f"{self.MAX_RETRIES} attempts. Last error: {previous_error}"
        )
