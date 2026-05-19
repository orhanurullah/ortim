# Changelog

All notable changes to Ortim are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html)
starting with v0.8.0 (first public release).

## [0.9.4] — 2026-05-19

**PyPI install bug-fix + user-level config store.** Reported by a PyPI user
who could not get `LLM_PROVIDER=deepseek` in `.env` to take effect; the
fix has two halves — the dotenv discovery bug, and a persistent
provider/key config so the next install never hits the same wall.

### Fixed
- `load_dotenv()` was called argument-less in `ortim/main.py`, which made
  `python-dotenv` walk up from the caller frame's file location instead
  of the user's `cwd`. On dev installs the file lives inside the repo,
  so walking up from it eventually found the repo's `.env` and the bug
  was invisible. On PyPI installs `main.py` lives in `site-packages`,
  and walking up from there never reaches a user project directory —
  so a `.env` placed in the project (e.g. `C:/projects/deneme/.env`)
  was silently ignored, and the runtime always asked for
  `ANTHROPIC_API_KEY` no matter what `LLM_PROVIDER` the operator set.
  Now `load_dotenv(find_dotenv(usecwd=True))` walks from `os.getcwd()`,
  matching operator intent. Two regression tests
  (`test_find_dotenv_usecwd_walks_from_user_cwd`,
  `test_find_dotenv_usecwd_returns_empty_when_absent`) pin the fix.

### Added
- **`ortim config` command group** with persistent user config at
  `~/.ortim/config.toml` (overridable via `ORTIM_CONFIG` env). Removes
  the need to keep a `.env` in every project directory — configure once,
  use everywhere. POSIX writes are chmod 0600 so an `api_key` stays
  per-user.
  - `ortim config init` — interactive wizard (provider → model → key);
    safe to re-run, preserves unrelated fields.
  - `ortim config show` — tabular view with `Source` column (`config` /
    `env` / `default`) so you can tell where each value came from.
  - `ortim config path` — print resolved config path.
  - `ortim config set-provider <name>`, `set-model <id>`,
    `set-key <provider>` (prompts hidden), `set-role <role>` —
    non-interactive setters for scripts.
- **`--provider` / `--model` flags on `run` and `demo`** — highest-
  precedence per-invocation override. `ortim demo --provider ollama` is
  the path PyPI users with no API key can take to verify the install.
- **Resolution precedence** (documented + tested): CLI flag → shell /
  `.env` env var → `~/.ortim/config.toml` → hardcoded default. Config
  values only populate env vars that are currently unset — operators
  exporting `LLM_PROVIDER=ollama` in a shell always win.
- **`ortim doctor` — new "Active LLM provider" check.** Reports the
  resolved provider, its source, and whether the matching credential is
  present. Replaces the guesswork when `ANTHROPIC_API_KEY: MISS` was
  surfacing as noise even though the operator had deliberately chosen
  DeepSeek or Ollama.

### Changed
- `LLMClient` missing-key error now names the resolved provider and
  lists three fix paths (`ortim config init`, env var export, or
  `--provider ollama` for a key-free local runtime). Surfaces the
  intent gap directly instead of just naming the env var.
- `ortim demo` key pre-flight consults the resolved provider, not a
  hardcoded "anthropic or deepseek" check — so `--provider ollama`
  proceeds past the pre-flight as intended. The original `test_demo_aborts_when_no_llm_key_present`
  is updated to pin against the new error text plus a new
  `test_demo_passes_when_provider_needs_no_key` covers the ollama path.

### Tests
- 14 new tests across `tests/test_config_store.py` (11 — roundtrip,
  precedence, `env_source` labels, malformed-TOML tolerance, quote
  escaping, path-override) and `tests/test_dotenv_cwd.py` (2 —
  the regression itself) plus the demo `--provider ollama` coverage.
  Full suite **746 → 760 (+14, zero existing-test regressions).**

## [0.9.3] — 2026-05-18

**Bug-fix and hardening pass** following a comprehensive manual test of v0.9.2.
Each of five surveillance findings was reproduced first, then patched with a
regression test. Verified on real workspaces (`079fb8862112`, `proofpoint48`,
fresh init `ffe8d7eb0c2b`). Full test count 740 → 746 (+6 regression tests,
zero existing-test regressions).

### Fixed
- `ortim budget` reported `$0.0000` for workspaces that had real audit data,
  while `ortim retro` showed the correct cost from the same audit log. Root
  cause: `budget` resolved the workspace ID via `discover_from_cwd` but
  skipped `_resolve_project`, so `AUDIT_LOG_PATH` was never bound to the
  per-workspace audit log; `BudgetTracker` then fell back to the default
  global path and filter-by-project_id returned zero rows. `budget` now
  routes through `_resolve_project` for the explicit-arg case and binds
  the audit path explicitly in the cwd-discovery case, matching `retro`'s
  contract. Three regression tests in `tests/test_cli_cwd_aware.py` lock
  the fix (`test_budget_no_arg_discovers_cwd_and_binds_audit_path`,
  `test_budget_explicit_id_binds_audit_path`,
  `test_budget_matches_retro_for_same_workspace`).
- `ortim retro` and `ortim budget` returned empty reports for legacy pool
  workspaces (created before the v0.9.0 project-mode pivot). Pre-pivot
  runs wrote audit events to the global default log
  (`./ortim/audit/decisions.jsonl`), but the resolver pointed both
  commands at `<workspace>/audit.jsonl` (which was never written). Both
  commands now consult a second source — the global default audit log —
  as a fallback for project-scoped queries, with `(timestamp, event,
  task_id)` deduplication for rows that legitimately appear in both. The
  fallback is only active when the caller asked for a specific
  `project_id`; whole-log queries (`BudgetTracker.report()` with no
  argument) still read the configured path alone, so global rollups
  don't silently mix in extra audit sources. Two new regression tests
  (`test_budget_pool_workspace_falls_back_to_global_audit`,
  `test_budget_whole_log_query_does_not_silently_mix_global`) lock both
  rules. Verified on real pool workspaces `079fb8862112` (23 calls,
  $0.0350) and `proofpoint48` (12 calls, $0.0346).
- `ortim status` (and any other cwd-aware command) no longer hits a
  confusing `Workspace state not found at <path>` error when the
  registry `current` pointer references a workspace whose `.ortim/`
  was deleted out from under it (temp-dir reaper, manual `rm`, drive
  change). `_resolve_current_pointer` now verifies `state_file` exists
  before returning the location; on a stale pointer it falls through to
  the standard `No project here. Run ortim init …` message. The
  resolver stays read-only — the stale registry entry is left in place
  so `ortim workspace doctor` still surfaces it as `path_missing`,
  giving the user an explicit chance to migrate or remove the row.
  Two new regression tests
  (`test_resolve_workspace_skips_stale_current_pointer`,
  `test_resolve_workspace_falls_through_to_friendly_error_when_current_stale`)
  lock the silent-skip behavior.
- Worker writes with whitespace in any path segment (e.g.
  `API Client Module/lib/supabase.ts`) are now rejected by the sandbox.
  The bug surfaced when an Architect labelled an RFC §7 module
  `"API Client Module"` and the Orchestrator copied that verbatim into
  `task.module_scope` per Hard Rule 13; the Worker then created an
  unquotable path that breaks shell tooling on Windows/CI. Three
  layers of defense: (a) `ortim.executor.sandbox.normalize_relative`
  raises `SandboxViolation` on any whitespace inside a segment;
  (b) `ortim.agents.orchestrator._parse_rfc_modules` and
  `_find_unscoped_tasks` normalize both sides of the RFC ↔ DAG
  comparison through a new `_normalize_module_name` helper
  (lowercase, whitespace → `-`, drop chars outside `[a-z0-9_/-]`),
  so kebab-case task scopes still match a Title Case RFC label
  without losing the Item 42 subset check; (c) `agents/orchestrator.md`
  Hard Rule 13 spells out the filesystem-safe form requirement and
  gives examples. New regression tests:
  `test_normalize_rejects_whitespace_in_segment` (sandbox),
  `test_parse_rfc_modules_normalizes_whitespace_to_kebab` and
  `test_find_unscoped_tasks_normalizes_task_side_too` (orchestrator).
- Reviewer no longer defaults to
  `unverifiable_reason: "test_infrastructure"` when the code itself has
  compile-time problems a human reviewer would catch in five seconds.
  Pre-fix symptom (phase-C smoke, workspace `5f729939b39d` T-001): the
  Worker emitted `import { createClient } from '@supabase/supabase-js'`
  AND `export function createClient()` in the same file — a TypeScript
  redeclaration that wouldn't build. Because the test runner was
  unconfigured, the Reviewer marked the runtime criterion
  `unverifiable: test_infrastructure` and sent the operator chasing a
  test-runner fix, while the real defect was a one-line code edit.
  `agents/reviewer.md` now has a `Static sanity checks` section that
  enumerates the obvious-broken patterns to flag (symbol
  redeclaration, duplicate top-level declarations, self-referential
  imports, unresolved imports, syntactic breaks) and makes the
  decision order explicit: `fail` with code_quote BEFORE `unverifiable:
  test_infrastructure`. Prompt content pinned by
  `test_reviewer_prompt_teaches_static_sanity_checks_before_unverifiable`.

## [0.9.2] — 2026-05-18

**Documentation pivot to English-canonical.** The PyPI page now leads with
the English README; a new `docs/why-ortim.md` articulates the value
proposition; tutorial and runbook are rewritten in English with
international examples. Turkish versions are preserved as historical
references under `docs/tr/`.

### Added
- `docs/why-ortim.md` — explains the structural pain points Ortim solves
  (forgotten context, error loops, silent test skips, architecture drift,
  hallucinated libraries, approval fatigue, missing audit), the design
  choices that solve each (state machine, deterministic tier scorer, DAG
  validators, module-scoped sandboxes, rubric-shaped reviewer chain, audit
  hash chain, multi-provider routing), a concrete cost/quality comparison
  vs vanilla LLM coding, and a positioning table vs Cursor / Aider /
  Claude Code / Continue.dev. Also lists non-goals and target users.
- `docs/tr/` directory: Turkish archives of `README.md`,
  `tutorial/getting-started.md`, `runbook/failure-recovery.md`, each with
  a header pointing at the English canonical version.

### Changed
- `README.md` rewritten in English. New value-led intro hooks into
  `docs/why-ortim.md`; quick-start uses the project-mode `cd <dir> &&
  ortim init` cadence; pain-point/answer table is foregrounded.
- `docs/tutorial/getting-started.md` rewritten in English. Example briefs
  are now internationally legible (task tracker, expense tracker) instead
  of Turkish-specific. The structure, gate explanations, and trust
  calibration section remain — the rewrite tightens phrasing rather than
  changing the flow.
- `docs/runbook/failure-recovery.md` rewritten in English. §0 project-mode
  quick reference retained; every recipe phrased in English; pointers to
  `.ortim/audit.jsonl` and `.ortim/task_status.json` for forensic work
  carried over from 0.9.1.

### Deferred
- `Ortim_Architecture.md` remains mixed Turkish/English. A full English
  pass is scoped for Phase 4 (likely paired with the M5 RAG work).

## [0.9.1] — 2026-05-18

**Patch release.** Fixes the `ortim demo` subprocess chain (it was broken by
the 0.9.0 pivot of `advance` / `execute` from two-positional-arg to
`<arg> --project <id>`), and refreshes the user-facing tutorial + failure
recovery runbook for the project-mode flow.

### Fixed
- `ortim demo` — the subprocess chain spawned `advance` and `execute` with a
  two-positional-arg layout (`advance <project_id> <state> ...`) that
  v0.9.0's signature no longer accepts. Typer rejected the extra argument
  and the demo failed at G1 auto-approve. Chain now uses the
  `<state> --project <id>` form. New `test_demo_chain_uses_project_flag_for_advance_and_execute`
  pins the signature contract so a future positional-vs-flag change in
  either command surfaces as a test failure before shipping.

### Changed
- `docs/tutorial/getting-started.md` rewritten end-to-end for project mode:
  §1.3 workspace pattern (`.ortim/` namespace + discovery rules), §4
  walkthrough now starts with `cd <dir> && ortim init` instead of
  `ortim new "<name>" --brief ...`, §6.7 disk cleanup uses
  `ortim workspace cleanup`, §7 covers `ortim ls` / `ortim use` / `ortim
  workspace` namespace, cheatsheet shows the cwd-first cadence.
- `docs/runbook/failure-recovery.md` — new §0 quick reference table for the
  project-mode command surface; every recipe updated to drop the
  `<workspace-id>` positional. Also removes references to options that
  never existed (`--task`, `--artifact worker-output`, `--artifact review`)
  and points readers at `.ortim/audit.jsonl` and `.ortim/task_status.json`
  instead.

## [0.9.0] — 2026-05-17

**Project Mode pivot.** Workspace identity moves from pool layout
(`<repo>/workspaces/<uuid>/`) to cwd-aware project mode
(`<user-dir>/.ortim/`). CLI matches the standard git / cargo / terraform /
Claude Code pattern: `cd <dir> && ortim init` creates a workspace there,
subsequent commands discover it implicitly. This is a **minor breaking
change** — pool layout still works for v0.9 but is deprecated and slated
for removal in v1.0.

### Added
- `ortim init "<brief>"` — primary workspace-creation command. Auto-detects
  brownfield (manifest sniff: `package.json`, `pyproject.toml`,
  `Cargo.toml`, `go.mod`, `pubspec.yaml`, `Gemfile`, `setup.py`, etc.) vs
  greenfield from cwd contents. `--brownfield` / `--greenfield` overrides.
- `ortim/workspace/` package: `resolver.py` (cwd + parent walk + registry
  fallback), `store.py` (mode-agnostic Project I/O), `init.py` (project
  bootstrap), `registry.py` (`~/.ortim/registry.json` index), `lifecycle.py`
  (archive / cleanup / doctor / migrate).
- `ortim ls` (and `ortim workspace list`) — registry-backed global listing
  with `*` marker for the active workspace, `--prune` for stale entries,
  `--include-archived` / `--no-pool` filters.
- `ortim use <id|name>` — set active workspace pointer
  (`~/.ortim/registry.json::current`). Read by resolver when cwd has no
  `.ortim/` anchor.
- `ortim workspace` subcommand namespace: `list`, `show`, `use`, `archive`,
  `unarchive`, `cleanup --older-than <N> [--yes]`, `doctor`, `migrate <id>
  --to <path>`.
- `Project.archived_at` + `Project.kind` fields (`active` / `demo` /
  `scratch` / `proof_point` / `baseline` / `legacy`).
- `Project.current_metadata_dir(root)` + `bind_metadata_dir()` — instance
  method + PrivateAttr that route `project.save(WORKSPACE_ROOT)` to the
  resolved layout automatically.
- Per-project audit log at `<workspace>/.ortim/audit.jsonl` (resolver sets
  `AUDIT_LOG_PATH` env var; in-process `AuditLogger()` constructions land
  in the right place without explicit threading).
- 128 new tests: resolver (18), store (16), init (26), CLI cwd-aware (26),
  registry (20), lifecycle (22).

### Changed
- All read commands (`status`, `show`, `inspect`, `gates`, `tasks`,
  `extensions`, `scope --show`) accept an optional `project_id` argument;
  if omitted, the workspace is discovered from cwd.
- Mutating commands (`advance`, `run`, `run-all`, `execute`, `extend`,
  `refine`, `lock`, `scope`, `drift-check`, `retro`, `budget`, `rescan`,
  `baseline`) follow the same cwd-first pattern. Two-positional-arg
  commands (`advance`, `execute`, `extend`) moved `project_id` from
  positional to `--project / -p` flag to keep the common-case usage
  (`ortim advance prd_approved`) clean.
- Archived workspaces refuse mutating commands with a friendly hint
  pointing at `ortim workspace unarchive`. Read commands work normally.
- `list-projects` deprecated → `ortim ls` (alias keeps working with
  stderr warning; removed in v1.0).
- README quick start switched to `cd <dir> && ortim init "<brief>"`.

### Backward compatibility
- All 196 pool-layout workspaces continue to load + run. Pool ids passed
  as positional argument still resolve via `_resolve_project`'s pool-first
  fallback. Pool-mode Project.save / Project.load semantics unchanged.
- `ortim new` is preserved but emits a deprecation warning recommending
  `ortim init`. `--from-existing` still works for legacy automation.
- `WORKSPACE_ROOT` env var still respected for pool root.

### Migration
- Opt-in `ortim workspace migrate <pool-id> --to <path>` lifts a pool
  workspace into project mode: ortim metadata (`PRD.md`, `RFC.md`,
  `state.json`, `.cache/`, etc.) lands in `<path>/.ortim/`; user code
  (`src/`, `package.json`, ...) stays at `<path>/`. Default `--copy`
  preserves the pool dir for rollback; `--move` consumes it.
- 0.9.x retains both modes side by side. v1.0 will drop the pool layout
  and pool-related CLI flags entirely.

### Documentation
- New `docs/plans/2026-Q2-project-mode.md` design doc (mimari karar log,
  migration stratejisi, milestone planı, risk analizi).
- `docs/plans/2026-Q2-roadmap.md` Faz 3 scope updated to "Project Mode
  Pivot + Distribution"; 3.2 / 3.4 / 3.5 deferred to Faz 4.

## [0.8.2] — 2026-05-17

Patch: fix sidebar URLs.

### Fixed
- `project.urls.Source`, `Issues`, `Changelog` now point to the actual
  GitHub repo (`orhanurullah/ortim`) instead of the placeholder
  `ortimdev/ortim` used in 0.8.1.
- README `git clone` instruction + runbook contact link updated to
  match.

## [0.8.1] — 2026-05-17

Patch: README rewritten as public-facing landing page; PyPI metadata
expanded.

### Added
- `CHANGELOG.md` (this file) — Keep-a-Changelog format.
- `author_email = contact@ortim.dev` (placeholder until domain MX
  configured).
- `project.urls`: Documentation, Source, Issues, Changelog.

### Changed
- README is now a vitrin / landing page (~150 lines). Internal
  milestone history moved here, under "Development history (pre-public)".

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
