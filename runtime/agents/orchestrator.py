# SPDX-License-Identifier: FSL-1.1-Apache-2.0
# Copyright (c) 2026 ortim.dev
"""Orchestrator agent — RFC → TaskDAG.

LLM produces the candidate DAG; deterministic validation rejects cycles,
missing deps, and over-budget tasks. On validation failure, the agent
retries with the error message included in the prompt (max 3 attempts).
"""

from __future__ import annotations

import re

from runtime.audit import AuditLogger
from runtime.babel.intent import _strip_code_fences
from runtime.llm import LLMClient
from runtime.memory import MemoryLoader
from runtime.orchestrator import CyclicDAG, MissingDependency, TaskDAG
from runtime.scope import ScopeManifest


# Item 42 — every emitted task.module_scope MUST match a module declared in
# RFC §7 Module Breakdown. Proof-point E2E (workspace `ed9f6074f1b8`,
# 2026-05-14) showed the Orchestrator collapsing RFC §7's separate `db` and
# `types` modules into a synthetic `shared` catch-all; Reviewer correctly
# flagged downstream imports as L1 boundary leaks but the damage was already
# done. Defense in depth: stronger prompt (Hard Rule 13 in
# agents/orchestrator.md) + deterministic post-DAG validator that feeds the
# error back into the existing retry loop.


def _parse_rfc_modules(rfc_text: str) -> set[str] | None:
    """Extract the module names declared in RFC §7 Module Breakdown.

    Handles both layouts the Architect produces:
      - markdown table: rows of `| \\`name\\` | responsibility | ...`
      - bullet list: `- \\`name\\` — responsibility`

    Returns `None` when §7 is missing or no module names parse. `None`
    means "no claim made" — caller should skip the subset check rather
    than flag every task as unscoped.
    """
    section = re.search(
        r"##\s*\d*\.?\s*Module Breakdown\b", rfc_text, re.IGNORECASE
    )
    if not section:
        return None
    start = section.end()
    next_section = re.search(r"\n##\s", rfc_text[start:])
    body = rfc_text[start:start + (next_section.start() if next_section else len(rfc_text) - start)]

    modules: set[str] = set()

    # Pattern A — markdown table rows: `| `name` | ...`. The header row
    # (`| Module | Responsibility | ...`) has no backticks so it's filtered
    # out naturally.
    for m in re.finditer(r"^\|\s*`([^`]+)`\s*\|", body, re.MULTILINE):
        name = re.sub(r"\s*\(new\)\s*$", "", m.group(1)).strip()
        if name:
            modules.add(name)

    # Pattern B — bullet-list fallback. Only consulted if table parse
    # found nothing (Architect's two layouts don't co-occur).
    if not modules:
        for m in re.finditer(r"^\s*[-*]\s+`([^`]+)`", body, re.MULTILINE):
            name = re.sub(r"\s*\(new\)\s*$", "", m.group(1)).strip()
            if name:
                modules.add(name)

    return modules or None


def _find_unscoped_tasks(
    dag: TaskDAG, rfc_modules: set[str]
) -> list[tuple[str, str]]:
    """Return `[(task_id, module_scope)]` for every task whose
    `module_scope` is NOT in `rfc_modules`. Empty list = all tasks
    correctly scoped.

    `module_scope` is normalized to its primary scope when the field is a
    list (forward-compat for the `module_scope: list[str]` future from
    item 4b).
    """
    out: list[tuple[str, str]] = []
    for task in dag.tasks:
        scope = task.module_scope
        if isinstance(scope, list):
            scope = scope[0] if scope else ""
        if scope not in rfc_modules:
            out.append((task.id, scope or "(empty)"))
    return out


# M3.1.1 — extend cycle DAG validators.
#
# When `generate_dag` is called for an extend cycle, the LLM produces a
# DAG that should:
#   1. Use task IDs strictly above the parent DAG's max ID (continuous
#      numbering — design §2 row 4).
#   2. Use module_scopes drawn from the union of existing RFC §7 modules
#      and the delta `### Module Breakdown (delta)` blocks under each
#      `## Extension N` section.
# Both checks raise ValueError that the existing retry-with-correction
# loop feeds back into the next attempt's prompt.


def _parse_rfc_extension_modules(rfc_text: str) -> set[str]:
    """Extract module names from every `### Module Breakdown (delta)`
    block under any `## Extension N` section. Returns empty set when no
    extensions are present (greenfield RFC). The merge with the
    H2-section result lives in `generate_dag` so the union semantics
    are explicit at the call site."""
    modules: set[str] = set()
    # Find every H3 "Module Breakdown (delta)" block. Body extends
    # until the next H3 (sibling sub-section like `### Data Model`) or
    # H2 (next root section).
    for header in re.finditer(
        r"###\s*Module Breakdown\s*\(delta\)",
        rfc_text,
        re.IGNORECASE,
    ):
        start = header.end()
        next_header = re.search(r"\n#{2,3}\s", rfc_text[start:])
        body = rfc_text[
            start : start + (next_header.start() if next_header else len(rfc_text) - start)
        ]
        # Same two-pattern parse as `_parse_rfc_modules`: table rows, then
        # bullet-list fallback.
        for m in re.finditer(r"^\|\s*`([^`]+)`\s*\|", body, re.MULTILINE):
            name = re.sub(r"\s*\(new\)\s*$", "", m.group(1)).strip()
            if name:
                modules.add(name)
        if not modules:
            for m in re.finditer(r"^\s*[-*]\s+`([^`]+)`", body, re.MULTILINE):
                name = re.sub(r"\s*\(new\)\s*$", "", m.group(1)).strip()
                if name:
                    modules.add(name)
    return modules


def _find_id_collisions(
    dag: TaskDAG, prior_dag: TaskDAG
) -> list[str]:
    """Return new task IDs that already exist in `prior_dag`. Empty
    list = no collisions."""
    existing = {t.id for t in prior_dag.tasks}
    return [t.id for t in dag.tasks if t.id in existing]


def _find_below_min_ids(
    dag: TaskDAG, min_id_int: int
) -> list[tuple[str, int | None]]:
    """Return `[(task_id, parsed_int_or_None)]` for tasks whose numeric
    ID tail is below `min_id_int` (e.g. parent DAG had T-005, extend
    must start at T-006; T-003 in the new set would be flagged).

    Empty list = all new IDs satisfy the continuity rule. Tasks with
    non-numeric tails are flagged with `None` so the LLM gets a clear
    correction message rather than silently passing.
    """
    below: list[tuple[str, int | None]] = []
    for task in dag.tasks:
        tail = task.id.removeprefix("T-")
        try:
            n = int(tail)
        except ValueError:
            below.append((task.id, None))
            continue
        if n < min_id_int:
            below.append((task.id, n))
    return below


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
        prior_dag: TaskDAG | None = None,
        scope: ScopeManifest | None = None,
    ) -> TaskDAG:
        """Generate a TaskDAG from the RFC.

        When `prior_dag` is provided (M3.1.1 extend cycles), two
        additional validators apply:
          1. New task IDs are strictly above `prior_dag.max_task_id()`
             (continuous numbering — design §2 row 4).
          2. New task module_scopes are drawn from the union of
             existing RFC §7 modules and `### Module Breakdown (delta)`
             entries under each `## Extension N` section.
        Both raise ValueError that the existing retry-with-correction
        loop feeds back into the next attempt's prompt.
        """
        system_prompt = self.memory.load_agent_prompt("orchestrator")
        principles = self.memory.load_l1_principles()
        full_system = (
            f"{system_prompt}\n\n## L1 Immutable Principles\n\n{principles}"
        )

        # Compute extend-cycle context once (pure functions of inputs).
        is_extend = prior_dag is not None
        min_new_id_int = prior_dag.max_task_id() + 1 if is_extend else 0
        existing_ids = (
            sorted(t.id for t in prior_dag.tasks) if is_extend else []
        )
        existing_modules = (
            sorted({
                (t.module_scope[0] if isinstance(t.module_scope, list) else t.module_scope)
                for t in prior_dag.tasks
            })
            if is_extend
            else []
        )

        # Faz 1.1 — scope block telling the LLM how to phase-tag emitted
        # TaskSpecs. Without this, `phase` falls back to its default (1),
        # which silently collapses Phase 2+ work into the MVP.
        scope_section = ""
        if scope is not None and scope.features:
            scope_section = (
                "## Locked Scope (HARD — phase per TaskSpec)\n"
                + scope.to_prompt_block()
                + "\n\n**HARD RULE — emit `phase` field per TaskSpec.** Each "
                "TaskSpec in the DAG MUST include a `phase: int` field. Read "
                "the RFC §7 two-tier Module Breakdown table and assign:\n"
                "  - `phase: 1` when the task supports a Phase-1 (MVP) row\n"
                "  - `phase: 2` (or higher) when it supports a deferred row\n"
                "A task that touches both phases is split into two tasks "
                "(one per phase) — do NOT emit a single task with mixed "
                "scope. Default phase=1 is only safe when no scope block "
                "is present; when this block IS present, omitting the "
                "phase field is a contract violation that triggers retry.\n"
            )

        previous_error: str | None = None
        for attempt in range(1, self.MAX_RETRIES + 1):
            sections = [
                f"Project ID: {project_id}\n",
                "RFC:\n\n```\n" + rfc_markdown + "\n```\n",
            ]
            if scope_section:
                sections.append(scope_section)
            if is_extend:
                sections.append(
                    "## Extend cycle context (HARD constraints)\n"
                    f"This is an extend cycle. The parent project already has "
                    f"tasks: {', '.join(existing_ids)}. Existing module "
                    f"scopes: {', '.join(existing_modules)}.\n"
                    f"- New task IDs MUST start at T-{min_new_id_int:03d} and "
                    f"continue without gaps (T-{min_new_id_int:03d}, "
                    f"T-{min_new_id_int + 1:03d}, ...).\n"
                    "- New tasks MUST NOT reuse any existing ID.\n"
                    "- New task `module_scope` MUST be either an existing "
                    "module (extending it) or a new module declared in the "
                    "RFC's `## Extension N` section under "
                    "`### Module Breakdown (delta)`.\n"
                    "- New tasks MAY declare `dependencies` on existing DONE "
                    f"tasks ({', '.join(existing_ids)}) — those are "
                    "satisfied by the prior DAG.\n"
                    "- **Aggregate ACs by (module_scope x behavioral "
                    "cluster) per the 'Extend Cycle Task Granularity' "
                    "section of the system prompt.** A 10-AC delta should "
                    "yield 3-5 tasks, not 10. Tasks must trace back to a "
                    "delta RFC Module Breakdown row or a delta AC — do not "
                    "invent tasks from parent RFC context.\n"
                )
            if previous_error:
                sections.append(
                    f"Previous attempt failed validation:\n  {previous_error}\n"
                    "Fix the issue and emit a corrected DAG. Output ONLY JSON.\n"
                )
            sections.append(
                "Emit the TaskDAG JSON. Output ONLY the JSON object."
            )
            user_prompt = "\n\n".join(sections)

            response = self.llm.call(
                system=full_system,
                user=user_prompt,
                temperature=0.0,
                max_tokens=8000,
            )
            cleaned = _strip_code_fences(response.text)

            try:
                dag = TaskDAG.model_validate_json(cleaned)
                # Extend-cycle dependencies on existing DONE tasks must
                # be allowed by `validate_dag`. We add the prior task IDs
                # to the in-DAG ID set BEFORE validation by re-using a
                # synthesized TaskDAG that includes them; simpler: skip
                # `validate_dag`'s in-DAG-only dep check by injecting a
                # combined view. We do the cycle/dup-id checks ourselves.
                if is_extend:
                    self._validate_extend_dag(dag, prior_dag)
                else:
                    dag.validate_dag()

                # Item 42 + M3.1.1: every task.module_scope MUST appear
                # in the union of (RFC §7 H2) ∪ (Extension N H3 deltas
                # if any). Skip the check when the RFC is missing §7
                # (older fixtures, brownfield runs with manual RFC).
                rfc_modules = _parse_rfc_modules(rfc_markdown)
                if rfc_modules is not None:
                    if is_extend:
                        rfc_modules = rfc_modules | _parse_rfc_extension_modules(
                            rfc_markdown
                        )
                    mismatches = _find_unscoped_tasks(dag, rfc_modules)
                    if mismatches:
                        detail = "; ".join(
                            f"{tid} uses module_scope='{scope}'"
                            for tid, scope in mismatches
                        )
                        allowed = ", ".join(sorted(rfc_modules))
                        suffix = (
                            " (extension Module Breakdown delta sections "
                            "included)"
                            if is_extend
                            else ""
                        )
                        raise ValueError(
                            f"Tasks reference module_scopes not in RFC §7 "
                            f"Module Breakdown{suffix}: {detail}. Allowed "
                            f"modules (verbatim): {allowed}. Do NOT "
                            "introduce 'shared', 'common', or any other "
                            "synthetic catch-all scope — every task's "
                            "module_scope MUST be exactly one of the "
                            "listed modules."
                        )
                self.audit.log(
                    "orchestrator_dag_ok",
                    project_id=project_id,
                    attempt=attempt,
                    task_count=len(dag.tasks),
                    estimated_tokens_total=dag.total_estimated_tokens(),
                    is_extend=is_extend,
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
                    is_extend=is_extend,
                    **response.audit_fields(),
                )

        raise RuntimeError(
            f"Orchestrator failed to produce a valid DAG after "
            f"{self.MAX_RETRIES} attempts. Last error: {previous_error}"
        )

    def _validate_extend_dag(self, dag: TaskDAG, prior_dag: TaskDAG) -> None:
        """Extend-cycle DAG validation:
        - cycle / dup-id within the new DAG (existing TaskDAG.validate_dag
          covers this once we treat the new DAG as standalone for those
          checks).
        - no ID collision with prior DAG.
        - new IDs >= prior_dag.max_task_id() + 1.
        - dependencies on prior-DAG IDs are allowed (override of the
          MissingDependency check that would otherwise fire).
        """
        # Local cycle/dup-id check that tolerates dependencies on prior
        # task IDs.
        ids = {t.id for t in dag.tasks}
        if len(ids) != len(dag.tasks):
            raise ValueError("Duplicate task IDs in delta DAG")
        prior_ids = {t.id for t in prior_dag.tasks}
        for t in dag.tasks:
            for dep in t.dependencies:
                if dep not in ids and dep not in prior_ids:
                    raise MissingDependency(
                        f"Task {t.id} depends on missing task {dep!r} "
                        "(not in delta DAG and not a prior DONE task)"
                    )
                if dep == t.id:
                    raise CyclicDAG(f"Task {t.id} depends on itself")
        # Cycle within the new tasks (Kahn's). Edges from prior tasks
        # are no-op (they're already DONE).
        in_degree = {
            t.id: sum(1 for d in t.dependencies if d in ids)
            for t in dag.tasks
        }
        graph: dict[str, list[str]] = {t.id: [] for t in dag.tasks}
        for t in dag.tasks:
            for dep in t.dependencies:
                if dep in ids:
                    graph[dep].append(t.id)
        from collections import deque
        queue = deque(tid for tid, d in in_degree.items() if d == 0)
        visited = 0
        while queue:
            current = queue.popleft()
            visited += 1
            for neighbor in graph[current]:
                in_degree[neighbor] -= 1
                if in_degree[neighbor] == 0:
                    queue.append(neighbor)
        if visited != len(dag.tasks):
            raise CyclicDAG("Delta DAG contains a cycle")

        # ID collision check: no new task may reuse a prior task's ID.
        collisions = _find_id_collisions(dag, prior_dag)
        if collisions:
            raise ValueError(
                f"New task IDs collide with existing prior-DAG IDs: "
                f"{', '.join(collisions)}. Extend-cycle task IDs MUST be "
                f"strictly above the parent DAG's max ID "
                f"(T-{prior_dag.max_task_id() + 1:03d} or higher); reusing "
                "a prior ID would silently overwrite history."
            )

        # Continuity check: new IDs must be >= max_prior + 1.
        min_new_id_int = prior_dag.max_task_id() + 1
        below = _find_below_min_ids(dag, min_new_id_int)
        if below:
            detail = "; ".join(
                f"{tid} (parsed as {n!r})" for tid, n in below
            )
            raise ValueError(
                f"New task IDs must start at T-{min_new_id_int:03d} or "
                f"above (parent DAG max is T-{prior_dag.max_task_id():03d}). "
                f"Offending IDs: {detail}. Use continuous numbering: "
                f"T-{min_new_id_int:03d}, T-{min_new_id_int + 1:03d}, ..."
            )
