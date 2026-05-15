# M5 Pre-Mortem

> **Method.** Imagine it's **3 weeks from now** (≈ 2026-06-04). We declared M5 RAG + MCP shipped. Then the next proof-point run revealed M5 made things *worse* or didn't deliver on its value claim. We're holding a post-mortem. **What does the failure look like?**
>
> Goal: surface failure modes BEFORE implementation, so M5-design.md can encode each one as either (a) an explicit acceptance criterion, (b) a deliberate scope exclusion, or (c) an early-warning signal we'll monitor during build.
>
> **Why this exists.** tespit.md shows we discover ~5-8 structural items per E2E run **after** shipping (41 → 41', 17 → 18 → 18a, 39 → 39a/b/c, 40+41+42 → 41'+44+46). M5 is 2-3 weeks of work; the same discovery cadence would mean ~15-25 new items mid-flight. Pre-mortem trades 1 hour now for a more contained build.

---

## Failure scenarios (ranked by likelihood × severity)

### Scenario 1 — "Retrieval contaminates the verdict" 🔴 *high likelihood, high severity*

**The failure.** M5 ships. Reviewer now retrieves prior similar verdicts from RAG and prepends them to its prompt as "## Project Memory". On the next proof-point, Reviewer **paraphrases** the retrieved past verdict instead of running the rubric fresh against the current code — confirming a verdict that's structurally wrong because the retrieved case wasn't actually analogous. Result: a regression of Phase 0 (item 9) and item 21 (length validator) gains. The proof-point self-driving rate drops from 83% (v3) to 60-65%.

**Root cause hypothesis.** LLMs anchor on retrieved content. The Reviewer rubric's whole point (Phase 0) was to make verdicts deterministic *given the rubric + code*; injecting retrieved prose puts a thumb on the scale.

**Early warning signal.** Audit log shows `reviewer_verdict.criteria_verdicts[i].evidence` text containing phrases that quote retrieved RAG passages verbatim rather than the current code (`code_quote` field). Add a validator: if `evidence` has >30% n-gram overlap with retrieved passage and <30% overlap with `code_quote`, flag `reviewer_retrieval_contamination`.

**Mitigation.**
- Reviewer is **excluded** from RAG retrieval in v0 of M5. Only Worker (planning side) and Documenter consume retrieved context.
- If we later admit Reviewer, the retrieval is **scoped to L1 principles + skill content** (already deterministic), never to past verdicts.
- M5-design acceptance criterion: "Reviewer rubric outcomes on a fixed-input replay set are bit-identical to pre-M5 outcomes." Hash a replay corpus.

---

### Scenario 2 — "Cross-project poisoning" 🟡 *medium likelihood, high severity*

**The failure.** If we ship cross-project shared knowledge (vault-wide), a stylistic choice or anti-pattern from project A leaks into project B's Worker prompts. User of project B says "my React code suddenly has Vue patterns" or "why is my CLI handler using FastAPI middleware shape". Trust collapses.

**Root cause hypothesis.** Vector similarity ≠ semantic relevance across stack/domain boundaries. `useState` patterns embed close to Flutter `StatefulWidget` patterns in embedding space; retrieval doesn't know they're not interchangeable.

**Early warning signal.** Audit `worker_retrieved_chunks` event with `source_project_id`, `source_stack`, `target_stack`. Mismatch beyond a small whitelist (e.g. `TypeScript` ↔ `JavaScript` OK; `TypeScript` ↔ `Rust` not) = warn.

**Mitigation.**
- M5 v0 ships **project-local only**. No cross-project retrieval. Period.
- M5 v1 (later) considers cross-project, but only with a **same-stack filter** at retrieval time (`WHERE locked_stack.primary_framework = $current`).
- Embedding-time metadata: every chunk carries `{project_id, stack, tier, app_class, source_path, agent_role}` and retrieval applies hard filters before similarity.

---

### Scenario 3 — "Embedding cost explosion" 🟡 *medium likelihood, medium severity*

**The failure.** We chose OpenAI `text-embedding-3-small` for embedding (per tespit.md line 1102). At ~$0.02 per 1M tokens. A real brownfield project (~50K files, ~10M tokens of code) costs $200 to index once. Re-indexing on each commit explodes. User abandons M5 after first cost statement.

**Root cause hypothesis.** Indexing scope wasn't bounded; we embedded all files instead of "documents that change rarely" (PRD, RFC, skills, completed tasks). No incremental indexing strategy.

**Early warning signal.** `embedding_cost_usd` per-project audit event with running total. Alert when single project > $5 in 24h.

**Mitigation.**
- M5-design must enumerate **exactly what gets indexed**: locked PRD (~5KB), locked RFC (~15KB), completed task outputs (~10KB each), audit decisions (~2KB/event filtered), skill files (~3KB each). Cap: ~500KB embeddable per typical project = ~$0.01.
- Code files are **not** embedded by default — they're already retrievable via `read_files` deterministic path; embedding gives marginal value for high cost.
- Incremental: re-embed only when an artifact's content hash changes. Idempotent.
- Local embedding fallback: `instructor-large` or `BAAI/bge-small-en-v1.5` via `sentence-transformers` for $0 marginal cost; quality dip acceptable for inner-loop retrieval.

---

### Scenario 4 — "MCP read-actions look free, write-actions break sandbox" 🟡 *medium likelihood, high severity*

**The failure.** We add MCP tool calling to Worker (per tespit.md line 1108). Worker calls `filesystem.write_file` for a "validation" purpose; the MCP server doesn't enforce `module_scope`; Worker now writes outside scope without triggering our sandbox. The whole sandbox guarantee is bypassed because MCP is a separate code path. Subsequent run produces inscrutable garbage and the user can't tell where the cross-module leak came from.

**Root cause hypothesis.** MCP tool calling is a parallel I/O channel; our sandbox lives in `runtime/executor/sandbox.py` between Worker output and disk write. MCP tools talk to disk directly via the MCP server process.

**Early warning signal.** `mcp_tool_call` audit event with `tool_name`, `arguments`, `result_hash`. Cross-reference against `module_scope` of the active task. Any write outside scope = alert.

**Mitigation.**
- **MCP is split into 13b explicitly: read-only tools first** (`git log`, `filesystem read`, `git blame`). Write tools require an explicit gate: `MCP_WRITE_ENABLED=true` env + scope wrapper.
- All MCP tool calls go through a sandbox proxy layer: `runtime/mcp/proxy.py` intercepts every tool call, applies `check_in_scope` and `check_extension` before dispatch.
- M5-design acceptance criterion: "No MCP tool call can write to a path outside the active task's `module_scope`. Proxy raises `McpSandboxViolation`."
- Defer write-tool integration to **M5.2** or later. Ship M5.1 (RAG + MCP read-only) first.

---

### Scenario 5 — "RAG becomes the IntentAnalyst stabilizer it was supposed to be — and locks in wrong choices" 🟠 *low likelihood, very high severity*

**The failure.** Item 45 (IntentAnalyst non-determinism) was M5's killer use case: same brief → same `GoldenPathInputs`. We ship M5: IntentAnalyst retrieves "what did we do last time for similar briefs?" and produces consistent output. But the first cached output for a given brief class was *wrong* (e.g., the v3 T4 result was the wrong tier — Architect ignored locked stack, item 46 had to patch around it). RAG now makes that wrong output reproducible forever for that brief class. Users see "consistent but wrong" — worse than non-deterministic.

**Root cause hypothesis.** Treating "first observed output" as canonical without a feedback loop. Reinforcement of bad early decisions.

**Early warning signal.** `intent_analyst_retrieved_prior` audit event with `prior_run_outcome: success|partial|fail`. If retrieved prior was a failed run, surface in UX: "Retrieving a prior analysis from a run that ended in HITL — proceed?".

**Mitigation.**
- Indexed runs are tagged with **terminal outcome**: `DONE`, `AWAITING_HITL`, `FAILED`. Retrieval **filters out non-DONE** by default (config-overridable).
- Even for DONE runs, retrieved chunks include the proof-point first-attempt rate and self-driving rate; low-quality runs deprioritized.
- Manual "blacklist this run from retrieval" affordance (CLI: `ortim memory exclude <project_id>`).
- IntentAnalyst's retrieval is **advisory**, not authoritative: response includes `retrieved_priors: [...]` but the LLM is instructed to "re-derive `GoldenPathInputs` from the current brief; priors are reference points only, not answers". Pin via prompt + test.

---

### Scenario 6 — "Embedding model deprecation / vendor lock" 🟢 *low likelihood, medium severity*

**The failure.** OpenAI deprecates `text-embedding-3-small` 8 months from now. We're locked in. Reindexing everything costs $X. Or we chose Qdrant binary format and now want to migrate to Chroma — but our index has 10M chunks. Migration is a week of work.

**Root cause hypothesis.** Embedding provider + vector store choice not made replaceable. No abstraction layer.

**Early warning signal.** None — this is a slow burn. Detected at deprecation announcement.

**Mitigation.**
- M5 ships with a **`MemoryStore` interface** (analogous to current `LLMClient` provider abstraction): `embed(text) -> vec`, `index(chunks)`, `search(query, k, filters)`. Concrete impls: `QdrantStore`, `ChromaStore`, `SqliteFtsStore` (lexical-only baseline).
- M5-design acceptance: switching from Qdrant to Chroma must be a config change + reindex, not a code rewrite.
- Embedding provider abstraction: `EmbeddingProvider`. Concrete: `OpenAIEmbedding`, `LocalSentenceTransformer`. Provider mapped in `~/.ai-factory/routing.yml` (extends M4 routing concept).

---

### Scenario 7 — "Discovery cadence repeats inside M5" 🔴 *high likelihood, medium severity*

**The failure.** We ship M5 in 3 weeks. The first proof-point run after M5 produces 5-8 new structural items (per the pattern shown in items 41→41', 17→18→18a). They cascade: fixing one surfaces the next. By week 5, M5 is "shipped" but not stable. Real M5 stabilization runs into M6+.

**Root cause hypothesis.** This is **the** systemic risk. M5 is 4-5× larger than any previous module (M2 was ~1 week, M3 ~1 week, M4 ~1 week, M5 ~2-3 weeks). The discovery surface scales with code surface.

**Early warning signal.** Track `new_item_emission_rate` per E2E run (audit-derived). Stable ratio for M2/M3/M4 was ~2-3 items per proof-point. If first post-M5 proof-point emits >5, we're in this scenario.

**Mitigation.**
- **Sub-phase M5.** Ship **M5.0 (RAG read-only, project-local, indexed corpus = PRD+RFC+locked-stack+skills)** as the smallest demoable cut. Proof-point. *Then* add M5.1 (audit log + completed-task indexing). *Then* M5.2 (MCP read-only). *Then* M5.3 (cross-project if value demonstrated).
- Each sub-phase gets its own proof-point E2E and its own line in backlog.md.
- Pre-commit gate: don't merge an M5 sub-phase until its proof-point passes the "first-attempt rate ≥ baseline" check (regression guard).

---

### Scenario 8 — "Value claim doesn't materialize" 🟠 *low likelihood, very high severity*

**The failure.** M5 ships. Proof-point v4 runs same brief as v3. The from-scratch self-driving rate is **still 83%, not 95%+**. RAG didn't help where it was supposed to. We can't explain to anyone why M5 was worth 3 weeks.

**Root cause hypothesis.** RAG addresses **memory** problems, but the open items at v3 (45 IntentAnalyst, 43 Reviewer cosmetic, BaaS drift, UI-text-match) are **not** memory problems — they're prompt/contract problems. RAG can't fix a contract gap.

**Early warning signal.** Pre-build mapping exercise: for each remaining open item that M5 *should* address, write out **exactly** the retrieval path that would prevent it. If we can't write that path, M5 doesn't address that item.

**Mitigation.**
- Before writing code: produce a table in M5-design.md mapping each backlog OPEN item to (a) M5 addresses it, with this retrieval path; (b) M5 does not address it, this is the right tool; (c) unsure. Items in (a) become M5's measurable success criteria.
- If the (a) list is empty or weak (just "stabilizes context across runs" without concrete examples), **don't ship M5 yet** — ship the prompt/contract fixes for items 45/43/BaaS/UI-text first.
- Honest framing pre-built: "M5 is the foundation for things we can't build without persistent memory (drift detector, learned skill mining, multi-session continuity). The 83% → 95% gap may or may not be what M5 closes; the structural enabler is the value."

---

## Cross-cutting safeguards (apply to all scenarios)

1. **Replay corpus.** Before M5 code is written, build a frozen replay corpus: N=5 known E2E runs (the v1/v2/v3 proof-points + 2 others). For each, `audit/decisions.jsonl` is the canonical input. M5 acceptance: replay corpus outcomes are bit-identical to pre-M5 (for Reviewer paths) or strictly better (for Worker/IntentAnalyst paths).

2. **Roll-forward toggle.** Every M5 capability is feature-flagged: `AI_FACTORY_M5_RAG=on|off`. Default off until proof-point v4 validates. Existing pipeline is fully functional with flag off.

3. **Cost ceiling.** `AI_FACTORY_M5_BUDGET_USD_PER_PROJECT=5.00` env. Hit → `embedding_budget_exceeded` audit event + degrade to lexical-only (SqliteFtsStore) for that project.

4. **Honest measurement.** A "self-driving rate" metric must be computed deterministically from audit log (same script for v1/v2/v3/v4) — not eyeballed from a per-run summary table. Bake this into `runtime/budget/tracker.py` or a sibling `runtime/metrics/`.

5. **Pre-mortem revisit.** This file gets a second pass **mid-M5** (~week 2 of build). If we discover new failure modes during build, they get added here, not just to tespit.md. The pre-mortem is a living risk register, not a one-shot exercise.

---

## What this pre-mortem changes about M5-design

When M5-design.md is drafted (Task #3), it must explicitly carry forward:

| From scenario | Into M5-design as |
|---|---|
| 1 (verdict contamination) | **Scope exclusion:** Reviewer is not a RAG consumer in v0. **Acceptance:** bit-identical Reviewer outcomes on replay corpus. |
| 2 (cross-project poison) | **Scope exclusion:** project-local only in v0. **Schema:** chunks carry `{project_id, stack, tier, app_class}` metadata even when filter not yet applied. |
| 3 (embedding cost) | **Scope:** enumerated indexed corpus (PRD/RFC/skills/completed-task-outputs/filtered-audit-decisions); code files excluded. **Budget gate:** $5/project default cap. **Abstraction:** `EmbeddingProvider` interface so local fallback is one config line away. |
| 4 (MCP sandbox bypass) | **Sub-phase split:** M5.2 (MCP read-only) separate from M5.0 (RAG). **Architecture:** all MCP calls go through `runtime/mcp/proxy.py` sandbox wrapper. **Acceptance:** McpSandboxViolation on out-of-scope write attempt. |
| 5 (locks in wrong) | **Filter rule:** retrieval defaults to `terminal_outcome=DONE` only. **UX:** retrieved priors surfaced as advisory, not authoritative. |
| 6 (vendor lock) | **Abstraction:** `MemoryStore` + `EmbeddingProvider` interfaces. **Acceptance:** Qdrant↔Chroma swap = config change. |
| 7 (discovery cascade) | **Phasing:** M5.0 → M5.1 → M5.2 → M5.3, each with its own proof-point. **Don't ship cumulatively.** |
| 8 (value claim) | **Pre-build exercise:** map each open backlog item to retrieval path or rule it out. **Honest framing:** if 83→95 gap is unmappable, M5 ships as foundation, not as autonomy-boost. |

**Output of this pre-mortem:** M5 splits into at least 4 sub-phases (M5.0/0.1/0.2/0.3). M5.0 alone is shippable in ~5-7 days. Full M5 stays at 2-3 weeks but as a phased rollout, not a big-bang merge.
