# SPDX-License-Identifier: FSL-1.1-Apache-2.0
# Copyright (c) 2026 ortim.dev
"""collect_prior_outputs — M4 cross-task export visibility.

Walks every DONE task in the DAG (except the current one), reads every
source file under its `module_scope`, extracts exports via
`runtime.codebase.exports.extract_exports`, and renders a budget-capped
view ready for Worker prompt injection.

The brownfield equivalent (`read_related`) reads FULL file bodies for a
single in-scope module; this layer reads ONLY export signatures across
every prior module, so the two budgets are independent and additive.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from runtime.codebase.exports import ExportSignature, extract_exports

if TYPE_CHECKING:
    from runtime.executor.status import TaskStatusFile
    from runtime.orchestrator import TaskDAG, TaskSpec


DEFAULT_PER_MODULE_CHAR_BUDGET = 2_000
DEFAULT_TOTAL_CHAR_BUDGET = 8_000

_SUPPORTED_EXTS = frozenset(
    {".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".py"}
)


@dataclass
class ModuleExports:
    """Per-module aggregate of exports the Worker can see."""

    module: str
    files: dict[str, list[ExportSignature]] = field(default_factory=dict)
    truncated: bool = False


def collect_prior_outputs(
    *,
    workspace: Path,
    dag: "TaskDAG",
    status_file: "TaskStatusFile",
    current_task_id: str,
    per_module_char_budget: int = DEFAULT_PER_MODULE_CHAR_BUDGET,
    total_char_budget: int = DEFAULT_TOTAL_CHAR_BUDGET,
) -> dict[str, ModuleExports]:
    """Group DONE tasks by `module_scope`, walk each module's files,
    extract exports, and return budget-capped `ModuleExports` per scope.

    Tasks not in `status_file.records`, or with status != DONE, are
    skipped — we don't teach Worker about shapes that may still change.
    """
    done_tasks = _select_done_tasks(dag, status_file, exclude_id=current_task_id)
    if not done_tasks:
        return {}

    by_module: dict[str, list["TaskSpec"]] = {}
    for task in done_tasks:
        scope = primary_scope(task)
        by_module.setdefault(scope, []).append(task)

    # Build per-module exports in deterministic order so the rendered
    # block is stable across runs.
    modules: dict[str, ModuleExports] = {}
    total_chars = 0
    for module in sorted(by_module):
        mod_exports = ModuleExports(module=module)
        mod_chars = 0
        mod_path = workspace / module
        if not mod_path.exists() or not mod_path.is_dir():
            continue

        for file_path in sorted(_walk_source_files(mod_path)):
            rel = file_path.relative_to(workspace).as_posix()
            try:
                src = file_path.read_text(encoding="utf-8")
            except OSError:
                continue
            exports = extract_exports(file_path, src)
            if not exports:
                continue
            cost = _signatures_cost(exports)
            if mod_chars + cost > per_module_char_budget:
                mod_exports.truncated = True
                break
            mod_exports.files[rel] = exports
            mod_chars += cost

        if not mod_exports.files:
            continue

        if total_chars + mod_chars > total_char_budget:
            # Mark every accepted module as truncated to signal the
            # drop, then stop adding new ones.
            for existing in modules.values():
                existing.truncated = True
            break

        modules[module] = mod_exports
        total_chars += mod_chars

    return modules


def format_prior_outputs_block(modules: dict[str, ModuleExports]) -> str:
    """Render as a Worker system prompt block. Empty input → empty
    string so callers can append unconditionally."""
    if not modules:
        return ""
    lines: list[str] = [
        "## Prior task exports — use these import shapes verbatim",
        "",
        "The following modules are already DONE. Import the names listed",
        "here exactly as shown; do NOT invent unlisted exports.",
        "",
    ]
    for module in sorted(modules):
        m = modules[module]
        lines.append(f"### {module}")
        if m.truncated:
            lines.append("_(truncated — some exports omitted under budget)_")
        for path in sorted(m.files):
            lines.append("")
            lines.append(f"`{path}`")
            lines.append("```ts")
            for sig in m.files[path]:
                lines.append(sig.signature)
            lines.append("```")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


# ---- helpers --------------------------------------------------------------


def _select_done_tasks(
    dag: "TaskDAG", status_file: "TaskStatusFile", *, exclude_id: str
) -> list:
    # Lazy import keeps `runtime.codebase` independent of
    # `runtime.executor` at module-load time (avoids a circular import
    # through executor/__init__.py).
    from runtime.executor.status import TaskStatus

    out = []
    for task in dag.tasks:
        if task.id == exclude_id:
            continue
        rec = status_file.records.get(task.id)
        if rec is None or rec.status != TaskStatus.DONE:
            continue
        out.append(task)
    return out


def primary_scope(task: "TaskSpec") -> str:
    """TaskSpec.module_scope may be a single str (legacy) or a list.
    Use the first entry as the primary scope. If the field doesn't
    exist for whatever reason, fall back to the task id."""
    scope = getattr(task, "module_scope", None)
    if isinstance(scope, list):
        return scope[0] if scope else task.id
    return scope or task.id


def _walk_source_files(root: Path):
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if path.suffix.lower() not in _SUPPORTED_EXTS:
            continue
        # Skip co-located test files — Worker doesn't need them as
        # import shapes (the impl file's exports are what's reachable).
        # Tests still get extracted if a downstream test imports them,
        # which is rare; keeping the prompt focused costs less.
        name = path.name.lower()
        if ".test." in name or ".spec." in name:
            continue
        yield path


def _signatures_cost(sigs: list[ExportSignature]) -> int:
    """Rough character cost — one line per signature plus a per-line
    overhead for the rendered block. Underestimates by a few percent
    which is fine for budget caps."""
    return sum(len(s.signature) + 6 for s in sigs)  # +6 for "kind/name + newline"
