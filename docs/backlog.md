# Ortim Backlog — Canonical View

> **Purpose.** Single source of truth for open work. `tespit.md` is the **append-only chronological discovery log**; this file is the **structured projection** for "what is open right now". When in doubt, this file wins for status queries; tespit.md wins for context/rationale.
>
> **Last sync:** 2026-05-15 (post execution-stage proof-point on `proofpoint48` — Item 48 SHIPPED + empirical, Item 49 RETRACTED, M3.1 production-ready for happy-path planning + execution; G-1/G-2 added to DEFERRED watch; pytest 404, no regression)
>
> **Sync protocol.** Every time a new item is added to tespit.md or an existing one changes status, update the row here in the same edit. Drift between tespit.md and this file is the bug; this file is the canonical layer downstream code (M5 design, future agents) can consume.

## Schema

| Field | Meaning |
|---|---|
| **ID** | Matches `tespit.md` numbering. `15a`, `41'` style sub-items kept verbatim. |
| **Status** | `OPEN` (work pending) · `PARTIAL` (some sub-items done, others not) · `SHIPPED` (verified done) · `DEFERRED` (parked, watching for trigger) · `CLOSED` (observation/superseded, no action) |
| **Priority** | `P0` blocker · `P1` high · `P2` medium · `P3` low · `—` non-actionable observation |
| **Pillar** | Vision pillar: 1=Babel, 2-3=Conversational intake/stack/PRD, 4=Method-level/two-shot, 5=RAG, 6=Skills, 7=MCP, 8=Dynamic LLM routing. `?` = unverified mapping (user to confirm). |
| **Last touched** | Date of latest status change in tespit.md |
| **Discovery → Resolution** | One-line trace |

> **New items follow the template at [`docs/item-template.md`](./item-template.md).** The template includes a mandatory "Downstream coverage scan" field designed to catch cascade misses like Items 41 → 41' and BaaS-drift → 47 / 47b before they ship.

---

## OPEN — actionable work

| ID | Title | Priority | Pillar | Last touched | Notes |
|---|---|---|---|---|---|
| **3** | State `advance` UX message (`from == to` case) | P3 | — | 2026-05-08 | Trivial; "Already in X, next: Y" friendlier message. Wait for any UX polish pass. |
| **7b** | `_run_all_loop` parallel branch auto-retry + unit tests | P2 | — | 2026-05-09 | Sequential branch retry works; parallel single-pass. ~4-6h. Needs mock-based integration test. |
| **4b** | Tier × app_class template matrix completion | P3 | 3 | 2026-05-08 | T0/T1/T3 + mobile (pubspec.yaml) + desktop (Cargo.toml). Currently T2/web only. Triggered when first non-T2/web greenfield demo is attempted. |
| **4c** | DAG validator regex (description ↔ scope match) | P3 | — | 2026-05-08 | Observation-only deferral; ship if Orchestrator prompt sertleştirme proves insufficient. Phase 0 + Item 42 may have already neutralized this. |
| **18b** | Bootstrap-time runtime detection (`where.exe node/python/go`) | P3 | 2-3 | 2026-05-09 | M2 conversational stack covers structural case; 18b only if 18a falls short again. Not observed. |
| **18c** | `ortim new --prefer-stack` CLI flag | P3 | 2-3 | 2026-05-09 | Power-user affordance / M2 prefiguration. Defer unless explicit user demand. |
| **39b'** | `cargo test -p` + `go test ./<pkg>/...` scope adapters | P3 | — | 2026-05-14 | Per-runner scope syntax. vitest/pytest/flutter shipped. Defer until first Rust/Go E2E. |
| **39c** | PRDAnalyst skill-aware (resolve_for_project entry point) | P3 | 6 | 2026-05-14 | Demoted: Worker proven to handle additive PRD↔skill constraints across 3 runs. Ship only if exclusive conflict observed. |

**Strategic open questions** (carried forward; non-implementation):

- **SQ-1** PyPI publish timing — `name="ortim"` reserved? Trigger condition?
- **SQ-2** Enterprise tier real revenue timeline — M5 ships iskelet; what's the gap to actual sale?
- **SQ-3** ortim.dev landing page — when?
- **SQ-4** First hedef segment — agency / fintech / sağlık? Defer until proof-point demo reveals who says "vay be".
- **SQ-5** TUI library choice for M2 dialog — currently `prompt_toolkit` via typer; revisit if M2 UX feedback demands `textual`.

---

## SHIPPED — verified done

| ID | Title | Shipped | Pillar | One-line summary |
|---|---|---|---|---|
| **1** | LLM transient retry (503/429) | 2026-05-10 (item 22) | 8 | Exponential backoff, 3 retries, jitter in `llm/client.py`. |
| **4** | Root scaffolding + shared resource layer | 2026-05-08 (M1.5) | 3 | `runtime/architecture/bootstrap.py`; T2/web template; Orchestrator Hard Rules 11+12. Sub-items 4b/4c deferred. |
| **5** | Provider routing fail-loud on critical roles | 2026-05-10 (item 23) | 8 | stderr WARNING on global fallback for Architect/Security; M4 dynamic routing remains the structural answer. |
| **6** | Test/hook silent-skip + approve loophole | 2026-05-08 (Phase 0 9c) | — | Test-cmd auto-detect from tier+app_class; rubric `unverifiable` escalates when tests skip. |
| **7** | Worker→Reviewer auto-retry loop (sequential) | 2026-05-08 (M1.5) | 5 | `execute_task` reject branch feeds prior_reasons; loops until MAX_RETRIES. Parallel branch = 7b open. |
| **8** | Windows console Unicode `cp1254` crash | 2026-05-08 (M1.5) | — | `sys.stdout.reconfigure(encoding="utf-8", errors="replace")` at module load. |
| **9** | Phase 0 Foundation Hardening (rubric + binary criteria + test-cmd) | 2026-05-08 | 4-5 | Reviewer rubric per-criterion verdict; `unverifiable` → AWAITING_HITL; ban-list; bootstrap `.ai-factory.env`. |
| **10** | M2 — Conversational Intake & Stack Iteration | 2026-05-13 (item 27) | 2-3 | `INTAKE_DIALOG`/`STACK_DIALOG`/`PRD_DIALOG` states; `ortim discuss`; LockedStack as single source. |
| **11** | M3 — Skills System | 2026-05-13 (item 31) | 6 | `skills/<scope>/<name>.md` frontmatter; resolver; per-task injection; 5 seed skills. |
| **12** | M4 — Two-Shot Worker + Cross-task export visibility | 2026-05-13 (item 34) | 4 | (Two-shot was pragmatic-scoped; export-shape catalog was actually shipped — see Item 34 in tespit.md for nuance.) |
| **15** | Sandbox-violation feedback in `prior_reasons` | 2026-05-08 (15a) | 5 | `[sandbox]`-tagged feedback; Worker next attempt sees concrete reason. |
| **15a** | Same as 15 | — | — | (alias) |
| **15b** | Per-language Worker import skill | 2026-05-13 (M3) | 6 | Subsumed by M3 skills. |
| **16** | `unverifiable` two-mode disambiguation | 2026-05-13 (item 38) | — | `criterion_design` vs `test_infrastructure_unavailable` schema separation. |
| **17** | Architect Call 2 honors `select_tier()` | 2026-05-09 (partial), M2 (structural) | 3 | `_LANG_STACK_BY_TIER_APP` constraint injected; M2 StackAnalyst locked the contract. |
| **18a** | Stack-aware test-cmd RFC fallback | 2026-05-09 | 3 | `_LANG_TEST_CMD` token scan in `bootstrap.py` when matrix has no entry. |
| **19** | `_run_all_loop` NameError (`codebase_summary`/`app_class`) | 2026-05-09 | — | Latent bug; parallel branch never exercised before. |
| **21** | Reviewer length validator | 2026-05-09 | 4 | Orchestrator-style retry loop on `len(criteria_verdicts) != len(task.acceptance_criteria)`. |
| **22** | LLM transient retry (P0 hardening) | 2026-05-10 | 8 | Item 1 implementation. |
| **23** | Provider fail-loud on critical roles (P1) | 2026-05-10 | 8 | Item 5 implementation. |
| **24** | Unverifiable two-mode schema (P1) | 2026-05-10 | — | Item 16 schema-level fix. |
| **26** | Post-run code quality compile-clean | 2026-05-13 | 4 | Closed by items 27 (M2 LockedStack) + 30 (stack-aware package.json/tsconfig) + 34 (cross-task export visibility) + 36 (@types peers). web-todo-m2 compiled 0 tsc errors. |
| **27** | M2 Conversational Intake | 2026-05-13 | 2-3 | (same as 10) |
| **29** | `test_runner.py` Windows shim resolution | 2026-05-13 | — | `.cmd`/`.ps1` fallback path resolution for npm-scoped runners. |
| **30** | Stack-aware `package.json` + `tsconfig.json` | 2026-05-13 | 3 | Closed 2/4 of item 26 directly. |
| **31** | M3 Skills system foundation | 2026-05-13 | 6 | (same as 11) |
| **33** | Cross-task export-shape visibility | 2026-05-13 (M4 item 34) | 4 | Subsumed by M4 export catalog. |
| **34** | M4 cross-task export catalog | 2026-05-13 | 4 | Worker sees prior-task exported symbols; Reviewer enforces import correctness. |
| **36** | `_NPM_TYPES_PEERS` auto-injects `@types/*` | 2026-05-13 | 3 | Runtime packages without bundled `.d.ts` get peer `@types/*` added by bootstrap. |
| **37** | Reviewer barrel-import false-positive | 2026-05-13 (item 38) | — | Reviewer prompt sertleştirme with explicit barrel pattern examples. |
| **38** | Reviewer sertleştirme (items 16 + 37) | 2026-05-13 | — | Prompt-only fix; no schema change. Closed both 16 and 37. |
| **39a** | SQL-mock skill | 2026-05-14 | 6 | `skills/typescript/sql-mock-patterns.md`; resolver test pinning. |
| **39b** | Per-task test scoping (vitest/pytest/flutter) | 2026-05-14 | — | `test_runner.py::_apply_scope`; `runner.py` passes `primary_scope(task)`. pytest exit-5 normalized. Sub-39b' deferred for cargo/go. |
| **40** | Architect §4 key_libraries discipline | 2026-05-14 | 4 | Subset validator + 3-attempt retry-with-correction; mirrors item 21 pattern. |
| **41** | Bootstrap `_FRAMEWORK_PACKAGES` map | 2026-05-14 | 3 | React+Vite / Vue+Vite / Next.js / Hono / Express → dep packages. Closed "Cannot find package 'react'" class. |
| **41'** | React testing-library + vite.config + setupTests writers | 2026-05-14 | 3 | `_REACT_VITE_PACKAGES`, `_VITE_CONFIG_REACT`, `_SETUP_TESTS_REACT`. jsdom + testing-library quartet. |
| **42** | Orchestrator DAG-RFC module match validator | 2026-05-14 | 4 | RFC §7 parser + scope subset check; Hard Rule 13. Closed "synthetic shared" L1 leak class. |
| **44** | `skills/react/dependency-injection.md` | 2026-05-14 | 6 | Pattern A (props), Pattern B (Context), 3 anti-patterns. Triggers on `app component`/`wire`/`integrate` keywords. |
| **46** | Bootstrap honors `locked_stack.primary_framework` over heuristic tier | 2026-05-14 | 3 | `_is_browser_framework_stack` gate; T4 + React stack now writes vite.config etc. Locked-stack contract beats tier heuristic. |
| **README-stale** | README.md refreshed to current state | 2026-05-14 | — | v0.7 status table with M1/M1.5/Phase 0/M2/M3/M4/Items 22–47b/45 grouped sections; "Yol Haritası" expanded with TAMAMLANDI markers; "Sonraki Adım" reframed around 3 candidates (M3.1 extend / PyPI publish / Enterprise scoping). |
| **M3.1.0** | `ortim extend` foundation (state machine + schema + ExtenderAgent + delta writer + CLI) | 2026-05-14 | 4 | New `runtime/extend/` package: 7 new state machine states (DONE → EXTEND_DIALOG → ... → EXTEND_RFC_APPROVED → TASKS_GENERATING) + 2 HITL gates (G1/G2 cycle N), `ExtensionIntent` + `DagDelta` Pydantic schemas, `TaskDAG.extensions: list[dict]` + `TaskDAG.max_task_id()` helper, `ExtenderAgent.draft_delta_prd/draft_delta_rfc` with BLOCKED-STACK escape hatch + 12K char truncation budget, `agents/extender.md` system prompt, idempotent `delta_writer.append_delta_section` (cycle is the de-dupe key), `ortim extend <id> "<brief>"` + `ortim extensions <id>` CLI. **+45 tests** (state machine +6, schema +12, ExtenderAgent +9, delta_writer +12, CLI helpers +5). |
| **M3.1.1** | `ortim extend` executor wiring (Orchestrator extend validators + `run` handler + DAG merge persistence) | 2026-05-14 | 4 | Extended `OrchestratorAgent.generate_dag(prior_dag=...)` with new validators: ID collision detection (`_find_id_collisions`), continuity check (`_find_below_min_ids`, IDs ≥ prior max+1), scope membership union (parent §7 ∪ delta `### Module Breakdown (delta)` H3 blocks via new `_parse_rfc_extension_modules`). Custom `_validate_extend_dag` allows new tasks to depend on prior DONE task IDs (would otherwise fail `MissingDependency`). `ortim run` gained two dispatch blocks: EXTEND_PRD_APPROVED → EXTEND_RFC_AWAITING_APPROVAL (`_draft_extend_rfc` helper) and EXTEND_RFC_APPROVED → TASKS_READY (`_generate_extend_dag` merges new tasks into existing task_dag.json + writes `DagDelta` to `extensions` + per-task markdown files). `run-all` already skips DONE tasks (line 2548-2559) so no executor changes needed. **+17 tests** (orchestrator validators +13, run helpers +3, merge persistence +2). M3.1 v1 fully shipped; remaining is M3.1.2 (drift detection — defer until reported) and a real-LLM E2E proof-point. |
| **48** | Orchestrator extend-cycle AC-aggregation guidance | 2026-05-15 | 4 | `agents/orchestrator.md` `## Extend Cycle Task Granularity` section: (module_scope × behavioral cluster) aggregation rule, 10-AC delta → 3-5 tasks quantitative anchor, bundle example, cross-module counter-example, trace-back rule (every task → delta RFC §Module Breakdown row OR delta AC). `runtime/agents/orchestrator.py` extend-cycle user-prompt block references the section by name + repeats quantitative anchor. **Empirical validation**: same TR tagging brief, fresh v3 clone (`proofpoint48`) — 11 ACs → 4 tasks (vs pre-fix 1b9c9f9ca18b: 10 ACs → 10 tasks). ~60% reduction; deps clean; scope correct. **+2 tests** (pytest 402 → 404). |
| **43** | Reviewer stack-citation discipline | 2026-05-14 | 4 | `agents/reviewer.md` Hard Rule 8 — quote `stack.json.key_libraries` verbatim by field name; "the locked stack lists ..." paraphrase forbidden because it merges stack.json with RFC §4 drift. +1 test. |
| **BaaS-drift** | StackAnalyst browser-only intent detection | 2026-05-14 | 2-3 | `agents/stack_analyst.md` — new "Browser-only intent detection" section + Hard Boundary; sql.js/IndexedDB/"yerel veritabani"/"tek kullanıcı" signals; Hono/Express/Fastify/Koa explicitly forbidden when ≥2 browser-only signals AND 0 backend signals. +1 test. |
| **UI-text-match** | `skills/react/ui-test-text-matching.md` | 2026-05-14 | 6 | New skill: UI text ↔ test assertion symmetry; bare-string default + partial-match opt-in when criterion names decoration. Triggers on `warning/banner/notification/alert/message/label/status text/empty state/error message/success message` keywords. +1 resolver test. **v4 status:** not exercised (T-004 not reached). |
| **47** | `_NPM_DEP_REGISTRY` browser-persistence coverage + silent-drop visibility | 2026-05-14 | 3 | Added `idb`, `dexie`, `localforage` to registry; unknown `key_library` now emits stderr WARNING (was silent `continue`). Discovered mid-v4 when BaaS-drift fix widened StackAnalyst's range to include `idb`. +3 tests. |
| **47b** | `fake-indexeddb` auto-pull for browser persistence test peer | 2026-05-14 | 3 | When `idb`/`dexie`/`localforage` in key_libraries, bootstrap auto-adds `fake-indexeddb` devDep (mirrors `react` → `@vitejs/plugin-react` auto-pull). Discovered mid-v4 T-002 (jsdom doesn't provide IndexedDB). +3 tests. |
| **45** | Architect `extract_inputs` (Call 1) non-determinism | 2026-05-14 | 2 | Symptom was mis-labeled as IntentAnalyst — actual culprit was Architect Call 1's prompt: Rule 2 ("use unknown when not sure") collided with implicit signals (single-user → obviously small/solo/low). Fix: derivation rules section (a/b/c/d) + 3 few-shot examples in `agents/architect.md`. **Empirically validated:** 5/5 consecutive `extract_inputs` calls on the v4 PRD produce identical canonical `small/solo/low` (vs pre-fix v3's outlier `unknown/unknown/unknown`). +2 tests. M5 RAG no longer needed for this case — significant scope re-evaluation. |

---

## DEFERRED — parked, awaiting trigger

| ID | Title | Trigger to revisit | Pillar |
|---|---|---|---|
| **2** | Tier scoring weights re-balance (CLI/single-user negative signals) | M2 StackAnalyst surfaces remaining gap; partially mitigated by 17+18a | 3 |
| **18** | Stack constraint matrix env-blind (root issue) | M2 conversational stack is the structural answer | 2-3 |
| **39c** | PRD ↔ skill consistency | Only if exclusive PRD↔skill conflict observed (never in 3 runs) | 6 |
| **G-1** | M4 export visibility vs barrel-import discipline mismatch in extend mode | Same class observed in 2 more extend-cycle runs (T-009 on `proofpoint48` was first instance: Worker copied raw `../tagging/tagging` path instead of barrel import despite typescript-module-boundaries skill being in scope) | 4, 6 |
| **G-2** | `test_infrastructure_unavailable` mode coarseness — `worker_test_quality_failure` sub-mode missing | Two more cases where Worker test misuse (e.g. `expect(...).rejects` Promise-wrap error) gets labelled as infrastructure failure rather than worker quality issue; observed once on T-009 `task/repository.test.ts` | — |

---

## CLOSED — observations, no action

| ID | Title | What it was | Pillar |
|---|---|---|---|
| **13** | M5 Knowledge Layer (RAG + MCP) — roadmap entry | Now active design phase (this work) | 5, 7 |
| **20** | "4/5 first-attempt self-driving" observation | Proof point, not work item | — |
| **25** | E2E Validation Run `e2e-validation-1` | Run report, not work item | — |
| **28** | E2E web-todo-m2 validation report | Run report | — |
| **32** | E2E web-todo-m2 T-004 fixed by M3 | Regression confirmation | — |
| **35** | E2E re-run on web-todo-m2 — 0 tsc errors | Confirmation that 26 is closed | — |
| **39** | First autonomous E2E summary | Run report; sub-items 39a/b/c split out | — |

---

## Counts (sanity check)

- **OPEN actionable:** 8 (0× P1, 0× P2, 8× P3) — Item 48 shipped 2026-05-15 same day (Item 49 retracted post-forensic)
- **SHIPPED:** 37+ (Items 43, BaaS-drift, UI-text-match, 47, 47b, 45, README-stale, M3.1.0, M3.1.1 added 2026-05-14)
- **DEFERRED:** 3
- **CLOSED non-actionable:** 7
- **Strategic open questions:** 5

**Total surface area covered:** items 1–49 from tespit.md (49 retracted; 48 SHIPPED; latest valid) + sub-items + 2 sentinel watch-list rows (G-1, G-2) + 5 SQ's.

---

## Maintenance log

| Date | Author | Change |
|---|---|---|
| 2026-05-14 | initial extract | First canonical projection from tespit.md 1-2441 |
| 2026-05-14 | option-A session | Item 43 + BaaS-drift + UI-text-match shipped (prompt/skill fixes). pytest 328 → 331 (+3). OPEN actionable 13 → 10. SHIPPED +3. |
| 2026-05-14 | option-E (proof-point v4) | Items 47 + 47b shipped mid-run (registry coverage + fake-indexeddb auto-pull). BaaS-drift validated live (autonomous React+Vite pick on first call). Item 43 partial validation (Reviewer suggestion used `key_libraries` field name). UI-text-match not exercised (T-004 not reached — user interrupt after primary signal landed). pytest 331 → 337 (+6). |
| 2026-05-14 | option-C (Item 45 standalone) | Item 45 closed via prompt-only fix to `agents/architect.md` Call 1 (derivation rules + few-shot). Empirically validated: 5/5 deterministic on v4 PRD. M5 RAG's primary autonomy-jump value claim invalidated — M5 reframed as "foundation for future capabilities" (drift detector, skill mining), not "stabilizer for Item 45". pytest 337 → 339 (+2). |
| 2026-05-14 | option-D + template upgrade | README.md refreshed to v0.7 state (status table + Yol Haritası + Sonraki Adım all updated to reflect M1/M1.5/Phase 0/M2/M3/M4 + Items 22–47b/45 shipped). `docs/item-template.md` created with mandatory "Downstream coverage scan" field — the lesson from Items 41 → 41' and BaaS-drift → 47/47b cascade misses. Backlog OPEN actionable 9 → 8. |
| 2026-05-14 | M3.1.0 (extend foundation) | New `runtime/extend/` package + state machine extension + CLI commands. M3.1.0 SHIPPED across 4 sub-tasks (state/schema/agent/CLI). pytest 339 → 384 (+45). M3.1.1 (DAG validation + executor integration) remaining. |
| 2026-05-14 | M3.1.1 (extend executor) | Orchestrator extend-cycle validators (ID collision/continuity/scope-union) + `ortim run` dispatch for EXTEND_PRD_APPROVED + EXTEND_RFC_APPROVED + DAG merge persistence. pytest 384 → 402 (+18). M3.1 v1 done; M3.1.2 drift detection deferred until reported. |
| 2026-05-15 | M3.1 v1 proof-point | Cloned v3 baseline → fresh workspace `1b9c9f9ca18b`; ran `ortim extend` cycle 1 with TR tagging brief; primary signal landed (saw-tooth module-drift correction by Architect, M4 cross-task export visibility, scope/continuity/ID-collision validators passed; `extensions.new_tasks=[T-007..T-016]`). Item 48 OPEN (10-AC → 10 tasks over-granularization, design target ≤3). Item 49 (off-delta contamination) initially logged then RETRACTED post-forensic: T-006 was a pre-existing baseline orphan, not extend-emitted; forensic-before-claim discipline caught the mis-attribution at wrap. Pytest 402 unchanged; spend ~$0.06. |
| 2026-05-15 | Item 48 ship + re-proof-point | `agents/orchestrator.md` `## Extend Cycle Task Granularity` section + runtime context guidance shipped; 2 unit tests pin the discipline (pytest 402 → 404). Re-proof-point on fresh v3 clone `proofpoint48`: 11 ACs → 4 tasks (vs pre-fix 10 ACs → 10 tasks); ~60% reduction; scope/deps/relevance clean. |
| 2026-05-15 | Execution-stage proof-point on `proofpoint48` | `ortim run-all` ran 4 delta tasks: T-007 schema DONE attempt 1, T-008 tagging CRUD DONE attempt 2 (Item 15a sandbox feedback fired), T-009 task ext AWAITING_HITL with valid reviewer findings (L1 boundary violation + INNER vs LEFT JOIN + 2× `test_infrastructure_unavailable`), T-010 not started. Real cost $0.0345 / 12 LLM calls. T-009 HITL is correct system behavior, not a bug. **G-1** (M4 export visibility vs barrel-import discipline) + **G-2** (`test_infrastructure_unavailable` mode coarseness vs worker test quality) added to DEFERRED — surveillance, fire on 2 more occurrences. M3.1 v1 now production-ready end-to-end. **Day total spend: ~$0.16.** |
