# SPDX-License-Identifier: FSL-1.1-Apache-2.0
# Copyright (c) 2026 ortim.dev
"""Item 42 — Orchestrator's emitted task.module_scope MUST match RFC §7.

Proof-point E2E (workspace `ed9f6074f1b8`, 2026-05-14) showed the
Orchestrator collapsing RFC §7's separate `db` and `types` modules into a
synthetic `shared` catch-all; Reviewer correctly flagged downstream
imports as L1 boundary leaks. The fix is two-layered: stronger prompt
(Hard Rule 13 in agents/orchestrator.md) + deterministic post-DAG
validator that raises into the existing retry loop on mismatch.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from ortim.agents.orchestrator import (  # noqa: E402
    OrchestratorAgent,
    _find_unscoped_tasks,
    _parse_rfc_modules,
)
from ortim.audit import AuditLogger  # noqa: E402
from ortim.llm.client import LLMResponse  # noqa: E402
from ortim.memory import MemoryLoader  # noqa: E402
from ortim.orchestrator import TaskDAG, TaskSpec  # noqa: E402


# ---------------------------------------------------------------------------
# Parser unit tests
# ---------------------------------------------------------------------------


def test_parse_rfc_modules_from_markdown_table() -> None:
    """The shape Architect actually produced in the proof-point — table rows
    with backtick-wrapped module names in the first column."""
    rfc = (
        "## 7. Module Breakdown\n\n"
        "| Module | Responsibility | Owns Schema | Public Interface |\n"
        "|--------|---------------|-------------|------------------|\n"
        "| `db` | sql.js init | tasks table | `initDB()` |\n"
        "| `store` | state mgmt | None | `useTaskStore()` |\n"
        "| `components/TaskForm` | input + submit | None | `<TaskForm />` |\n"
        "| `types` | TS interfaces | Task type | `Task` |\n\n"
        "## 8. API Surface\n"
    )
    # Module names are normalized to a filesystem-safe form: lowercased,
    # whitespace collapsed to `-`. `/` is preserved for nested modules.
    assert _parse_rfc_modules(rfc) == {
        "db",
        "store",
        "components/taskform",
        "types",
    }


def test_parse_rfc_modules_strips_new_annotation() -> None:
    """Brownfield RFCs mark new modules with `(new)` — strip that."""
    rfc = (
        "## 7. Module Breakdown\n\n"
        "| Module | Responsibility |\n|---|---|\n"
        "| `auth` | login |\n"
        "| `billing (new)` | invoices |\n\n"
        "## 8.\n"
    )
    assert _parse_rfc_modules(rfc) == {"auth", "billing"}


def test_parse_rfc_modules_bullet_list_fallback() -> None:
    """Some Architect outputs use bullet lists instead of tables."""
    rfc = (
        "## 7. Module Breakdown\n\n"
        "- `db` — sql.js initialization\n"
        "- `store` — state management\n"
        "- `types` — type definitions\n\n"
        "## 8.\n"
    )
    assert _parse_rfc_modules(rfc) == {"db", "store", "types"}


def test_parse_rfc_modules_returns_none_when_section_missing() -> None:
    rfc = "## 4. Tech Stack\n\n## 8. API\n"
    assert _parse_rfc_modules(rfc) is None


def test_parse_rfc_modules_returns_none_when_section_empty() -> None:
    """§7 exists but has no recognizable module rows — return None so the
    validator skips rather than rejecting every task."""
    rfc = "## 7. Module Breakdown\n\n(TBD)\n\n## 8.\n"
    assert _parse_rfc_modules(rfc) is None


def test_parse_rfc_modules_normalizes_whitespace_to_kebab() -> None:
    """G-C2: an Architect that writes `"API Client Module"` in §7 must not
    cause downstream sandbox failures. The parser normalizes whitespace
    so the validator can compare against the Orchestrator's kebab-case
    form without spurious mismatches."""
    rfc = (
        "## 7. Module Breakdown\n\n"
        "| Module | Responsibility |\n|---|---|\n"
        "| `API Client Module` | supabase client init |\n"
        "| `Auth Module` | login/logout |\n\n"
        "## 8.\n"
    )
    assert _parse_rfc_modules(rfc) == {"api-client-module", "auth-module"}


def test_find_unscoped_tasks_normalizes_task_side_too() -> None:
    """A task emitting kebab-case `module_scope` must match an RFC §7
    label written with whitespace — both sides go through the normalizer."""
    rfc_modules = {"api-client-module", "auth-module"}
    dag = _dag_with_scopes([
        ("T-001", "api-client-module"),
        ("T-002", "Auth Module"),  # raw RFC label form
    ])
    assert _find_unscoped_tasks(dag, rfc_modules) == []


# ---------------------------------------------------------------------------
# Validator unit tests
# ---------------------------------------------------------------------------


def _dag_with_scopes(scopes: list[tuple[str, str]]) -> TaskDAG:
    """Build a TaskDAG from [(task_id, module_scope)] pairs."""
    return TaskDAG(
        project_id="proj-test",
        tasks=[
            TaskSpec(
                id=tid,
                title=f"task {tid}",
                description="x",
                module_scope=scope,
                estimated_tokens=1000,
            )
            for tid, scope in scopes
        ],
    )


def test_find_unscoped_tasks_empty_when_all_match() -> None:
    dag = _dag_with_scopes([("T-001", "db"), ("T-002", "store")])
    assert _find_unscoped_tasks(dag, {"db", "store", "types"}) == []


def test_find_unscoped_tasks_lists_offenders() -> None:
    """The exact proof-point case: tasks scoped to synthetic `shared` even
    though RFC §7 only declares db/store/types."""
    dag = _dag_with_scopes(
        [("T-001", "shared"), ("T-002", "shared"), ("T-003", "store")]
    )
    mismatches = _find_unscoped_tasks(dag, {"db", "store", "types"})
    assert mismatches == [("T-001", "shared"), ("T-002", "shared")]


# ---------------------------------------------------------------------------
# Integration tests for generate_dag retry loop
# ---------------------------------------------------------------------------


@dataclass
class _SequentialLLM:
    responses: list[str]
    calls: list[tuple[str, str]] = field(default_factory=list)
    _idx: int = 0

    def call(
        self,
        system: str,
        user: str,
        temperature: float = 0.0,
        max_tokens: int = 4096,
    ) -> LLMResponse:
        self.calls.append((system, user))
        text = self.responses[self._idx]
        self._idx += 1
        return LLMResponse(
            text=text,
            input_tokens=10,
            output_tokens=5,
            model="fake-model",
            provider="fake",
        )


def _dag_json(scopes: list[tuple[str, str]]) -> str:
    """Build a TaskDAG JSON payload from [(task_id, module_scope)] pairs."""
    return json.dumps(
        {
            "project_id": "proj-test",
            "tasks": [
                {
                    "id": tid,
                    "title": f"task {tid}",
                    "description": "x",
                    "module_scope": scope,
                    "dependencies": [],
                    "estimated_tokens": 1000,
                    "acceptance_criteria": ["does something"],
                    "rfc_section": "§7",
                }
                for tid, scope in scopes
            ],
        }
    )


def _rfc_with_db_store_types() -> str:
    return (
        "# RFC: test\n\n"
        "## 4. Tech Stack\n- **Language:** TS\n\n"
        "## 7. Module Breakdown\n\n"
        "| Module | Responsibility |\n|---|---|\n"
        "| `db` | persistence |\n"
        "| `store` | state |\n"
        "| `types` | types |\n\n"
        "## 8. API\n"
    )


def _agent(llm) -> OrchestratorAgent:
    return OrchestratorAgent(llm=llm, memory=MemoryLoader(REPO_ROOT), audit=AuditLogger())


def test_generate_dag_retries_when_scope_not_in_rfc_then_succeeds() -> None:
    """First attempt uses synthetic 'shared' scope; second attempt aligns
    with RFC §7. Loop must accept attempt 2."""
    drifted = _dag_json([("T-001", "shared"), ("T-002", "store")])
    clean = _dag_json([("T-001", "db"), ("T-002", "store")])
    llm = _SequentialLLM(responses=[drifted, clean])
    agent = _agent(llm)

    dag = agent.generate_dag(
        rfc_markdown=_rfc_with_db_store_types(),
        project_id="proj-test",
    )

    assert {t.module_scope for t in dag.tasks} == {"db", "store"}
    assert len(llm.calls) == 2

    # Retry's user prompt must carry the structured error referencing the
    # offending task and the allowed set.
    retry_prompt = llm.calls[1][1]
    assert "module_scopes not in RFC §7" in retry_prompt
    assert "T-001 uses module_scope='shared'" in retry_prompt
    assert "db, store, types" in retry_prompt


def test_generate_dag_raises_after_three_unscoped_attempts() -> None:
    """If the LLM keeps emitting synthetic `shared` scopes for the full
    retry budget, generate_dag raises RuntimeError so a corrupt DAG can't
    enter the executor."""
    drifted = _dag_json([("T-001", "shared")])
    llm = _SequentialLLM(responses=[drifted, drifted, drifted])
    agent = _agent(llm)

    with pytest.raises(RuntimeError, match="module_scopes not in RFC"):
        agent.generate_dag(
            rfc_markdown=_rfc_with_db_store_types(),
            project_id="proj-test",
        )
    assert len(llm.calls) == 3


def test_generate_dag_skips_validation_when_rfc_has_no_section_7() -> None:
    """Older fixtures and brownfield runs may not have a parseable §7. The
    validator returns None in that case and the loop accepts the DAG as
    long as it passes the existing cycle/dep checks."""
    drifted = _dag_json([("T-001", "anything-goes")])
    llm = _SequentialLLM(responses=[drifted])
    agent = _agent(llm)

    rfc_without_section_7 = "# RFC\n\n## 4. Tech Stack\n\n- **Language:** TS\n"
    dag = agent.generate_dag(
        rfc_markdown=rfc_without_section_7,
        project_id="proj-test",
    )

    assert dag.tasks[0].module_scope == "anything-goes"
    assert len(llm.calls) == 1, "No retry when RFC has no §7 to enforce against"
