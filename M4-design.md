# M4 — Cross-task export visibility

**Status:** Design lock — 2026-05-13. Closes tespit.md item 33 (cross-task interface mismatch) — the residual blocker after M3 Skills landed.
**Effort estimate:** ~1 session foundation + E2E re-validation on web-todo-m2. pytest 263 → ~280.
**Items closed structurally:** the remaining 2 of 4 categories of item 26 (cross-task invented imports, cross-task wrong shape) by giving Worker an AST-extracted view of prior task exports.

---

## 1. The problem M4 solves

Web-todo-m2 post-M3 T-004 retry showed:
- M3 skill `typescript-module-boundaries` taught Worker the **right module** to import from.
- T-002 exported `createTaskService(db)` (factory pattern) but T-004 wrote `import { createTask, getAllTasks, ... } from '../task-service'` — guessing bare functions.

Skills can't fix this because the right shape is a fact about the codebase, not a pattern. The Worker has only RFC + acceptance criteria + locked stack + skills as context — never the actual public exports of prior DONE tasks.

The brownfield path solved the equivalent problem via `read_related()` + `CodebaseSummary` (M1). Greenfield needs the same plumbing but sourced from prior tasks in this very DAG.

---

## 2. Locked design decisions

| # | Question | Decision | Why |
|---|---|---|---|
| 1 | What to surface? | **Export signatures**, not full bodies. For TS: the export declaration line(s) plus the immediate following block (function body up to first `{}` close, class up to `{`, interface/type fully). For Python: `ast.parse`-extracted `def`/`class`/top-level `Name = ...` rendered as one signature per line. | Bodies blow the token budget. Signatures convey the contract — that's enough to write a correct import. |
| 2 | Token budget | Per-module cap: **2,000 chars**. Total cap across all prior tasks: **8,000 chars** (≈ 2,000 tokens). Skills already eat 12K; combined ceiling stays under the Worker call's safe ~25K input. | Mirrors M3's 5×12K and `_DEFAULT_RELATED_BYTES=30K` (which is for full bodies). |
| 3 | Which prior tasks? | Only tasks marked `DONE` in `task_status.json`. Tasks marked PENDING / AWAITING_HITL are skipped (their exports may be stale or wrong). | Don't teach Worker a shape we know is unreviewed. |
| 4 | Filtering by dependency? | M4 surfaces ALL DONE tasks' exports, not just `task.dependencies`. The dependency graph reflects "logical sequencing" not "what types do you need to see" — over-sharing exports is cheap, under-sharing causes the bug we're closing. | If budget pressure shows up later we'll add dep-filtering as a separate decision. |
| 5 | What languages? | TypeScript / TSX / JavaScript + Python. The export extractor is regex-based for TS family (mirroring existing `_TS_EXPORT_RE`) and uses Python's `ast` module for `.py`. Dart/Go/Rust deferred. | TS+Python covers every E2E we've seen. Adding more is mechanical. |
| 6 | Trigger condition | Run when (a) `codebase_summary is None` (not a brownfield project) AND (b) the DAG has at least one prior DONE task. Brownfield projects already get `read_related` → no double-injection. | One pathway per project class keeps the prompt shape predictable. |
| 7 | Injection point | Worker prompt only, under `## Prior task exports — use these import shapes verbatim` after the L1 / Skills blocks, before related_files (which stays brownfield-only). | Reviewer can already see the actual files Worker emits; doesn't need the export view. Keeps reviewer prompt narrow. |
| 8 | Audit | `worker_output_ok` gains `prior_task_modules: list[str]` (module scopes whose exports were included). Skill audit pattern. | Lets post-mortem ask "did Worker see T-002's exports?" without re-deriving. |

**Deferred to M5+:** signature extraction via tree-sitter (real ASTs), per-tenant export visibility, version-pinning, multi-language coverage for Dart/Go/Rust, signature diff alerts when re-locked.

---

## 3. Schema

```python
@dataclass(frozen=True)
class ExportSignature:
    """One exported symbol from one prior-task file."""
    kind: str          # "function", "class", "interface", "type", "const", "default"
    name: str          # symbol name; "default" for `export default` without a name
    signature: str     # one-line summary: "function foo(x: number): string"


@dataclass(frozen=True)
class ModuleExports:
    """Public surface of one prior-task module — what its index.ts /
    package barrel exposes to siblings."""
    module: str                     # module_scope, e.g. "task-service"
    files: dict[str, list[ExportSignature]]  # path → exports
    truncated: bool                 # True if budget cap dropped entries
```

---

## 4. Extractor contract

```python
def extract_exports(path: Path, source: str) -> list[ExportSignature]:
    """Per-file export extraction. Returns [] for unsupported languages
    or files with no exports. Never raises — malformed source produces
    a best-effort list."""
```

Implementation:
- `*.ts`, `*.tsx`, `*.js`, `*.jsx`: regex over the source. Patterns mirror `runtime/codebase/reader.py:_TS_EXPORT_RE` but capture the full first line (up to `{` or `=>` or `;`) so the signature carries through.
- `*.py`: `ast.parse(source)`; iterate top-level `FunctionDef` / `AsyncFunctionDef` / `ClassDef` / `Assign` whose target name doesn't start with `_`. Render signatures via the `ast.unparse(...)` of `def foo(...)`-style nodes.
- Other extensions: return `[]`.

---

## 5. Collector contract

```python
def collect_prior_outputs(
    *,
    workspace: Path,
    dag: TaskDAG,
    status_file: TaskStatusFile,
    current_task_id: str,
    char_budget_per_module: int = 2_000,
    total_char_budget: int = 8_000,
) -> dict[str, ModuleExports]:
    """Walk every DONE task != current_task, read its module_scope files,
    extract exports. Budget-cap per module and overall. Returns module
    name → ModuleExports."""
```

Algorithm:
1. Find every task in `dag.tasks` that is in `status_file.records` with `status == DONE` and is not `current_task_id`.
2. Group by `module_scope`. Multiple tasks can share a scope (e.g. T-003 + T-004 both `ui-components`); merge their exports into one ModuleExports.
3. For each module, walk the scope directory, read every `.ts/.tsx/.js/.jsx/.py` file, extract exports.
4. Compute per-file char usage from the rendered signatures; drop files when `per_module_total > char_budget_per_module`. Truncated=True.
5. Compute total across modules; drop modules when `total_total > total_char_budget`. Drop deterministically (alphabetical), keep `truncated=True` on the dropped scopes' siblings.

---

## 6. Injection contract

```python
def format_prior_outputs_block(modules: dict[str, ModuleExports]) -> str:
    """Render as a Worker system prompt block:

      ## Prior task exports — use these import shapes verbatim

      ### task-service (../task-service)
      <export signatures rendered as a TS code block>

      ### db-adapter (../db-adapter)
      <...>
    """
```

`WorkerAgent.execute(..., prior_task_exports: dict[str, ModuleExports] | None = None)` injects this block after the L1 + Skills block, before the `## Related existing files` block.

System prompt section ordering becomes:
1. Worker base prompt
2. `## L1 Immutable Principles`
3. `## Active Skills` (M3)
4. `## Prior task exports` (M4 — new)
5. (`## Related existing files` is in user prompt for brownfield)

---

## 7. Runner threading

```python
# in runner.execute_task(), before the Worker call:

prior_task_exports: dict[str, ModuleExports] | None = None
if codebase_summary is None and status_file.records:
    prior_task_exports = collect_prior_outputs(
        workspace=task_workspace,
        dag=dag,           # NEW param
        status_file=status_file,
        current_task_id=task.id,
    ) or None
```

`execute_task` accepts `dag: TaskDAG | None = None` so callers that don't have the DAG (none currently — but future tests) can opt out.

---

## 8. Faz sırası

```
M4-0 (this doc)
  └─ M4-1: extract_exports() + tests (TS regex + Python ast)
       └─ M4-2: collect_prior_outputs() + tests
            └─ M4-3: Worker prompt injection + runner threading + tests
                 └─ M4-4: E2E re-run on web-todo-m2 → expect tsc errors ≤ 2
```

Her faz commit-able. Test sayım hedefi: 263 → **~278** (+15 new).

---

## 9. Test sayım hedefi

| Dosya | Yeni testler |
|---|---|
| `tests/test_export_extractor.py` (yeni) | +5 (TS named function, default function, class, interface, Python def/class) |
| `tests/test_prior_outputs.py` (yeni) | +4 (only DONE tasks, current excluded, per-module budget, total budget) |
| `tests/test_prior_outputs_injection.py` (yeni) | +3 (block lands in prompt, empty → no block, audit captures module list) |
| **Toplam** | **+12** → pytest 263 → **275** |

(Buffer for E2E observation tweaks: ~3 extra tests.)

---

## 10. Riskler

| Risk | Olasılık | Mitigation |
|---|---|---|
| Regex extractor misses an export pattern (e.g. `export { foo, bar } from './x'`) | Orta | M4 ships the common 5 patterns; add `export { ... }` re-export support in a small follow-up if it surfaces. |
| Worker over-trusts export signatures and ignores RFC | Düşük | Block frames signatures as "import shapes" not "the architecture". RFC stays the source of truth for what to build. |
| Budget overflow when DAG has 20+ DONE tasks | Düşük | Per-module + total caps + alphabetical drop order. Audit logs `truncated` so we can spot the overflow later. |
| Tree-sitter rabbit hole | Düşük | Explicitly out of scope — regex MVP first, upgrade later when we see a real false-positive. |
| Reading prior tasks' files races with parallel run-all merge | Orta | `collect_prior_outputs` runs in the sequential branch of run-all today (single thread per task). For parallel branch, defer to the merge lock — same lock controls writes. |
