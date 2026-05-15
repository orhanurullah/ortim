# SPDX-License-Identifier: FSL-1.1-Apache-2.0
# Copyright (c) 2026 ortim.dev
"""Task DAG — atomic units of work generated from an approved RFC.

The DAG is the contract between the Orchestrator agent (which produces it)
and the Worker agents (iter. 5+, which execute one task each). Validation
is deterministic so an LLM-emitted DAG cannot smuggle in cycles or dangling
references.
"""

from __future__ import annotations

from collections import deque

from pydantic import BaseModel, Field, field_validator


class TaskSpec(BaseModel):
    id: str
    title: str
    description: str
    module_scope: str
    dependencies: list[str] = Field(default_factory=list)
    estimated_tokens: int = 5000
    acceptance_criteria: list[str] = Field(default_factory=list)
    rfc_section: str = ""

    @field_validator("id")
    @classmethod
    def _id_format(cls, v: str) -> str:
        if not v.startswith("T-"):
            raise ValueError(f"Task id must start with 'T-' (got {v!r})")
        return v

    @field_validator("estimated_tokens")
    @classmethod
    def _token_bound(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("estimated_tokens must be positive")
        if v > 20_000:
            raise ValueError(
                f"estimated_tokens={v} exceeds 20K cap — split the task"
            )
        return v


class CyclicDAG(Exception):
    pass


class MissingDependency(Exception):
    pass


class TaskDAG(BaseModel):
    project_id: str
    tasks: list[TaskSpec]
    # M3.1 — `ortim extend` appends one `DagDelta` per extend cycle. Default
    # empty list keeps legacy task_dag.json files (pre-M3.1) loading cleanly
    # via Pydantic's default-on-missing semantics. The DagDelta schema
    # itself lives in runtime.extend.schema; we hold `dict` here to avoid
    # a runtime import cycle (extend imports TaskSpec from this module),
    # and the Orchestrator validator (M3.1.1) is the layer that enforces
    # delta-shape correctness.
    extensions: list[dict] = Field(default_factory=list)

    def max_task_id(self) -> int:
        """Return the highest numeric component of any existing task ID
        (e.g. T-007 → 7). Returns 0 when the DAG has no tasks. Used by
        the Orchestrator (M3.1.1) to assign continuous IDs to extend-cycle
        tasks. Tolerant of zero-padded and non-padded formats."""
        max_n = 0
        for t in self.tasks:
            tail = t.id.removeprefix("T-")
            try:
                n = int(tail)
            except ValueError:
                continue
            if n > max_n:
                max_n = n
        return max_n

    def validate_dag(self) -> None:
        """Raise on missing dependency or cycle."""
        ids = {t.id for t in self.tasks}
        if len(ids) != len(self.tasks):
            raise ValueError("Duplicate task IDs in DAG")

        for t in self.tasks:
            for dep in t.dependencies:
                if dep not in ids:
                    raise MissingDependency(
                        f"Task {t.id} depends on missing task {dep!r}"
                    )
                if dep == t.id:
                    raise CyclicDAG(f"Task {t.id} depends on itself")

        # Kahn's algorithm: if all nodes can be removed, DAG is acyclic.
        in_degree = {t.id: len(t.dependencies) for t in self.tasks}
        graph: dict[str, list[str]] = {t.id: [] for t in self.tasks}
        for t in self.tasks:
            for dep in t.dependencies:
                graph[dep].append(t.id)

        queue: deque[str] = deque(tid for tid, d in in_degree.items() if d == 0)
        visited = 0
        while queue:
            current = queue.popleft()
            visited += 1
            for neighbor in graph[current]:
                in_degree[neighbor] -= 1
                if in_degree[neighbor] == 0:
                    queue.append(neighbor)

        if visited != len(self.tasks):
            raise CyclicDAG("DAG contains a cycle")

    def topological_batches(self) -> list[list[str]]:
        """Return groups of task IDs that can run in parallel.

        Each batch contains tasks whose dependencies are all in earlier
        batches. Tasks within a batch are independent.
        """
        self.validate_dag()
        in_degree = {t.id: len(t.dependencies) for t in self.tasks}
        graph: dict[str, list[str]] = {t.id: [] for t in self.tasks}
        for t in self.tasks:
            for dep in t.dependencies:
                graph[dep].append(t.id)

        batches: list[list[str]] = []
        remaining = set(in_degree)
        while remaining:
            batch = sorted(tid for tid in remaining if in_degree[tid] == 0)
            if not batch:
                raise CyclicDAG("DAG contains a cycle")
            batches.append(batch)
            for tid in batch:
                remaining.remove(tid)
                for neighbor in graph[tid]:
                    in_degree[neighbor] -= 1
        return batches

    def total_estimated_tokens(self) -> int:
        return sum(t.estimated_tokens for t in self.tasks)
