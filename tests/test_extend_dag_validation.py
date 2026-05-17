# SPDX-License-Identifier: FSL-1.1-Apache-2.0
# Copyright (c) 2026 ortim.dev
"""M3.1.1a — Orchestrator.generate_dag(prior_dag=...) extend-cycle
validators.

Two layers of defense (mirrors Items 40 + 42 patterns):
- ID continuity: new task IDs must be > parent DAG max
- Scope membership: new task module_scope ∈ (existing RFC §7 ∪ delta
  Module Breakdown blocks under each `## Extension N` section)

Both raise ValueError that the existing retry-with-correction loop
feeds back into the next attempt's prompt; three strikes → RuntimeError.
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
    _find_below_min_ids,
    _find_id_collisions,
    _parse_rfc_extension_modules,
)
from ortim.audit import AuditLogger  # noqa: E402
from ortim.llm.client import LLMResponse  # noqa: E402
from ortim.memory import MemoryLoader  # noqa: E402
from ortim.orchestrator import TaskDAG, TaskSpec  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
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


def _task(task_id: str, scope: str = "ui", deps: list[str] | None = None) -> TaskSpec:
    return TaskSpec(
        id=task_id,
        title=f"task {task_id}",
        description=f"desc {task_id}",
        module_scope=scope,
        dependencies=deps or [],
        acceptance_criteria=[f"{task_id} works"],
    )


def _dag_json(
    tasks: list[tuple[str, str, list[str]]],
    project_id: str = "proj-test",
) -> str:
    return json.dumps(
        {
            "project_id": project_id,
            "tasks": [
                {
                    "id": tid,
                    "title": f"task {tid}",
                    "description": "x",
                    "module_scope": scope,
                    "dependencies": deps,
                    "estimated_tokens": 1000,
                    "acceptance_criteria": [f"{tid} works"],
                    "rfc_section": "§7",
                }
                for tid, scope, deps in tasks
            ],
        }
    )


def _rfc_with_extension(extension_modules: list[str] | None = None) -> str:
    """RFC body with parent §7 (db, store, ui) + optional `## Extension 1`
    delta module breakdown."""
    base = (
        "# RFC: web-todo\n\n"
        "## 4. Tech Stack\n- TS\n\n"
        "## 7. Module Breakdown\n\n"
        "| Module | Responsibility |\n|---|---|\n"
        "| `db` | persistence |\n"
        "| `store` | state |\n"
        "| `ui` | components |\n\n"
    )
    if extension_modules:
        rows = "\n".join(
            f"| `{m}` | new |" for m in extension_modules
        )
        base += (
            "## Extension 1 — Tagging\n\n"
            "### Module Breakdown (delta)\n\n"
            "| Module | New / Extended |\n|---|---|\n"
            f"{rows}\n\n"
            "### Other delta sub-section\n"
        )
    return base


def _agent(llm: _SequentialLLM) -> OrchestratorAgent:
    return OrchestratorAgent(
        llm=llm, memory=MemoryLoader(REPO_ROOT), audit=AuditLogger()
    )


def _prior_dag(scopes: list[tuple[str, str]]) -> TaskDAG:
    return TaskDAG(
        project_id="proj-test",
        tasks=[_task(tid, scope=scope) for tid, scope in scopes],
    )


# ---------------------------------------------------------------------------
# Pure-function unit tests
# ---------------------------------------------------------------------------


def test_parse_rfc_extension_modules_finds_delta_table_modules() -> None:
    rfc = _rfc_with_extension(extension_modules=["tagging", "tag-ui"])
    assert _parse_rfc_extension_modules(rfc) == {"tagging", "tag-ui"}


def test_parse_rfc_extension_modules_empty_when_no_extension_section() -> None:
    rfc = _rfc_with_extension(extension_modules=None)
    assert _parse_rfc_extension_modules(rfc) == set()


def test_find_id_collisions_empty_when_disjoint() -> None:
    prior = _prior_dag([("T-001", "db"), ("T-002", "ui")])
    new = TaskDAG(project_id="p", tasks=[_task("T-006", "ui")])
    assert _find_id_collisions(new, prior) == []


def test_find_id_collisions_lists_overlapping_ids() -> None:
    prior = _prior_dag([("T-001", "db"), ("T-002", "ui"), ("T-003", "store")])
    new = TaskDAG(
        project_id="p",
        tasks=[_task("T-002", "ui"), _task("T-006", "ui")],
    )
    assert _find_id_collisions(new, prior) == ["T-002"]


def test_find_below_min_ids_flags_low_numerics() -> None:
    new = TaskDAG(
        project_id="p",
        tasks=[_task("T-003", "ui"), _task("T-006", "ui")],
    )
    assert _find_below_min_ids(new, min_id_int=6) == [("T-003", 3)]


def test_find_below_min_ids_flags_non_numeric_tail() -> None:
    new = TaskDAG(project_id="p", tasks=[_task("T-foo", "ui")])
    assert _find_below_min_ids(new, min_id_int=1) == [("T-foo", None)]


# ---------------------------------------------------------------------------
# Integration: generate_dag with prior_dag
# ---------------------------------------------------------------------------


def test_generate_dag_extend_cycle_clean_first_attempt() -> None:
    """Happy path: extend cycle with clean DAG (continuous IDs, scope in
    union, deps on prior DONE tasks allowed). Single LLM call."""
    prior = _prior_dag([("T-001", "db"), ("T-002", "ui"), ("T-003", "store")])
    rfc = _rfc_with_extension(extension_modules=["tagging"])
    clean = _dag_json(
        [
            ("T-004", "tagging", []),         # new module
            ("T-005", "ui", ["T-002", "T-004"]),  # extends existing ui + deps on prior + new
        ]
    )
    llm = _SequentialLLM(responses=[clean])
    agent = _agent(llm)

    dag = agent.generate_dag(
        rfc_markdown=rfc, project_id="proj-test", prior_dag=prior
    )
    assert [t.id for t in dag.tasks] == ["T-004", "T-005"]
    assert len(llm.calls) == 1


def test_generate_dag_extend_rejects_id_collision_with_prior() -> None:
    """When a new task reuses a prior ID, validator fires and the loop
    retries with the correction. Second attempt uses fresh IDs."""
    prior = _prior_dag([("T-001", "db"), ("T-002", "ui"), ("T-003", "store")])
    rfc = _rfc_with_extension(extension_modules=["tagging"])
    bad = _dag_json([("T-002", "ui", []), ("T-004", "tagging", [])])
    good = _dag_json([("T-004", "tagging", []), ("T-005", "ui", [])])
    llm = _SequentialLLM(responses=[bad, good])
    agent = _agent(llm)

    dag = agent.generate_dag(
        rfc_markdown=rfc, project_id="proj-test", prior_dag=prior
    )
    assert [t.id for t in dag.tasks] == ["T-004", "T-005"]
    # Second call must reference the collision in its correction prompt.
    second_user = llm.calls[1][1]
    assert "T-002" in second_user
    assert "collide" in second_user.lower() or "previous attempt failed" in second_user.lower()


def test_generate_dag_extend_rejects_below_min_id() -> None:
    """When a new task uses an ID below the parent max+1, validator fires.
    Prior max is T-003; T-002 in delta is wrong."""
    prior = _prior_dag([("T-001", "db"), ("T-002", "ui"), ("T-003", "store")])
    rfc = _rfc_with_extension(extension_modules=["tagging"])
    bad = _dag_json([("T-002", "ui", [])])
    good = _dag_json([("T-004", "tagging", [])])
    llm = _SequentialLLM(responses=[bad, good])
    agent = _agent(llm)

    dag = agent.generate_dag(
        rfc_markdown=rfc, project_id="proj-test", prior_dag=prior
    )
    assert [t.id for t in dag.tasks] == ["T-004"]
    # T-002 collides with prior — the validator catches that first
    # (collisions before min-id check). The retry prompt mentions the
    # offender either way.
    second_user = llm.calls[1][1]
    assert "T-002" in second_user


def test_generate_dag_extend_scope_in_extension_delta_is_accepted() -> None:
    """A new task may use a module declared in `## Extension N` ###
    Module Breakdown (delta), not just the parent §7."""
    prior = _prior_dag([("T-001", "db"), ("T-002", "ui")])
    rfc = _rfc_with_extension(extension_modules=["tagging", "tag-ui"])
    # `tagging` is delta-only (not in parent §7) — must still pass.
    clean = _dag_json(
        [("T-003", "tagging", []), ("T-004", "tag-ui", ["T-003"])]
    )
    llm = _SequentialLLM(responses=[clean])
    agent = _agent(llm)

    dag = agent.generate_dag(
        rfc_markdown=rfc, project_id="proj-test", prior_dag=prior
    )
    assert [t.module_scope for t in dag.tasks] == ["tagging", "tag-ui"]
    assert len(llm.calls) == 1


def test_generate_dag_extend_dependency_on_prior_task_is_allowed() -> None:
    """An extend task may declare a dependency on a prior DONE task ID
    that doesn't appear in the new DAG. validate_extend_dag must NOT
    raise MissingDependency for these."""
    prior = _prior_dag([("T-001", "db"), ("T-002", "ui")])
    rfc = _rfc_with_extension(extension_modules=["tagging"])
    # T-003 depends on T-001 (prior DONE) and T-002 (prior DONE); both
    # outside the delta DAG.
    clean = _dag_json([("T-003", "tagging", ["T-001", "T-002"])])
    llm = _SequentialLLM(responses=[clean])
    agent = _agent(llm)
    dag = agent.generate_dag(
        rfc_markdown=rfc, project_id="proj-test", prior_dag=prior
    )
    assert dag.tasks[0].dependencies == ["T-001", "T-002"]
    assert len(llm.calls) == 1


def test_generate_dag_no_prior_dag_path_unchanged() -> None:
    """Backward compat: when prior_dag=None (initial DAG), behavior is
    identical to pre-M3.1.1 — no extend-context block in prompt, no
    extend-validator firing."""
    rfc = _rfc_with_extension(extension_modules=None)  # parent §7 only
    clean = _dag_json([("T-001", "db", []), ("T-002", "ui", ["T-001"])])
    llm = _SequentialLLM(responses=[clean])
    agent = _agent(llm)

    dag = agent.generate_dag(
        rfc_markdown=rfc, project_id="proj-test"
    )
    assert [t.id for t in dag.tasks] == ["T-001", "T-002"]
    # The prompt must NOT mention extend-cycle context.
    only_user = llm.calls[0][1]
    assert "extend cycle" not in only_user.lower()


def test_generate_dag_extend_three_strikes_raises() -> None:
    """Three failed attempts (e.g. LLM keeps colliding IDs) → RuntimeError."""
    prior = _prior_dag([("T-001", "db"), ("T-002", "ui")])
    rfc = _rfc_with_extension(extension_modules=["tagging"])
    bad = _dag_json([("T-001", "tagging", [])])  # collides with prior
    llm = _SequentialLLM(responses=[bad, bad, bad])
    agent = _agent(llm)

    with pytest.raises(RuntimeError, match="failed to produce a valid DAG"):
        agent.generate_dag(
            rfc_markdown=rfc, project_id="proj-test", prior_dag=prior
        )
    assert len(llm.calls) == 3


# ---------------------------------------------------------------------------
# Item 48 — Extend-cycle AC aggregation guidance
# ---------------------------------------------------------------------------


def test_orchestrator_prompt_teaches_extend_ac_aggregation() -> None:
    """Item 48: the system prompt MUST contain an 'Extend Cycle Task
    Granularity' section with explicit aggregation guidance — group ACs
    by (module_scope x behavioral cluster), target 3-5 tasks for a
    10-AC delta, do not pad one-AC-per-task."""
    prompt = (REPO_ROOT / "agents" / "orchestrator.md").read_text(
        encoding="utf-8"
    )
    assert "## Extend Cycle Task Granularity" in prompt, (
        "Item 48: missing 'Extend Cycle Task Granularity' section header"
    )
    assert "behavioral cluster" in prompt, (
        "Item 48: aggregation rule must reference 'behavioral cluster'"
    )
    assert "10-AC delta" in prompt and "3" in prompt and "5" in prompt, (
        "Item 48: explicit task-count target (3-5 tasks for 10-AC delta) "
        "must appear so the LLM has a quantitative anchor"
    )
    assert "trace back" in prompt.lower(), (
        "Item 48: every extend task must trace back to delta RFC/AC — "
        "the prompt must contain the literal 'trace back' phrasing"
    )
    # Counter-example pinning: aggregation rule must NOT blanket-collapse
    # cross-module ACs. Verify the prompt explicitly notes this boundary.
    assert "cross-module" in prompt.lower() or "different modules" in prompt.lower(), (
        "Item 48: counter-example (cross-module ACs stay separate) must "
        "be explicit, otherwise the rule risks over-collapsing"
    )


def test_generate_dag_extend_user_prompt_includes_aggregation_guidance() -> None:
    """Item 48: the runtime's extend-cycle user-prompt block must reference
    the aggregation rule by name and provide the 3-5-task quantitative
    anchor, so the LLM has the constraint in working context not just in
    the system-prompt section."""
    prior = _prior_dag([("T-001", "db"), ("T-002", "ui"), ("T-003", "store")])
    rfc = _rfc_with_extension(extension_modules=["tagging"])
    clean = _dag_json(
        [
            ("T-004", "tagging", []),
            ("T-005", "ui", ["T-002", "T-004"]),
        ]
    )
    llm = _SequentialLLM(responses=[clean])
    agent = _agent(llm)

    agent.generate_dag(
        rfc_markdown=rfc, project_id="proj-test", prior_dag=prior
    )

    only_user = llm.calls[0][1]
    assert "Aggregate" in only_user or "aggregate" in only_user, (
        "Item 48: user prompt must mention AC aggregation explicitly"
    )
    assert "Extend Cycle Task Granularity" in only_user, (
        "Item 48: user prompt must reference the system-prompt section by name"
    )
    assert "10-AC" in only_user and "3-5 tasks" in only_user, (
        "Item 48: user prompt must repeat the quantitative anchor "
        "(10-AC -> 3-5 tasks) in the per-call context block"
    )
