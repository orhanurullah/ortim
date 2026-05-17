# Changelog

All notable changes to Ortim are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html)
starting with v0.8.0 (first public release).

## [0.8.0] — 2026-05-17

First public release. Brand consolidation (`ai-factory` → `ortim`), PyPI
publish, and packaging finalization on top of the M3.1 v1 production-ready
foundation. 606 tests, 22 e2e baselines, zero regression.

### Added — public release prep
- **Package rename** — `runtime/` directory renamed to `ortim/`; all import
  paths updated (`from runtime.X` → `from ortim.X`). Required for clean
  `import ortim` namespace on PyPI.
- **Env-var dual-read shim** — `AI_FACTORY_*` → `ORTIM_*` rename with
  backward compatibility. Legacy names and the `.ai-factory.env` config
  file keep working; each fallback emits a one-time stderr deprecation
  warning. `ortim/env.py` exposes `env_get(name, default)` used by all
  call sites. Removal target: one minor release after this.
- **`ai-factory` CLI alias** kept for compatibility, emits a deprecation
  warning when invoked.
- **PyPI metadata** — keywords, classifiers, `text/markdown` description
  content-type, `project.urls` for Homepage/Source/Issues/Documentation/
  Changelog.

### Changed
- Version bumped 0.1.0 → 0.8.0 in both `pyproject.toml` and
  `ortim.__version__`.
- README rewritten as public-facing landing page; internal milestone
  history moved to this changelog.

### Foundation already shipped (M3.1 v1 — 2026-05-15)
The capabilities below are the state-of-the-system at first public
release. They accreted across the pre-public iter/M milestone sequence
(see "Development history" below) but ship together in 0.8.0.

- **State machine + 7 HITL gates** — deterministic `intake → babel →
  intake_dialog → stack_dialog → prd_dialog → ... → done` flow with G1
  (PRD) and G2 (RFC) as mandatory human approvals plus G3-G7 conditional
  gates (schema, external, security, deploy, budget).
- **Babel TR↔EN intent layer** — structured intent extraction with TR
  round-trip validation.
- **Conversational intake (M2)** — split into `IntentAnalyst` /
  `StackAnalyst` / `PRDAnalyst`; `ortim discuss`/`refine`/`lock`/`show`
  per-state dialogue.
- **Locked Stack** — `stack.json` as single source of truth for downstream
  layers, with browser-only intent detection (BaaS-drift fix).
- **Architect Call 1 + Call 2** — deterministic tier selection (T0-T6 web,
  M0-M2 mobile, D0-D1 desktop), RFC §1-§16 (incl. deployment, observability,
  security, test, DR, runbook sketch). Few-shot derivation rules empirically
  validated 5/5 deterministic.
- **Orchestrator** — TaskDAG generation with cycle detection, missing-dep
  validation, Hard Rule 10 (binary acceptance criteria ban-list), Hard
  Rule 13 (`task.module_scope ⊂ rfc_modules`), extend-cycle AC-aggregation
  guidance (10-AC → 3-5 task target).
- **Worker + Reviewer chain** — CodeReviewer (soft veto) + Security/Test
  hard veto + Perf soft veto. Reviewer rubric with per-criterion verdict
  and `unverifiable` two-mode (`criterion_design` vs `test_infrastructure`).
  Length validator + sandbox-feedback retry loop.
- **Skills system (M3)** — `skills/<scope>/<name>.md` frontmatter +
  resolver + per-task injection. 6 seed skills (TypeScript module
  boundaries, SQL mock patterns, React DI, React UI test text matching,
  Docker deploy skills).
- **Cross-task export visibility (M4)** — Worker sees AST-extracted public
  exports from prior DONE tasks; closes the cross-task interface mismatch
  failure class.
- **Iterative extension (M3.1)** — `ortim extend <id> "<brief>"` for
  feature deltas on DONE projects. EXTEND_DIALOG / EXTEND_PRD / EXTEND_RFC
  states with G1/G2 cycle-N gates. Idempotent delta section append.
- **Workspace bootstrap** — per-tier root template writer
  (`package.json`, `tsconfig.json`, `vite.config.ts`, `setupTests.ts`,
  `.gitignore`); `.ortim.env` test-cmd auto-write from tier+app_class;
  `_FRAMEWORK_PACKAGES` map (React+Vite, Vue+Vite, Next, Hono, Express,
  testing-library quartet, jsdom).
- **Brownfield support (M1)** — codebase reader, framework auto-detect,
  AST/regex export extraction; `ortim new --from-existing` / `inspect` /
  `rescan` / `baseline` CLI; Mobile (M0-M2 Flutter) + Desktop (D0-D1
  Tauri) tier docs.
- **Multi-LLM (iter 6a)** — provider-agnostic LLM client; `anthropic`,
  `deepseek`, `ollama`, OpenAI-compatible endpoints. Per-role routing
  (`ARCHITECT_PROVIDER`, etc.). Per-provider budget tracking.
- **Audit + budget** — JSONL hash-chain (tamper-evidence), PII redaction
  (KVKK/GDPR: email/TC kimlik/phone/credit-card/IPv4), thread-safe writes,
  per-provider cost accounting. CLI `ortim budget [--by-provider]` and
  `ortim retro <id>` for per-task breakdown.
- **Hooks (iter 6c)** — `pre_commit` + `pre_deploy` shell hooks via
  `ORTIM_LINT_CMD`, `ORTIM_FORMAT_CHECK_CMD`, `ORTIM_DEPLOY_CMD`.
- **Concurrency** — `mkdir`-atomic file lock, paralel `run-all --parallel`
  via `git worktree` + `ThreadPoolExecutor`, serialized merge.
- **Operational hardening** — LLM transient retry (503/429 exponential
  backoff), provider fail-loud, `unverifiable_reason` two-mode,
  Architect §4 `key_libraries` discipline (subset validator + retry),
  Orchestrator DAG-RFC module match, Reviewer stack-citation discipline,
  `_NPM_DEP_REGISTRY` browser-persistence coverage.

### Deferred (post-0.8.0)
- **M5 RAG (Obsidian) + MCP** — primary value already delivered by
  Architect Call 1 prompt fix; M5 repositioned as platform foundation.
- **M3.1.2 drift detector** — multi-cycle continuity surveillance.
- **G-1**: M4 export visibility vs barrel-import discipline (extend mode);
  surveillance, 2 more occurrences before promotion.
- **G-2**: `test_infrastructure_unavailable` mode coarseness — worker
  test-quality issues sometimes mislabeled as infra failure.

---

## Development history (pre-public)

Detailed iteration log preserved for posterity. Pre-public versions were
internal-only; the milestone sequence below shipped between 2025-Q4 and
2026-Q2 and is consolidated into the 0.8.0 public release above.

### M3.1 v1 (2026-05-15) — iterative extension

- **M3.1.0 foundation** — state machine: 7 new states (DONE → EXTEND_DIALOG
  → EXTEND_PRD_DIALOG/APPROVAL/APPROVED → EXTEND_RFC_DRAFTING/APPROVAL/
  APPROVED → TASKS_GENERATING) + 2 new HITL gates (G1/G2 cycle N);
  `ortim/extend/{schema.py,extender_agent.py,delta_writer.py}`; idempotent
  delta section append (cycle = de-dupe key); BLOCKED-STACK escape hatch.
- **M3.1.1 executor wiring** — `Orchestrator.generate_dag(prior_dag=...)`
  with 3 validators: ID collision, continuity (`> prior_max`), scope-union
  membership (parent §7 ∪ `### Module Breakdown (delta)` H3); extend
  dispatch in `ortim run`; DAG merge persistence + `extensions:
  list[DagDelta]` field.
- **Extend-cycle AC-aggregation discipline (Item 48)** — orchestrator
  prompt enforces aggregation by `(module_scope × behavioral cluster)`;
  empirical: 11 ACs → 4 tasks (vs pre-fix 10 ACs → 10 tasks; ~60%
  reduction).
- **End-to-end proof-point** — `proofpoint48` workspace: planning chain
  clean; execution chain 3/4 tasks auto (T-007 schema first-attempt;
  T-008 sandbox-feedback retry; T-009 valid HITL escalation).

### Operational hardening (2026-05-08 → 2026-05-14)

- **LLM transient retry** — 503/429 exponential backoff.
- **Provider fail-loud** — critical role + global fallback → stderr WARNING.
- **`unverifiable_reason` two-mode** — schema separation between criterion
  design issue and test infrastructure failure.
- **Architect §4 `key_libraries` discipline** — post-draft subset validator
  with retry-with-correction.
- **Bootstrap `_FRAMEWORK_PACKAGES`** — React+Vite / Vue+Vite / Next /
  Hono / Express deps + testing-library quartet + jsdom.
- **Orchestrator DAG-RFC module match** — Hard Rule 13 + RFC §7 parser +
  scope subset validator.
- **Reviewer stack-citation discipline** — `stack.json.key_libraries`
  verbatim quote.
- **Architect Call 1 derivation rules** — single-user → `small/solo/low`;
  few-shot examples; empirically validated 5/5 deterministic.
- **Bootstrap honors `locked_stack.primary_framework`** over heuristic
  tier (T4 + React stack → vite.config writers fire).
- **`_NPM_DEP_REGISTRY` browser-persistence** — `idb`, `dexie`,
  `localforage` + silent-drop stderr WARNING.
- **`_INDEXEDDB_PEERS`** — auto-pull `fake-indexeddb` for jsdom shim.
- **BaaS-drift fix** — `agents/stack_analyst.md` browser-only intent
  detection (Hono/Express/Fastify/Koa forbidden when ≥2 browser-only +
  0 backend signals).
- **UI-text-match skill** — UI ↔ test assertion symmetry.

### M4 (2026-05-13) — cross-task export visibility

Worker prompt receives AST-extracted public exports from prior DONE
tasks; closes the cross-task interface mismatch failure class
(previously T-009-class failures).

### M3 (2026-05-13) — skills system

- `skills/<scope>/<name>.md` frontmatter (`name`, `description`,
  `audience`, `triggers`).
- Resolver: tier > app_class > language > keyword specificity; per-call
  char budget.
- 6 seed skills: typescript-module-boundaries,
  typescript-imports-from-locked-stack, typescript-sql-mock-patterns,
  react-component-patterns, react-dependency-injection,
  react-ui-test-text-matching.

### M2 (2026-05-13) — conversational intake

- Dialog states: `INTAKE_DIALOG` / `STACK_DIALOG` / `PRD_DIALOG`.
- Split analysts: `IntentAnalyst` (intent.md) + `StackAnalyst`
  (LockedStack JSON) + `PRDAnalyst` (PRD.md).
- CLI: `ortim discuss <id>` / `refine <id> "<feedback>"` / `lock <id>` /
  `show <id>`.

### Phase 0 (2026-05-08) — foundation hardening

- Reviewer rubric (per-criterion verdict + `unverifiable` two-mode:
  `criterion_design` vs `test_infrastructure`).
- Orchestrator Hard Rule 10 — binary acceptance criteria ban-list.
- `.ortim.env` test-cmd auto-write from tier+app_class.

### M1.5 (2026-05-08) — bootstrap layer

- `ortim/architecture/bootstrap.py` — per-tier root template (T2/web:
  `package.json` + `tsconfig.json` + `vite.config.ts` + `setupTests.ts`
  + `.gitignore`); idempotent, no overwrite.
- Auto-retry loop (sequential branch) with `prior_reasons` sandbox
  feedback injection.
- Windows UTF-8 console reconfigure (cp1254 crash fix).

### M1 (2026-05-08) — brownfield support

- `ortim/codebase/{reader,frameworks,baseline,schema}.py` — gitignore-
  aware walk, AST/regex export extraction, framework detection.
- Mobile (M0-M2 Flutter) + Desktop (D0-D1 Tauri) tier docs.
- `ortim new --from-existing` + `inspect` / `rescan` / `baseline` CLI.

### iter 6d — RFC template §11-§16 + tier docs

- `docs/templates/RFC.template.md` — new sections: §11 Deployment
  Strategy, §12 Observability Baseline, §13 Security Posture, §14 Test
  Strategy, §15 Disaster Recovery, §16 Runbook Sketch.
- 6 new tier documents (T0-T3, T5, T6) ~80-110 lines each.
- `agents/architect.md` — Call 2 fills §11-§16 with `[NEEDS-INPUT]`
  marker for gaps.

### iter 6c — HITL G3-G7 + hooks

- Project-level gate states: `SCHEMA_AWAITING_APPROVAL` (G3),
  `BUDGET_AWAITING_APPROVAL` (G7), `DEPLOY_AWAITING_APPROVAL` (G6).
- `ortim/orchestrator/gate_detector.py` — `detect_schema_tasks(dag)`,
  `detect_external_calls(worker_output)`, `detect_security_severity(verdict)`,
  `detect_budget_breach(tracker, project_id, cap_usd)`.
- `ortim/hooks/registry.py` — `pre_commit` + `pre_deploy` shell hooks.

### iter 6b — Multi-reviewer (hard veto)

- `SecurityReviewerAgent` (hard veto): injection (SQL/shell/eval),
  hardcoded secrets, authn/authz bypass, insecure crypto, path traversal,
  SSRF, CSRF, sensitive data in logs, known-CVE deps.
- `TestReviewerAgent` (hard veto): AC × test mapping required, test
  runner failure → reject, happy-path-only → reject.
- `PerfReviewerAgent` (soft veto): N+1, missing index, unbounded loop,
  sync I/O, bundle bloat.
- `ReviewerChain` — optional `(security, test, perf)`; hard veto bypasses
  retry budget and sends task straight to `AWAITING_HITL`.

### iter 6a — Multi-LLM provider abstraction

- `ortim/llm/providers.py` — `ProviderConfig` registry: `anthropic`,
  `deepseek` (Anthropic-compatible endpoint).
- `ortim/llm/router.py` — `client_for(role)`: per-role provider/model
  env override.
- `ortim/budget/tracker.py` — per-provider pricing.

### iter 5c — Parallel batch execution + worktree

- `git worktree`-based isolation for batch-parallel tasks.
- `run-all --parallel --max-workers N`: `ThreadPoolExecutor` with
  serialized merge (`merge_lock`) and `task_status.json` save
  (`status_lock`).
- Workspace-level `file_lock(workspace/.exec)` prevents two concurrent
  `run-all` invocations.
- Per-batch metrics audit event (`executor_batch_metrics`: wall_seconds,
  sum_task_seconds, speedup, merge_wait_seconds).

### iter 5a + 5b — Worker, sandbox, git, test runner, batch executor

- `ortim/executor/sandbox.py` — `normalize_relative` (abs/`..`/Win drive
  reject), `check_in_scope` (prefix match, sibling/lookalike reject),
  `check_extension` (source + config + docs + known-basename whitelist).
- `ortim/executor/worker.py` — `WorkerAgent` (LLM + sandbox-validated
  `WorkerOutput`); retry injects prior reviewer reasons.
- `ortim/executor/reviewer.py` — `CodeReviewerAgent` (soft veto).
- `ortim/executor/test_runner.py` — `ORTIM_TEST_CMD` subprocess wrapper.
- `ortim/executor/git_ops.py` — `ensure_repo`, `start_task_branch`,
  `commit_changes`, `merge_task_to_main`, `abandon_task_branch`.
- CLI: `execute <id> <task-id>`, `run-all <id>`.
