# M5 — Knowledge Layer: RAG (project-local) + MCP (read-only)

**Status:** Design draft v0 — 2026-05-14. To be locked after one pass of user review.
**Effort estimate:** ~2-3 weeks total across **4 sub-phases** (M5.0 → M5.3). M5.0 alone is shippable in ~5-7 days.
**Companion docs:** `docs/M5-premortem.md` (failure scenarios → design constraints), `docs/backlog.md` (open items M5 targets).

---

## 1. The problem M5 solves

Per backlog OPEN items, three classes of pain persist after proof-point v3:

| Class | Items | Why prompt/contract fixes won't close it |
|---|---|---|
| **Cross-run amnesia** | "First run learns; second run re-learns from scratch" | The system has no place to persist what it observed last time. Adding "remember X" to the prompt makes prompts grow; doesn't survive process exits. |
| **Stateless-agent non-determinism** | 45 (IntentAnalyst) — same brief → different `GoldenPathInputs` | Temperature already 0.0; sampling variance comes from model itself. Anchoring on a prior trusted output stabilizes the distribution. |
| **Pattern reuse manual** | Skills system (M3) is human-curated. No path from "we solved this once" to "future runs see the solution" | Skills loader is keyword-triggered, content is static. Successful prior task outputs are invisible to future runs. |

M5 introduces a **knowledge layer** between persistence (workspace, audit log) and agents. Knowledge is project-local in v0; cross-project deferred.

**What M5 explicitly is NOT:**
- Not a Reviewer assistant (per pre-mortem scenario 1).
- Not cross-project shared brain (per pre-mortem scenario 2).
- Not a code-file embedder (per pre-mortem scenario 3 — code is already retrievable via `read_files`).
- Not a write-capable MCP (M5.3 ships read-only; write deferred to a later sub-phase or never).

---

## 2. Locked design decisions

| # | Question | Decision | Why |
|---|---|---|---|
| 1 | Scope | **Project-local only** in v0. No vault, no cross-project retrieval. | Pre-mortem scenario 2; controls blast radius. Cross-project added after v0 proven valuable. |
| 2 | Consumer agents | **IntentAnalyst, Architect Call 1+2, StackAnalyst, Worker, Documenter.** **Reviewer EXCLUDED.** | Pre-mortem scenario 1: retrieved past verdicts contaminate fresh rubric evaluation. Reviewer determinism is a Phase 0 guarantee we don't trade away. |
| 3 | Indexed corpus | Locked PRD; locked RFC; locked stack.json; per-task DONE outputs (summary, not code); filtered audit decisions (reviewer verdicts, gate decisions, retry reasons); active skills referenced. | Pre-mortem scenario 3: code files not indexed (high cost, marginal value over `read_files`). Capped at ~500KB per project = ~$0.01 OpenAI embedding cost. |
| 4 | Store abstraction | `MemoryStore` Protocol. Implementations: `SqliteFtsStore` (lexical baseline, zero-cost), `QdrantStore` (vector + filters, M5.1), `ChromaStore` (alt). | Pre-mortem scenario 6; vendor lock prevention. M5.0 ships `SqliteFtsStore` only — proves value before paying for embeddings. |
| 5 | Embedding abstraction | `EmbeddingProvider` Protocol. Implementations: `OpenAIEmbedding` (text-embedding-3-small), `LocalSentenceTransformer` (`bge-small-en-v1.5`). | Same as 4. Local provider is the cost-cap fallback. |
| 6 | Retrieval is **advisory**, not authoritative | Retrieved chunks injected as `## Project Memory — reference only` block. Agent prompts explicitly say "re-derive from current inputs; priors are reference, not answer". | Pre-mortem scenario 5: prevents locking in early wrong outputs as canonical. |
| 7 | Retrieval default filter | `terminal_outcome = DONE` only. Failed-run chunks excluded by default. Override via env. | Pre-mortem scenario 5. Don't teach future runs from runs that ended in HITL. |
| 8 | Indexing trigger | State-transition hooks: `PRD_APPROVED` → index PRD; `RFC_APPROVED` → index RFC + locked stack; per-task `DONE` in `task_status.json` → index task summary + verdict. Audit `memory_indexed` event. | Incremental, idempotent, no batch job. Reuses existing transition machinery. |
| 9 | Feature flag | `AI_FACTORY_M5_RAG=on\|off`. **Default off** until proof-point v4 validates. | Pre-mortem cross-cutting safeguard 2. Existing pipeline fully functional with flag off. |
| 10 | Cost ceiling | `AI_FACTORY_M5_BUDGET_USD_PER_PROJECT=5.00` env. Hit → `embedding_budget_exceeded` audit event + auto-degrade to `SqliteFtsStore`. | Pre-mortem scenario 3. |
| 11 | Replay corpus | N=5 frozen E2E runs (v1/v2/v3 proof-points + 2 others) under `tests/fixtures/replay/`. M5 acceptance: replay outcomes bit-identical (Reviewer paths) or strictly better (Worker/Architect paths). | Pre-mortem cross-cutting safeguard 1. Honest measurement, not eyeballing. |
| 12 | MCP scope (M5.3 only) | **Read-only** servers: `filesystem` (read), `git` (log/blame). Write tools NOT exposed in v0. All calls through `runtime/mcp/proxy.py` sandbox wrapper. | Pre-mortem scenario 4. Defer write integration until proxy battle-tested. |

**Deferred to M6+:** Vault-wide cross-project memory; embedding-based skill mining (auto-derive skills from successful runs); RAG-driven drift detector; MCP write-tool integration; multi-tenant memory isolation.

---

## 3. Sub-phasing

```
M5-0 (this doc) ─── design lock
  ├─ M5.0  Foundation + IntentAnalyst (5-7 days)
  │   ├── MemoryStore Protocol + SqliteFtsStore (lexical, zero-cost)
  │   ├── Indexer (PRD/RFC/stack on state transitions)
  │   ├── Retriever facade
  │   ├── IntentAnalyst threading (targets Item 45)
  │   ├── Feature flag + replay corpus
  │   └── E2E proof-point v4a — expects: IntentAnalyst deterministic across replays
  │
  ├─ M5.1  Vector layer + Worker/Architect consumers (5-7 days)
  │   ├── EmbeddingProvider Protocol + OpenAI + Local impls
  │   ├── QdrantStore + ChromaStore
  │   ├── Cost cap gate
  │   ├── Worker / Architect Call 1+2 / StackAnalyst threading
  │   └── E2E proof-point v4b — expects: Worker code quality stable; cost < $0.50
  │
  ├─ M5.2  Audit indexing + Documenter (3-5 days)
  │   ├── Filtered audit chunking (reviewer verdicts, gate decisions, retry reasons)
  │   ├── Documenter threading — README cites prior decisions
  │   └── E2E proof-point v4c — expects: README references 3+ audit events
  │
  └─ M5.3  MCP read-only (3-5 days)
      ├── runtime/mcp/proxy.py sandbox wrapper
      ├── filesystem (read) + git (log/blame) servers
      ├── Worker MCP tool advertising (read-only)
      └── E2E proof-point v4d — expects: zero McpSandboxViolation; tool calls audited
```

**Each sub-phase has its own proof-point E2E and its own backlog row.** Don't ship cumulatively. If M5.0 proof-point shows regression, M5.1 doesn't start.

---

## 4. Schemas

```python
@dataclass(frozen=True)
class Chunk:
    """One indexed unit. Embedding provider produces a vector for `text`;
    metadata is filterable at search time."""
    chunk_id: str           # uuid
    project_id: str
    doc_type: str           # "prd" | "rfc" | "stack" | "task_output" | "audit_decision" | "skill"
    source_path: str        # relative to workspace
    text: str               # the actual indexed content
    token_count: int        # for budget accounting
    metadata: dict[str, Any]  # {tier, app_class, terminal_outcome, agent_role_target, task_id?, created_at}


@dataclass(frozen=True)
class RetrievalResult:
    chunks: list[Chunk]
    query: str
    filters: dict[str, Any]
    elapsed_ms: int


@dataclass(frozen=True)
class StoreStats:
    project_id: str
    chunk_count: int
    total_tokens: int
    by_doc_type: dict[str, int]
    last_indexed_at: str | None    # ISO timestamp
```

---

## 5. Contracts

### 5.1 MemoryStore Protocol

```python
class MemoryStore(Protocol):
    """Project-namespaced indexed memory. Implementations differ in
    backing store and retrieval algorithm."""

    def index(self, project_id: str, chunks: list[Chunk]) -> None:
        """Idempotent: re-indexing the same chunk_id is a no-op unless
        text hash changed."""

    def search(
        self,
        project_id: str,
        query: str,
        *,
        k: int = 5,
        filters: dict[str, Any] | None = None,
    ) -> RetrievalResult:
        """Return top-k chunks for `query` within `project_id`.
        `filters` is a dict of metadata equality checks; chunks not
        matching are excluded BEFORE similarity ranking."""

    def delete_project(self, project_id: str) -> None:
        """Tear-down for `ortim memory clear <project_id>`."""

    def stats(self, project_id: str) -> StoreStats: ...
```

### 5.2 EmbeddingProvider Protocol (M5.1+)

```python
class EmbeddingProvider(Protocol):
    def embed(self, texts: list[str]) -> list[list[float]]: ...
    def model_name(self) -> str: ...
    def dim(self) -> int: ...
    def cost_estimate_usd(self, total_tokens: int) -> float: ...
```

### 5.3 Indexer

```python
def index_state_transition(
    *,
    project_id: str,
    workspace: Path,
    transition: ProjectState,
    store: MemoryStore,
    audit: AuditLogger,
) -> None:
    """Called by orchestrator on each PRD_APPROVED / RFC_APPROVED / per-DONE
    transition. Reads the relevant artifact, chunks it, applies content-hash
    check (skip if unchanged), indexes via `store.index`, emits
    `memory_indexed` audit event with chunk count + token total."""
```

### 5.4 Retriever facade

```python
def retrieve_for_agent(
    *,
    project_id: str,
    agent_role: str,        # "intent_analyst" | "architect_call_1" | ... ; Reviewer rejected
    query: str,
    store: MemoryStore,
    audit: AuditLogger,
    k: int = 5,
    extra_filters: dict[str, Any] | None = None,
) -> list[Chunk]:
    """Single entry point for all agent retrieval calls. Applies the
    default `terminal_outcome=DONE` filter, raises if agent_role is in
    the exclusion list (currently `reviewer`), emits `memory_retrieved`
    audit event with query+chunk_ids."""
```

### 5.5 Per-agent threading

Every consumer agent's `execute()` signature gains:

```python
def execute(self, ..., retrieved_context: list[Chunk] | None = None) -> ...:
```

`retrieved_context=None` is the default and preserves M2/M3/M4 behavior bit-for-bit. The runner builds the list via `retrieve_for_agent(...)` only when `AI_FACTORY_M5_RAG=on`.

---

## 6. Prompt injection

System prompt for each consumer agent gains a new section, after L1 / Skills, before related_files:

```
## Project Memory — reference only

The following passages are retrieved from this project's prior artifacts.
They are reference context. Re-derive your output from the current task
inputs; do not copy from the passages.

### From {doc_type} ({source_path}, created {created_at})
{text}

---
{next chunk}
```

Hard rules in each agent's `.md` file:
- "Project Memory is advisory. The current task inputs override any pattern in retrieved passages."
- "If Project Memory contradicts the current locked stack / locked PRD / current acceptance criteria, follow the current inputs and emit `[retrieval_conflict]` in your reasoning."

---

## 7. State machine deltas

**None for M5.0–M5.2.** Indexing hooks into existing transitions:
- `PRD_DRAFTING → PRD_APPROVED`: index PRD
- `RFC_DRAFTING → RFC_APPROVED`: index RFC + locked_stack
- Per-task `task_status` change to `DONE`: index task summary + verdict + filtered audit slice

For M5.3 (MCP), no new states either. MCP calls happen inside Worker execution; sandbox proxy enforces scope. If a future MCP write integration needs interactive permission, that would be a `MCP_AWAITING_GRANT` state — out of scope for v0.

---

## 8. CLI surface

```
ortim memory stats <project_id>      # show StoreStats
ortim memory clear <project_id>      # delete all chunks for project
ortim memory query <project_id> "<query>" [--agent intent_analyst] [--k 5]
                                     # debug retrieval; bypasses agent flow
ortim memory rebuild <project_id>    # force re-index from current workspace
```

Existing commands unaffected. `ortim run` / `run-all` simply gain audit events when flag is on.

---

## 9. Acceptance criteria (binary, per Hard Rule 10)

### M5.0

1. `MemoryStore` Protocol has at least one concrete implementation (`SqliteFtsStore`) with passing tests for `index`, `search`, `delete_project`, `stats`.
2. Indexer fires exactly once per `PRD_APPROVED` transition (audit `memory_indexed` event count == 1 for that transition).
3. Re-indexing the same content (no hash change) produces zero new chunks (idempotent test).
4. Replay corpus: 5 frozen runs replayed with `AI_FACTORY_M5_RAG=off` produce outputs bit-identical to pre-M5 baseline (regression test fixture).
5. Replay corpus: 5 frozen runs replayed with `AI_FACTORY_M5_RAG=on` produce `IntentAnalyst` outputs identical across 3 successive replays of the same fixture (determinism test).
6. `retrieve_for_agent(agent_role="reviewer", ...)` raises `MemoryAccessForbidden` (test asserts).
7. CLI `ortim memory stats <id>` returns non-zero `chunk_count` after a full run with flag on.

### M5.1

8. `EmbeddingProvider` Protocol has `OpenAIEmbedding` + `LocalSentenceTransformer` implementations.
9. `QdrantStore` passes the same conformance tests as `SqliteFtsStore`.
10. Cost gate: indexing a synthetic 1MB document with `OpenAIEmbedding` and `AI_FACTORY_M5_BUDGET_USD_PER_PROJECT=0.01` triggers exactly one `embedding_budget_exceeded` audit event and degrades to `SqliteFtsStore`.
11. Worker retrieval injection produces `## Project Memory` block in prompt only when flag on AND `retrieved_context` non-empty (snapshot test).

### M5.2

12. Audit chunking includes reviewer verdicts and excludes raw LLM responses (sensitivity filter test).
13. Documenter README first-draft includes `[mem]`-tagged references to ≥3 audit events on a full run with flag on.

### M5.3

14. `runtime/mcp/proxy.py` raises `McpSandboxViolation` when a tool attempts a write outside `task.module_scope` (test asserts).
15. `mcp_tool_call` audit event emitted with `tool_name`, `arguments_hash`, `result_hash`, `elapsed_ms`.

---

## 10. Test count target

| Sub-phase | New tests | Cumulative |
|---|---|---|
| M5.0 | +30 (store conformance, indexer, retriever, IntentAnalyst threading, replay determinism, feature flag, CLI) | 328 → ~358 |
| M5.1 | +27 (embedding providers, Qdrant, Worker/Architect/StackAnalyst threading, cost cap) | 358 → ~385 |
| M5.2 | +15 (audit chunking, sensitivity filter, Documenter threading) | 385 → ~400 |
| M5.3 | +15 (MCP proxy, sandbox-violation, audit event shape) | 400 → ~415 |
| **Total** | **+87** | **328 → ~415** |

Buffer ~5 per sub-phase for E2E-observed tweaks.

---

## 11. File layout (anticipated)

```
runtime/memory/
├── __init__.py
├── schema.py              # Chunk, RetrievalResult, StoreStats dataclasses
├── store.py               # MemoryStore Protocol + SqliteFtsStore impl (M5.0)
├── indexer.py             # state-transition hooks (M5.0)
├── retriever.py           # retrieve_for_agent facade (M5.0)
├── embed.py               # EmbeddingProvider Protocol + impls (M5.1)
├── qdrant_store.py        # QdrantStore impl (M5.1)
├── chroma_store.py        # ChromaStore impl (M5.1, optional)
├── audit_filter.py        # what audit decisions are indexable (M5.2)
└── loader.py              # existing MemoryLoader (markdown) — unchanged

runtime/mcp/                # NEW dir
├── __init__.py
├── proxy.py               # sandbox-wrapping MCP proxy (M5.3)
├── servers.py             # filesystem + git server bindings (M5.3)

agents/
├── intent_analyst.md      # gains "## Project Memory" prompt block (M5.0)
├── architect.md           # same (M5.1)
├── stack_analyst.md       # same (M5.1)
├── worker.md              # same (M5.1)
├── documenter.md          # same (M5.2)
# reviewer.md UNCHANGED (excluded by design)

tests/
├── test_memory_store_sqlite.py        (M5.0)
├── test_memory_indexer.py             (M5.0)
├── test_memory_retriever.py           (M5.0)
├── test_memory_intent_analyst.py      (M5.0)
├── test_memory_replay_corpus.py       (M5.0 — uses fixtures/replay/)
├── test_memory_embeddings.py          (M5.1)
├── test_memory_store_qdrant.py        (M5.1)
├── test_memory_cost_gate.py           (M5.1)
├── test_memory_worker_thread.py       (M5.1)
├── test_memory_audit_filter.py        (M5.2)
├── test_memory_documenter.py          (M5.2)
├── test_mcp_proxy.py                  (M5.3)
└── fixtures/replay/                   (M5.0 — 5 frozen E2E runs)
```

---

## 12. Risks

| Risk | Likelihood | Mitigation | Pre-mortem ref |
|---|---|---|---|
| Reviewer contamination via retrieved verdicts | High | Reviewer excluded from consumer list; replay corpus enforces bit-identity | Scenario 1 |
| Cross-project poisoning | Medium | Project-local only in v0; metadata structure ready for future cross-project filtering | Scenario 2 |
| Embedding cost explosion | Medium | Enumerated corpus; cost cap env; lexical fallback; local embedding option | Scenario 3 |
| MCP sandbox bypass | Medium | All MCP calls through `proxy.py`; write tools deferred entirely | Scenario 4 |
| RAG reinforces early wrong outputs | Low | `terminal_outcome=DONE` filter default; retrieval is advisory not authoritative; manual exclude CLI | Scenario 5 |
| Vendor lock / model deprecation | Low | Protocol-based abstractions; `MemoryStore` + `EmbeddingProvider` swappable via config | Scenario 6 |
| Discovery cadence inside M5 | **High** | 4 sub-phases each with own proof-point; backlog rows opened per sub-phase; mid-M5 pre-mortem revisit | Scenario 7 |
| Value claim doesn't materialize | Low-Medium | Pre-build mapping (§13 below) explicitly lists which open items M5 should close; if list is weak, defer M5 | Scenario 8 |

---

## 13. Value mapping — which backlog OPEN items does M5 actually close?

> **Update 2026-05-14 (post option-A + option-C).** Items 43, BaaS-drift, UI-text-match, AND 45 all closed via prompt/skill fixes in <4 hours, **before any M5 code was written**. Item 45 was specifically tested empirically (`scripts/item_45_empirical.py`): 5/5 deterministic on the v4 PRD. The autonomy-jump value claim that originally framed M5 (Item 45 stabilization) is now structurally answered without RAG. **This is the "value claim doesn't materialize" failure mode from pre-mortem Scenario 8, validated pre-build.** The original table is preserved below for historical reference; see §13.1 for the revised framing.

### 13.0 Original value-mapping (pre-2026-05-14, kept for context)

| Backlog item | M5 addresses? | How |
|---|---|---|
| **45** — IntentAnalyst non-determinism | ✅ Yes (M5.0) | IntentAnalyst retrieves prior `GoldenPathInputs` for similar briefs as advisory context; reduces sampling variance through anchoring |
| **43** — Reviewer cosmetic conflation (stack.json vs RFC §4) | ❌ No | Reviewer excluded from M5. Prompt fix in `agents/reviewer.md` is the right tool, ~15 min. |
| **BaaS-drift** — StackAnalyst proposes Node+Hono for browser intent | 🟡 Partial (M5.1) | StackAnalyst retrieves prior successful stack picks for similar app classes; helps but doesn't fix the heuristic itself |
| **UI-text-match** — Worker emoji-prefix vs bare-string mismatch | 🟡 Partial (M5.1) | Worker retrieves prior test patterns; primary fix is a skill (`skills/react/ui-test-text-matching.md`), ~20 min |
| **7b** — `_run_all_loop` parallel retry | ❌ No | Concurrency bug, unrelated to memory |
| **4b** — tier template matrix | ❌ No | Bootstrap deps, unrelated |

**Honest reading (original).** M5 closes one P1 item (45) cleanly; partially helps two P2/P3 items; doesn't touch the rest of the open list.

### 13.1 Revised value-mapping (post 2026-05-14)

| Backlog item | M5 addresses? | What actually closed it |
|---|---|---|
| **45** — Architect `extract_inputs` non-determinism | ❌ Closed by prompt fix | `agents/architect.md` Call 1 derivation rules + few-shot. Empirically: 5/5 deterministic. |
| **43** — Reviewer cosmetic conflation | ❌ Closed by prompt fix | `agents/reviewer.md` Hard Rule 8. |
| **BaaS-drift** | ❌ Closed by prompt fix | `agents/stack_analyst.md` Browser-only detection. v4: 1/1 autonomous correct pick. |
| **UI-text-match** | ❌ Closed by new skill | `skills/react/ui-test-text-matching.md`. Live validation deferred. |
| **47, 47b** | ❌ Closed by bootstrap fix | Code, not memory. |
| **7b, 4b, 18b/c, 39b'/c, README-stale** | ❌ No | Concurrency / bootstrap / niche / hygiene — all unrelated to memory. |

**M5 closes ZERO currently-open backlog items.** This is the cleanest possible result of pre-mortem Scenario 8 — the value claim was tested before commitment.

### 13.2 What is M5 actually for, then?

Defensible as **platform foundation** for future capabilities; not as a fix for any currently-known pain.

| Purpose | Today's value | When does it become P0? |
|---|---|---|
| Anti-amnesia across runs | Low — current per-run cost ($0.10-0.30) isn't a budget crisis | When users start regenerating from same brief (iterative dev workflow) |
| Drift detector (RFC ↔ code over time) | Medium — but no "extend" flow shipping today | When `ortim extend` (M3.1, deferred from original M3 scope) ships |
| Skill auto-mining | Medium — manual curation works for 5 skills | When skill count > 30 and manual curation breaks |
| Multi-session continuity | Low-Medium — workspace state already persists | When users report "lost work" between sessions (none today) |
| MCP read-only tools | Medium — extends M1 brownfield reader | When brownfield extension flows become primary use case |

**None are P0 today.** All are P2-P3 "nice when needed".

### 13.3 Recommended scope shift — three options

**Option α — Defer M5 entirely.** Ship the prompt/skill/bootstrap fixes that just landed (which is the bulk of what proof-points v1→v4 demanded), then move to the next demonstrable user value. Strong candidates: M3.1 `ortim extend` (iterative development on shipped projects — backlog item 5), Enterprise tier MVP, README hygiene + PyPI publish prep (SQ-1, README-stale).

**Option β — Ship M5.0 only (Foundation skeleton).** Build `MemoryStore` Protocol + `SqliteFtsStore` + indexer + retriever facade WITHOUT consumer wiring. ~3-5 days. Future capabilities (drift detector, skill miner) plug in then. Don't ship M5.1/0.2/0.3 unless and until a real consumer needs them. Replays + cost cap stay in M5.0 acceptance.

**Option γ — Ship full M5 (M5.0 + 0.1 + 0.2 + 0.3) as originally designed.** Honest cost: 2-3 weeks. Value over Option β: marginal until post-M5 capabilities (drift detector, skill miner) also ship. **Not recommended** absent a specific use-case demand.

**Recommendation: Option α.** The "validate via cheap fixes first" loop (option-A + option-C this session) shipped 6 backlog items in <4 hours. Continuing that discipline means: identify the next concrete user pain, fix with the cheapest tool that works, only invest in infrastructure when a real consumer needs it. M5 returns to the queue as an explicit, justified investment when (and only when) drift detection / skill mining / extend-flow continuity become priorities.

---

## 14. Open design questions for second-pass review

1. **Replay corpus capture** — How do we freeze a "run" reproducibly? Audit log + workspace artifacts + LLM responses snapshot? Need to decide before M5.0 writes the first test.
2. **`SqliteFtsStore` vs `QdrantStore` semantics gap** — FTS5 is lexical (BM25); vector store is semantic. Will `retrieve_for_agent` return surprisingly different chunks across stores? Mitigation: define conformance test set that both must pass; tolerate some divergence as long as relevance@5 stays above a threshold.
3. **Indexer-on-state-transition vs indexer-on-commit** — current design hooks transitions. But what about Worker output that was approved but not yet merged? Index at `DONE` or at merge complete? **Tentative answer:** at `DONE` (Reviewer approval is the gate; merge is mechanical).
4. **Cost cap precision** — `embedding_budget_exceeded` per-project. What about workspace-shared costs (one user, many projects)? Add a global cap env too? **Tentative answer:** per-project cap is enough for v0; global cap is a v1 polish.
5. **`text-embedding-3-small` vs newer** — At design time `text-embedding-3-small` is 1536-dim, $0.02/1M tokens. If a smaller/cheaper model exists at impl time (e.g., `-mini`), swap is a config line. Just keep the dim configurable in `QdrantStore`.
6. **MCP server packaging** — Do we bundle `mcp-server-filesystem` / `mcp-server-git` as deps, or expect user to install them externally and configure paths? **Tentative answer:** soft dep — `ortim memory init --with-mcp` installs them if missing; manual install is fine.
7. **Pillar mapping confirmation** — M5 covers Pillars 5 (RAG) + 7 (MCP) per memory. Does this mapping still hold, or do we want to expand "Pillar 5 = Memory" beyond RAG (e.g., audit-log structured memory is also Pillar 5)?

---

## 15. Definition of Done — M5.0

- All 7 acceptance criteria for M5.0 pass (§9.1–7).
- `docs/backlog.md` row for "M5.0 — Foundation + IntentAnalyst" set to SHIPPED with date.
- Proof-point v4a executed on a fresh greenfield + flag on, audit shows non-zero `memory_retrieved` events for IntentAnalyst, replay corpus determinism test green.
- Pre-mortem revisit (§ in M5-premortem.md): re-read scenarios 1–8 against actual M5.0 behavior; surface any new failure modes into pre-mortem before M5.1 starts.
- README.md updated to reflect M5.0 status.
- No regression: full pytest suite green; existing E2E (web-todo-m2 replay) produces unchanged outputs with flag off.

M5.1 / M5.2 / M5.3 each get their own DoD section in this file after design lock.
