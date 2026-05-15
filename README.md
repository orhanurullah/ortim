# Ortim

> Yapay zeka destekli, sıkı kurallı, çok-ajanlı yazılım geliştirme platformu.

**Lisans:** FSL-1.1-Apache-2.0 (core) + Commercial (enterprise/). Bkz. `LICENSE` ve `LICENSE.commercial`.

7-katmanlı orchestrator + 12 ajan + document-driven flow (PRD → RFC → Task) + Golden Paths (T0–T6 web, M0–M2 mobile, D0–D1 desktop) + 7 HITL gate.

Felsefe: **markdown bilgiyi söyler, runtime kuralı zorlar**. LLM "atlamak" istese bile state machine, deterministic tier scorer ve DAG validator engeller.

Detaylı spec: **[Ortim_Architecture.md](./Ortim_Architecture.md)**

CLI komutu: `ortim` (canonical) — `ai-factory` alias geriye uyumluluk için korunur.

## Status: v0.8 (post M3.1 v1 production-ready + Item 48 ship)

> **2026-05-15 update:** **`ortim extend` end-to-end validated** — DONE projeye yeni feature ekleyebilen iteratif pipeline (M3.1 v1 = M3.1.0 foundation + M3.1.1 executor wiring + Item 48 AC-aggregation discipline). Iki proof-point: (1) planning chain — TR tagging brief, 4 task üretildi (saw-tooth module-drift correction by Architect, scope/continuity/ID-collision validators, M4 cross-task export visibility hepsi green); (2) execution chain — 3/4 task otomatik (T-007 schema first-attempt DONE; T-008 tagging CRUD 2nd-attempt DONE via Item 15a sandbox feedback; T-009 task-module ext AWAITING_HITL with valid L1 boundary + criterion-mismatch findings; T-010 not started). T-009 HITL **bug değil**, reviewer'ın iş tanımı. Test sayım: **404**; sıfır kalıcı regresyon. Açık actionable backlog: 8 (0× P2, 8× P3). M3.1 planning + happy-path execution production-ready; G-1/G-2 surveillance items added. **M5 RAG ertelendi** (M5-design.md §13.3 Option α). Detaylı: [`docs/backlog.md`](./docs/backlog.md), `tespit.md` "Execution-stage proof-point" bölümü.

| Bileşen | Durum |
|---|---|
| **Foundation (v0.4–v0.6d)** | |
| State machine + project lifecycle + 7 HITL gate'i (G1–G7) | OK |
| Babel TR↔EN intent + Memory loader (L1 / glossary / template / agent prompts) | OK |
| Worker + Reviewer chain (Code soft + Security/Test hard veto + Perf soft) | OK |
| Git branch isolation + `git worktree` paralel + serileştirilmiş merge | OK |
| Test runner (per-task scope, vitest/pytest/flutter), hooks (`pre_commit` + `pre_deploy`) | OK |
| Multi-LLM (Anthropic + DeepSeek) + per-role routing + per-provider budget | OK |
| Audit JSONL hash chain + thread-safe + budget tracker | OK |
| Golden Paths scorer T0–T6 + tier docs + RFC template §1–§16 | OK |
| **M1 — Brownfield desteği (2026-05-08)** | |
| Codebase reader + framework detection + `bootstrap_brownfield` | OK |
| Mobile (M0–M2 Flutter) + Desktop (D0–D1 Tauri) tier'ları | OK |
| `ortim new --from-existing` / `inspect` / `rescan` / `baseline` komutları | OK |
| **M1.5 — Workspace bootstrap (2026-05-08)** | |
| `runtime/architecture/bootstrap.py` — per-tier root template + auto-retry loop | OK |
| Windows console UTF-8 reconfigure (cp1254 crash fix) | OK |
| `_NPM_DEP_REGISTRY` (`react`/`vite`/`zod`/`idb`/`dexie`/`localforage`/...) + `_FRAMEWORK_PACKAGES` map | OK |
| Test peer auto-pull (`@testing-library/react`, `fake-indexeddb`) | OK |
| Silent-drop visibility — unknown `key_library` → stderr WARNING | OK |
| **Phase 0 — Foundation hardening (2026-05-08)** | |
| Reviewer rubric (per-criterion verdict + L1 ayrım + `unverifiable` 2-mode) | OK |
| Orchestrator binary acceptance criteria (Hard Rule 10 ban-list) | OK |
| Test runner auto-detect (`.ai-factory.env` from tier+app_class) | OK |
| Reviewer length validator (retry-with-correction) + sandbox feedback in `prior_reasons` | OK |
| **M2 — Conversational Intake (2026-05-13)** | |
| Dialog states `INTAKE_DIALOG` / `STACK_DIALOG` / `PRD_DIALOG` + `ortim discuss`/`refine`/`lock`/`show` | OK |
| Split analysts: `IntentAnalyst` / `StackAnalyst` / `PRDAnalyst` | OK |
| `LockedStack` artifact — single source of truth for downstream layers | OK |
| **M3 — Skills system (2026-05-13)** | |
| `skills/<scope>/<name>.md` frontmatter + resolver + per-task injection | OK |
| 6 seed skills (typescript-module-boundaries, sql-mock-patterns, react-dependency-injection, react-ui-test-text-matching, ...) | OK |
| **M4 — Cross-task export visibility (2026-05-13)** | |
| Worker sees prior DONE task'ların public export'larını; import shape inference | OK |
| **M3.1 — `ortim extend` iteratif geliştirme (2026-05-15)** | |
| EXTEND_DIALOG / EXTEND_PRD / EXTEND_RFC state machine + G1/G2 cycle N HITL gates | OK |
| `ExtenderAgent.draft_delta_prd` / `draft_delta_rfc` + BLOCKED-STACK escape hatch | OK |
| Idempotent `delta_writer.append_delta_section` (cycle = de-dupe key) | OK |
| `Orchestrator.generate_dag(prior_dag=...)` + ID collision / continuity / scope-union validators | OK |
| Extend-cycle AC-aggregation guidance (10-AC → 3-5 task target) | OK (Item 48) |
| `ortim extend <id> "<brief>"` + `ortim extensions <id>` CLI | OK |
| **Operational hardening (Items 22–24, 40, 42–48)** | |
| LLM transient retry (503/429 exponential backoff) | OK (Item 22) |
| Provider fail-loud (critical roles emit stderr WARNING on global fallback) | OK (Item 23) |
| `unverifiable_reason` two-mode (`criterion_design` vs `test_infrastructure`) | OK (Item 24) |
| Architect §4 key_libraries discipline (post-draft subset validator + retry) | OK (Item 40) |
| Architect Call 1 derivation rules (single-user → small/solo/low; few-shot) — 5/5 deterministic | OK (Item 45) |
| Orchestrator DAG-RFC module match (Hard Rule 13 + validator) | OK (Item 42) |
| Reviewer stack-citation discipline (`stack.json.key_libraries` verbatim) | OK (Item 43) |
| StackAnalyst browser-only intent detection (Hono/Express/Fastify/Koa forbidden) | OK (BaaS-drift) |
| `_INDEXEDDB_PEERS` auto-pull `fake-indexeddb` for jsdom shim | OK (Item 47b) |
| Orchestrator extend-cycle AC-aggregation discipline | OK (Item 48) |
| **Deferred** | |
| M5 RAG (Obsidian) + MCP | Ertelendi (M5-design.md §13.3 Option α) |
| Drift detector + GC + migration agent | Future (M3.1.2 — multi-cycle continuity'den sonra) |
| G-1 M4 export visibility vs barrel-import (extend mode) | Surveillance — 2 more occurrences |
| G-2 `test_infrastructure_unavailable` mode coarseness | Surveillance — 2 more occurrences |

## Kurulum

Gereksinimler: **Python 3.11+**, **Anthropic API key** (`run` komutu için; `score-tier` ve state komutları key gerektirmez).

```powershell
cd C:\Flutter\projects\ai-factory

python -m venv .venv
.\.venv\Scripts\Activate.ps1

pip install -e .

Copy-Item .env.example .env
# .env dosyasını düzenle, ANTHROPIC_API_KEY ekle
```

## Hızlı Başlangıç

```powershell
# 1. Yeni proje aç (Türkçe brief)
ortim new "Bir görev yönetim uygulaması istiyorum" --name todo-app
# → workspaces/<id>/state.json oluşur, state = intake

# 2. Babel + Analyst + Architect + Orchestrator pipeline'ı çalıştır
ortim run <project-id>
# → intent.json → PRD.md → HITL Gate G1

# 3. PRD'yi gözden geçir (workspaces/<id>/PRD.md), sonra onayla
ortim advance <project-id> prd_approved --note "reviewed"

# 4. Architect + Orchestrator devam etsin
ortim run <project-id>
# → golden_path_inputs.json → tier seçimi → RFC.md → HITL Gate G2

# 5. RFC'yi onayla
ortim advance <project-id> rfc_approved --note "reviewed"

# 6. TaskDAG üretsin
ortim run <project-id>
# → task_dag.json + tasks/T-*.md (her atomic task için)

# 7. Task DAG'ı incele
ortim tasks <project-id>

# 8. Token + maliyet raporu
ortim budget <project-id>
```

## CLI Referansı

| Komut | Amaç |
|---|---|
| `ortim doctor [--json]` | Environment health check: Python sürümü, API key'ler, runtime binaries (node/git/flutter/cargo/go), agent prompts, skill dir. Exit 0 clean / 2 recommended eksik / 3 required eksik. |
| `ortim demo [--brief "..."] [--execute]` | End-to-end planning walkthrough: brief → PRD → RFC → DAG. G1/G2 auto-approve, dialog-mode-off scoped. ~$0.02-0.05 cost on DeepSeek. `--execute` ile T-001'i de koştur. |
| `ortim new <brief> --name <ad>` | Yeni proje aç |
| `ortim run <id> [--step babel\|analyst\|architect\|orchestrator\|auto]` | Mevcut state'e göre uygun ajanı koştur |
| `ortim status <id>` | Proje detayı + history |
| `ortim list-projects` | Tüm projeler |
| `ortim tasks <id>` | TaskDAG + paralel batch'ler |
| `ortim execute <id> <task-id> [--max-attempts N]` | Tek task'ı Worker → tests → Reviewer pipeline'ından geçir |
| `ortim run-all <id> [--max-attempts N] [--continue-on-fail] [--parallel] [--max-workers N]` | DAG'ı topolojik batch'lerde koştur (default sıralı; `--parallel` ile worktree'li thread pool) |
| `ortim budget [<id>]` | Token + USD raporu (audit log üzerinden) |
| `ortim retro <id> [--per-task] [--category <name>] [--json]` | Retrospective rollup: per-category token+USD, per-task attempt counts (worker / sandbox / reviewer reject), skill triggers, HITL escalations, task wall-time p50/p95 |
| `ortim drift-check <id> [--json]` | Multi-cycle integrity check: module scope (D1), ID continuity (D2), ID collision (D3), status↔audit reconciliation (D4). Exit 0 clean / 2 warning / 3 error. |
| `ortim states` | Tüm state'ler ve izinli geçişler |
| `ortim advance <id> <target> [--note]` | Manuel state ilerletme (HITL onayları + acil durum) |
| `ortim score-tier [...]` | Verilen input'larla tier seçim algoritmasını koştur (API key gerekmez) |
| `ortim extend <id> "<brief>"` | DONE projeye yeni feature delta'sı: Babel → ExtenderAgent → delta PRD; G1 (cycle N) açılır |
| `ortim extensions <id>` | Projenin extend cycle geçmişi (PRD.md'den okur) |

## State Machine ve HITL Gate'ler

```
intake → babel_processing → prd_drafting → prd_awaiting_approval → prd_approved
                                                  ↑ G1 ↓
       → rfc_drafting → rfc_awaiting_approval → rfc_approved → tasks_generating
                              ↑ G2 ↓
       → tasks_ready → executing → done
                                  ↘ failed / paused (her noktadan)
```

- Her transition `runtime/orchestrator/state_machine.py:TRANSITIONS` içinde explicit. Atlamak imkansız (`InvalidTransition` raise).
- **G1 (PRD)** ve **G2 (RFC)** zorunlu insan onayı. CLI `prd_awaiting_approval` veya `rfc_awaiting_approval`'da durur, kullanıcı `advance ... prd_approved` çağırmadan ilerlemez.
- G3–G7 (schema, external, security, deploy, budget) iter 5+ ile gelecek.

## Mimari Akış

```
[TR brief]
   ↓
Babel (intent.json + TR round-trip)
   ↓
Analyst (PRD.md, [NEEDS-INPUT] eksikler işaretlenir)
   ↓ G1
Architect (1) GoldenPathInputs JSON (LLM)
          (2) tier seçimi (deterministic — score_tier ayrıca CLI'dan)
          (3) RFC.md (LLM, tier KİLİT)
   ↓ G2
Orchestrator (TaskDAG: id formatı T-*, deps, ≤20K token/task,
              cycle + missing-dep validation, 3x retry)
   ↓
Worker + Reviewer (iter 5)
```

Önemli boundary'ler:
- **Tier seçimini LLM yapmaz.** Architect agent PRD'den input çıkarır; `runtime/architecture/golden_paths.py` kural-temelli skor hesaplar. T4 (Modular Monolith) hiç bloklanmayan default.
- **Analyst teknik karar veremez.** Sistem promptu yasaklar; PRD template'i tech-stack alanı içermez.
- **Orchestrator'un DAG'ını runtime validate eder.** LLM cycle veya eksik dependency üretirse retry; 3 hata = `failed`.

## Klasör Yapısı

```
ai-factory/                    # repo dizini (rename edilmedi; canonical brand: Ortim)
├── Ortim_Architecture.md       Master spec
├── LICENSE                     FSL-1.1-Apache-2.0 (core)
├── LICENSE.commercial          Commercial (enterprise/)
├── NOTICE                      Third-party attribution
├── enterprise/                 Commercial-licensed tier (M5+ kapsamı, M1'de boş iskelet)
├── README.md                  Bu dosya
├── pyproject.toml             Paket + ruff + mypy + pytest config
├── .env.example               Anthropic key + bütçe + audit path
├── docs/
│   ├── principles/core.md     L1 immutable kurallar
│   ├── golden-paths/          T0–T6 (şu an: index + T4 detaylı)
│   ├── glossary/tr-en.md      Babel sözlüğü
│   └── templates/             PRD / RFC / Task template'leri
├── agents/                    Ajan system promptları (babel, analyst, architect, orchestrator)
├── runtime/
│   ├── main.py                CLI entry (typer + rich)
│   ├── orchestrator/
│   │   ├── state_machine.py   States + TRANSITIONS + HITL_GATES
│   │   ├── project.py         Project model + persist + transition + history
│   │   └── task_dag.py        TaskSpec + TaskDAG + Kahn validation + topological_batches
│   ├── babel/intent.py        StructuredIntent + extract + round_trip
│   ├── memory/loader.py       Markdown concat (principles, glossary, templates, agent prompts)
│   ├── architecture/
│   │   └── golden_paths.py    Tier enum + GoldenPathInputs + 7 scorer + select_tier
│   ├── agents/                Analyst / Architect / Orchestrator agent classes
│   ├── llm/client.py          Anthropic wrapper (system+user, token usage döndürür)
│   ├── audit/logger.py        JSONL append-only event log
│   ├── budget/tracker.py      Audit log → token & cost raporu
│   ├── concurrency/lock.py    mkdir-atomic file lock (LockTimeout, stale recovery)
│   └── executor/              (iter 5)
├── workspaces/                Per-project state (gitignored: state.json, intent.json, PRD.md, RFC.md, tasks/, task_dag.json)
└── tests/                    state_machine, memory_loader, golden_paths, budget_tracker, task_dag, concurrency_lock, executor, audit_logger
```

## Yol Haritası

### İter 5a + 5b (TAMAMLANDI) — Worker, sandbox, git, test runner, batch executor

5a'da boundary'ler izole edildi (sandbox + soft-veto reviewer); 5b'de yetenekler genişletildi.

- **`runtime/executor/sandbox.py`** — `normalize_relative` (abs/`..`/Win drive reject), `check_in_scope` (prefix match, sibling/lookalike reject), `check_extension` (kaynak kod + config + docs + bilinen basename whitelist; binaries reject), `resolve_in_workspace` (symlink escape reject)
- **`runtime/executor/worker.py`** — `WorkerAgent` (LLM + sandbox-validated `WorkerOutput`); reject ettiğinde retry'da prior reviewer reasons'ı yeni prompt'a inject eder
- **`runtime/executor/reviewer.py`** — `CodeReviewerAgent` (soft veto; test result görür, fail varsa hard reject)
- **`runtime/executor/status.py`** — `task_status.json` sidecar (PENDING/IN_PROGRESS/DONE/FAILED/AWAITING_HITL + attempts + last verdict)
- **`runtime/executor/git_ops.py`** — subprocess wrapper: `ensure_repo` (init + main + seed commit), `start_task_branch`, `commit_changes`, `merge_task_to_main`, `abandon_task_branch`. Env-driven via `AI_FACTORY_GIT_ENABLED=auto|true|false`.
- **`runtime/executor/test_runner.py`** — `AI_FACTORY_TEST_CMD` set edilirse subprocess'le çalışır (timeout, exit code, stdout/stderr tail). Auto-detect yok — kullanıcı açık seçim yapar.
- **`runtime/executor/runner.py`** — `execute_task()` çekirdek pipeline: Worker → write files → run tests → Reviewer → commit/abandon. CLI thin wrapper.
- **CLI:** `execute <id> <task-id>` (tek task), `run-all <id>` (DAG'ı topolojik batch'lerde sıralı koştur)
- **Smoke test:** 30/30 (`tests/test_executor.py`, LLM-free; git lifecycle dahil)
- **Agent prompts:** `agents/worker.md`, `agents/reviewer.md` v0.5b kuralları (file whitelist, test contract)

### İter 5c (TAMAMLANDI) — Paralel batch execution + worktree

5b'de tek-tek seri çalışan executor, 5c'de batch içindeki bağımsız task'lar için paralelleşti.

- **`runtime/executor/git_ops.py`** — `add_worktree(workspace, task_id)` fresh `task/<id>` branch'i `<workspace>/.worktrees/<task_id>` altına bağlar; `remove_worktree` + `merge_task_to_main` worktree-aware (merge sonrası worktree silinir, sonra `branch -D`). `add_worktree` idempotent — eski worktree/branch kalıntılarını otomatik temizler.
- **`runtime/executor/runner.py`** — `execute_task(..., use_worktree=True)` Worker write + test + reviewer'ı worktree dizininde koşturur; commit worktree'de yapılır, `ExecutionResult.needs_merge=True` döner. Caller (yalnız `run-all --parallel`) merge'i seri biçimde yapar. Sequential mod (`use_worktree=False`) eskisi gibi: worker direkt ana repo'da `task/<id>` checkout eder ve inline merge eder.
- **`runtime/main.py:run-all`** — `--parallel` / `--sequential` (default: sequential), `--max-workers N` (default: 4). Paralel modda: `ThreadPoolExecutor` ile batch içi paralel exec; `merge_lock` ile merge serileştirilir; `status_lock` ile `task_status.json` save serileştirilir; merge conflict → task `AWAITING_HITL`. Workspace bazlı `file_lock(workspace/.exec)` aynı projede iki `run-all`'ı engeller.
- **`runtime/concurrency/lock.py`** — `mkdir`-atomic file_lock şimdi aktif kullanımda (`run-all` exec lock + paralel test'ler), stale-lock recovery (>2x timeout) korunuyor.
- **`runtime/audit/logger.py`** — `threading.Lock` ile per-instance write serializasyonu eklendi; paralel Worker'lar JSONL satırlarını bozmaz.
- **Batch-level metrikler** — her batch sonunda `executor_batch_metrics` audit event: `wall_seconds`, `sum_task_seconds`, `speedup`, `merge_wait_seconds`, `task_count`, `mode`, `max_workers`. Konsolda paralel batch için "batch süresi Xs, hızlanma xN" satırı.
- **Smoke test:** 88/88 (`tests/test_executor.py` 33, `test_concurrency_lock.py` 5, `test_audit_logger.py` 2 — concurrent JSONL integrity dahil; diğer suite'ler değişmedi)

### İter 6a (TAMAMLANDI) — Multi-LLM provider abstraction + DeepSeek

LLM çağrıları artık provider-agnostic. DeepSeek'in Anthropic-uyumlu endpoint'i (`https://api.deepseek.com/anthropic`) `anthropic` SDK ile çalışır — sadece `base_url` farklı.

- **`runtime/llm/providers.py`** (yeni) — `ProviderConfig` registry: `anthropic`, `deepseek`. `pricing_for(provider, model)`, `resolve_provider(name)`.
- **`runtime/llm/client.py`** — provider seçimi `resolve_provider`'dan; `Anthropic(api_key, base_url)`. `LLMResponse.provider` field'ı + `audit_fields()` helper'ı (`tokens` + `provider` + `model` döner).
- **`runtime/llm/router.py`** (yeni) — `client_for(role)`: `<ROLE>_PROVIDER`/`<ROLE>_MODEL` env override → `LLM_PROVIDER`/`DEFAULT_MODEL` → provider default.
- **Agent başına LLM** — `main.py`'da Babel/Analyst/Architect/Orchestrator/Worker/Reviewer her biri kendi `client_for(role)` çağrısıyla başlar; pahalı kararlar Claude'da, ucuz işler DeepSeek'te tutulabilir.
- **`runtime/budget/tracker.py`** — per-provider pricing. `BudgetReport.per_provider: dict[str, ProviderBreakdown]`. CLI: `ortim budget --by-provider`.
- **Audit log** — her LLM çağrısı satırı `provider` + `model` taşır; eski satırlar geriye uyumlu (default: anthropic).
- **Smoke test:** 19 yeni test (`test_llm_providers.py` 9, `test_llm_router.py` 6, `test_budget_multi_provider.py` 4); regression yok, tüm suite 107/107.

### İter 6b (TAMAMLANDI) — Multi-reviewer (hard veto)

CodeReviewer (soft veto, functional correctness) üstüne 3 yeni reviewer:

- **`agents/security_reviewer.md` + `runtime/executor/security_reviewer.py`** — `SecurityReviewerAgent` (hard veto). Threat catalogue: injection (SQL/shell/eval), hard-coded secrets, authn/authz bypass, insecure crypto (MD5/ECB), path traversal, SSRF, CSRF, sensitive data in logs, known-CVE deps. Severity high/medium → reject; low → suggestion.
- **`agents/test_reviewer.md` + `runtime/executor/test_reviewer.py`** — `TestReviewerAgent` (hard veto). AC × test eşleştirme zorunlu (`ac_coverage: [{ac, test}]` döner); test runner failure → otomatik reject; happy-path-only → reject.
- **`agents/perf_reviewer.md` + `runtime/executor/perf_reviewer.py`** — `PerfReviewerAgent` (soft veto). N+1, missing index, unbounded loop, sync I/O, bundle bloat, missing pagination. Bulgular `last_review_suggestions`'e `[perf] ...` etiketiyle düşer; merge'i blok etmez.
- **`runtime/executor/runner.py:ReviewerChain`** — opsiyonel `(security, test, perf)`; her biri bağımsız None olabilir. Pipeline: CodeReviewer + tests OK → Security → (OK ise) Test → (her durumda) Perf. Hard veto yakaladığında: **retry budget'ı atlanır, task doğrudan `AWAITING_HITL`** (security/test gap'i aynı Worker'ı yeniden çağırarak çözülmez).
- **`ExecutionResult.verdicts`** ve **`blocked_by`** — her reviewer'ın çıktısı saklanır; hard veto veren reviewer'ın adı `blocked_by`'da.
- **`AI_FACTORY_HARD_REVIEWERS=on`** env flag'i; default `off` (geriye uyumlu — pre-6b davranış). API key eksik bir reviewer için degrade-warn (chain'in geri kalanı çalışmaya devam).
- **CLI:** `ortim execute` ve `run-all` çıktısında `BLOCKED` etiketi + `[security]/[test]/[perf]` etiketli reasons.
- **Smoke test:** 7 yeni test (`test_reviewer_chain.py`); `FakeLLM` ile gerçek API çağrısız: legacy chain=None davranışı, security hard veto → AWAITING_HITL, test hard veto sonrası, perf soft-only, verdict parse'ları. Tüm suite 114/114.

### İter 6c (TAMAMLANDI) — HITL G3–G7 + hooks

- **Project-level gate state'leri:** `SCHEMA_AWAITING_APPROVAL` (G3), `BUDGET_AWAITING_APPROVAL` (G7), `DEPLOY_AWAITING_APPROVAL` (G6) — `runtime/orchestrator/state_machine.py` `TRANSITIONS` ve `HITL_GATES` güncellemeleri.
- **Task-level gate'ler:** G4 (external integration) ve G5 (security severity high/medium) doğrudan task → `AWAITING_HITL` ile yönetilir; faz 6b'deki SecurityReviewer hard veto bunu yapıyordu.
- **`runtime/orchestrator/gate_detector.py`** (yeni) — saf fonksiyonlar:
  - `detect_schema_tasks(dag)` → `SchemaGateEvidence` (DDL/migration regex + path hint'leri).
  - `detect_external_calls(worker_output)` → `ExternalGateEvidence` (boto3/httpx/requests/stripe/twilio import + non-local URL).
  - `detect_security_severity(verdict)` → `SecurityGateEvidence` (duck-typed verdict kabul eder, circular import'tan kaçınır).
  - `detect_budget_breach(tracker, project_id, cap_usd)` → `BudgetGateEvidence` (overage % dahil).
- **`runtime/hooks/registry.py`** (yeni) — `run_hook("pre_commit"|"pre_deploy", cwd, audit, ...)`. Komut env'leri: `AI_FACTORY_LINT_CMD`, `AI_FACTORY_FORMAT_CHECK_CMD`, `AI_FACTORY_DEPLOY_CMD`. Chain'de ilk fail short-circuit; her hook event'i audit'a `hook_event` olarak düşer (`exit_code`, `duration_seconds`, `stderr_tail`). `AI_FACTORY_HOOKS_ENABLED=false` ile global disable.
- **Pre-commit entegrasyonu** — `runner.py:execute_task` Reviewer chain onayladıktan SONRA `commit_changes` ÖNCESİ `pre_commit` hook'u çağırır. Hook fail ise: branch abandon, last_review_reasons'a `[pre_commit] hook failed (exit X); stderr tail: ...` push, task PENDING (retry budget tüketir → AWAITING_HITL).
- **CLI:** `ortim gates <project-id>` — açık project gate'leri + advisory schema/budget gate raporu.
- **Smoke test:** 20 yeni test (`test_gate_detector.py` 13, `test_hooks.py` 7); regression yok, suite 134/134.

### İter 6d (TAMAMLANDI) — RFC template §11–§16 + 6 yeni tier doc

- **`docs/templates/RFC.template.md`** — yeni bölümler:
  §11 Deployment Strategy (rollout pattern, health checks, rollback prosedürü), §12 Observability Baseline (RED/USE metrikler, log alanları, alerting kuralları), §13 Security Posture (secret yönetimi, authn/authz, audit trail, threat model, dep audit), §14 Test Strategy (pyramid dağılımı, coverage floor, mutation score, contract test'ler, perf budget), §15 Disaster Recovery (RTO/RPO, backup, failover prosedürü, DR drill cadence), §16 Runbook Sketch (oncall senaryoları + escalation).
- **`agents/architect.md`** — Call 2 boundary'lerine eklendi: §11–§16 doldurma zorunlu, eksikler `**[NEEDS-INPUT]**: <soru>` formatında işaretlenmeli; her bölüm için somut quality bar (numeric thresholds, command-level rollback adımları, vb.).
- **6 yeni tier dokümanı** — `docs/golden-paths/T{0,1,2,3,5,6}-*.md`, her biri ~80–110 satır, tutarlı format: When to use / When NOT / Architecture / Canonical Tech Stack / Cross-cutting / Blocker conditions / Migration path / Notes. T4 dışında hiç detayı olmayan 6 tier artık Architect'in RFC üretiminde gerçek rehbere sahip.
- **`docs/templates/Task.template.md`** — yeni "Integration / Staging" bölümü (staging smoke check, feature flag, backwards-compat).
- **`docs/golden-paths/index.md`** — 6 yeni doc'a referans güncellemesi (eski "stubs in iter 4+" satırı kaldırıldı).

### M1 — Brownfield (2026-05-08, TAMAMLANDI)
- `runtime/codebase/{reader,frameworks,baseline,schema}.py` — gitignore-aware walk, AST/regex export extraction, framework detection
- Mobile (M0–M2 Flutter) + Desktop (D0–D1 Tauri) tier'ları
- `ortim new --from-existing` + `inspect` / `rescan` / `baseline` CLI

### M1.5 — Bootstrap layer (2026-05-08, TAMAMLANDI)
- `runtime/architecture/bootstrap.py` — per-tier root template (T2/web: `package.json` + `tsconfig.json` + `vite.config.ts` + `setupTests.ts` + `.gitignore`); idempotent, mevcut dosyalara dokunmaz
- Auto-retry loop (sequential branch); `prior_reasons` sandbox feedback enjeksiyonu
- Windows UTF-8 console reconfigure (cp1254 crash fix)

### Phase 0 — Foundation hardening (2026-05-08, TAMAMLANDI)
- Reviewer rubric (per-criterion verdict + `unverifiable` two-mode: `criterion_design` vs `test_infrastructure`)
- Orchestrator Hard Rule 10 — binary acceptance criteria ban-list
- `.ai-factory.env` test-cmd auto-write from tier+app_class

### M2 — Conversational Intake (2026-05-13, TAMAMLANDI)
- Dialog states `INTAKE_DIALOG` / `STACK_DIALOG` / `PRD_DIALOG`
- `ortim discuss <id>` / `refine <id> "<feedback>"` / `lock <id>` / `show <id>`
- Split analysts: `IntentAnalyst` (intent.md) + `StackAnalyst` (LockedStack JSON) + `PRDAnalyst` (PRD.md)

### M3 — Skills system (2026-05-13, TAMAMLANDI)
- `skills/<scope>/<name>.md` frontmatter (`name`, `description`, `audience`, `triggers`)
- Resolver: tier > app_class > language > keyword spesifiklik sırasıyla; per-call char budget
- 6 seed skill (typescript-module-boundaries, typescript-imports-from-locked-stack, typescript-sql-mock-patterns, react-component-patterns, react-dependency-injection, react-ui-test-text-matching)

### M4 — Cross-task export visibility (2026-05-13, TAMAMLANDI)
- Worker prompt'una önceki DONE task'ların `index.ts` / `__init__.py` export'larından AST-extracted signature listesi enjekte edilir
- Cross-task interface mismatch (önceden T-009 sınıfı failure) sınıfını yapısal olarak kapatır

### M3.1 — `ortim extend` iteratif geliştirme (2026-05-15, TAMAMLANDI)
- **M3.1.0 foundation** — state machine: 7 yeni state (DONE → EXTEND_DIALOG → EXTEND_PRD_DIALOG/APPROVAL/APPROVED → EXTEND_RFC_DRAFTING/APPROVAL/APPROVED → TASKS_GENERATING) + 2 yeni HITL gate (G1/G2 cycle N); `runtime/extend/{schema.py,extender_agent.py,delta_writer.py}`; idempotent delta section append (cycle = de-dupe key); BLOCKED-STACK escape hatch; +45 test
- **M3.1.1 executor wiring** — `Orchestrator.generate_dag(prior_dag=...)` + 3 validator: ID collision, continuity (`> prior_max`), scope-union membership (parent §7 ∪ `### Module Breakdown (delta)` H3); `ortim run` extend dispatch (EXTEND_PRD_APPROVED → EXTEND_RFC + EXTEND_RFC_APPROVED → TASKS_READY); DAG merge persistence + `extensions: list[DagDelta]` field; +17 test
- **Item 48 — extend-cycle AC-aggregation discipline** — `agents/orchestrator.md` `## Extend Cycle Task Granularity` section: aggregation by `(module_scope × behavioral cluster)`, 10-AC delta → 3-5 task anchor, trace-back rule (every task → delta RFC Module Breakdown row OR delta AC); runtime context block references the section by name; +2 test. Empirical (same TR brief, fresh v3 clone): 11 ACs → 4 tasks vs pre-fix 10 ACs → 10 tasks; **~60% reduction**
- **End-to-end proof-point** — `proofpoint48` workspace: planning chain clean (delta PRD + delta RFC + delta DAG validators all silent); execution chain 3/4 task otomatik (T-007 schema first-attempt; T-008 sandbox-feedback retry; T-009 valid HITL escalation with L1 + criterion findings)
- CLI: `ortim extend <id> "<brief>"` + `ortim extensions <id>`

### Operational hardening (2026-05-08 → 2026-05-14, TAMAMLANDI)
- Item 22 — LLM transient retry (503/429 exponential backoff)
- Item 23 — Provider fail-loud (critical role + global fallback → stderr WARNING)
- Item 24 — `unverifiable_reason` two-mode schema separation
- Item 40 — Architect §4 `key_libraries` discipline (post-draft subset validator + retry-with-correction)
- Item 41/41' — Bootstrap `_FRAMEWORK_PACKAGES` map (React + Vite / Vue + Vite / Next / Hono / Express deps + testing-library quartet + jsdom)
- Item 42 — Orchestrator DAG-RFC module match (Hard Rule 13 + RFC §7 parser + scope subset validator)
- Item 43 — Reviewer stack-citation discipline (`stack.json.key_libraries` verbatim quote)
- Item 44 — `skills/react/dependency-injection.md` (Pattern A: props down; Pattern B: Context; anti-patterns)
- Item 45 — Architect Call 1 derivation rules (single-user → `small/solo/low`; few-shot examples). Empirically validated: 5/5 deterministic on v4 PRD via `scripts/item_45_empirical.py`.
- Item 46 — Bootstrap honors `locked_stack.primary_framework` over heuristic tier (T4 + React stack → vite.config writers fire)
- Item 47 — `_NPM_DEP_REGISTRY` browser-persistence coverage (`idb`, `dexie`, `localforage`) + silent-drop stderr WARNING
- Item 47b — `_INDEXEDDB_PEERS` auto-pull `fake-indexeddb` for jsdom shim
- BaaS-drift — `agents/stack_analyst.md` Browser-only intent detection (Hono/Express/Fastify/Koa forbidden when ≥2 browser-only + 0 backend signals)
- UI-text-match — `skills/react/ui-test-text-matching.md` (UI ↔ test assertion symmetry)

### Ertelenenler
- **M5 RAG (Obsidian) + MCP** — M5'in birincil değer önerisi olan Item 45 prompt fix ile kapandı; M5 "platform foundation" pozisyonuna geçti. Tam analiz: [`M5-design.md`](./M5-design.md) §13.
- **M3.1.2 — Drift detector** — workspace'in `DONE` ile `extend` arasında manuel edit edilmesi durumu. Multi-cycle continuity hata raporu beklemede.
- **G-1 — M4 export visibility vs barrel-import discipline (extend mode)** — `proofpoint48` T-009'da Worker barrel import yerine internal path kullandı; 2 daha aynı sınıf gözlemden sonra item açılır.
- **G-2 — `test_infrastructure_unavailable` mode coarseness** — Worker test quality issue'ları (örn. yanlış kullanılmış `expect(...).rejects`) mod-olarak infrastructure failure görünüyor; `worker_test_quality_failure` mode'u ayrılabilir. Aynı sınıftan 2 daha gözlem bekleniyor.

## Geliştirme

```powershell
# Lint + format check
ruff check .

# Type check (strict)
mypy runtime

# Test (smoke + ileride birim)
pytest

# State machine sanity (stdlib-only, deps yokken bile)
python tests\test_state_machine.py
```

Code patterns:
- LLM çağrıları → `LLMClient.call(system, user, temperature, max_tokens)` — token usage döner, audit'a `tokens={"in":..,"out":..}` field'ıyla yaz.
- Yeni state ekliyorsan: `ProjectState`, `TRANSITIONS` ve gerekirse `HITL_GATES`'i güncelle, `tests/test_state_machine.py`'ye geçişi ekle.
- Yeni ajan: `agents/<name>.md` (system prompt) + `runtime/agents/<name>.py` (class) + `MemoryLoader.load_agent_prompt("<name>")` zaten çalışır.
- LLM çıktısı parse edeceksen `runtime/babel/intent.py:_strip_code_fences` reuse et.

## Sorun Giderme

| Belirti | Sebep / Çözüm |
|---|---|
| `ANTHROPIC_API_KEY not set` | `.env` dosyası yok veya boş. `Copy-Item .env.example .env` sonra düzenle. |
| `Cannot transition X -> Y. Allowed: [...]` | LLM/CLI yanlış sıraya girmiş; state machine doğru çalışıyor. `ortim states` ile geçerli geçişleri gör. |
| `Orchestrator failed to produce a valid DAG after 3 attempts` | RFC çok belirsiz ya da LLM cycle/missing-dep üretmeye devam ediyor. Audit log'da `orchestrator_dag_validation_failed` kayıtları sebebi söyler. RFC'yi netleştir, `ortim advance <id> rfc_drafting` ile geri al. |
| `estimated_tokens=X exceeds 20K cap` | LLM tek bir task'ı çok büyük tahminliyor. Orchestrator promptunda task'ın bölünmesini iste, RFC'yi daha küçük slice'lara böl. |
| `intent.json missing` / `PRD.md missing` | Önceki state atlanmış. `ortim status <id>` ile state'i kontrol et, eksik adımı `--step` ile manuel koştur. |
| `LockTimeout` | Aynı workspace'de paralel komut. Beklemekte; ya da çökmüş eski lock (>60s sonra otomatik temizlenir). |

## Paralel Çalıştırma

```powershell
# Sıralı (default): tek tek, ana repo `task/<id>` checkout
ortim run-all <project-id>

# Paralel: batch içindeki bağımsız task'lar `git worktree` ile izole, ThreadPool ile koşar
ortim run-all <project-id> --parallel --max-workers 4
```

Paralel mod gereksinimleri:
- `git` PATH'te olmalı, `AI_FACTORY_GIT_ENABLED=false` set edilmemeli
- Aynı workspace'te ikinci `run-all` engellenir (workspace exec lock)
- Worktree'ler `<workspace>/.worktrees/<task_id>/` altında; task DONE → merge sonrası otomatik silinir, REJECTED → cleanup'ta silinir
- Merge conflict → task `AWAITING_HITL`, `task_status.json`'a `last_error: merge: ...` yazılır

Audit'a her batch için `executor_batch_metrics` event'i düşer (wall/sum süre, speedup, merge wait, mode). `runtime/audit/decisions.jsonl` üzerinden batch maliyetleri analiz edilebilir.

## Sonraki Adım

**2026-05-15 update — M3.1 v1 production-ready, end-to-end validated:**

Tek oturumda ship + iki proof-point + execution-stage validation:
- **Planning chain** (Item 48 sonrası): TR tagging brief → delta PRD (Architect saw-tooth module-drift correction) → delta RFC (`### Module Breakdown (delta)` H3 doğru format) → delta DAG **4 task** (vs pre-fix 10) — scope/continuity/ID-collision validators all silent
- **Execution chain** (`run-all proofpoint48`): T-007 schema first-attempt DONE; T-008 tagging CRUD 2nd-attempt DONE (Item 15a sandbox feedback fired); T-009 task ext valid HITL escalation (L1 boundary + criterion mismatch + 2× test_infrastructure_unavailable Item 24 mode); T-010 not started post-T-009 halt. T-009 HITL **doğru sistem davranışı**, reviewer'ın iş tanımı
- Day spend: ~$0.16; pytest 339 → **404** (+65 with M3.1.0 + M3.1.1 + Item 48); G-1/G-2 surveillance items added to DEFERRED

Sıradaki sprint adayları (öncelik sırasıyla):
1. **PyPI publish hazırlığı + landing page** (SQ-1 + SQ-3): `name="ortim"` rezerv, ilk satışa açık sürüm tagging, ortim.dev iskeleti. ~1 hafta. **Foundation artık satılabilir state'te** — M3.1 dahil iteratif geliştirme demosu mümkün.
2. **Enterprise tier MVP scoping** (SQ-2): multi-tenant orchestrator, SSO, audit retention, SLA. Geniş kapsamlı; önce strateji belgesi.
3. **G-1 / G-2 surveillance** — pattern surface ederse 2-3 run sonra item açılır; proaktif fix henüz gerekmiyor.
4. **M3.1.2 drift detector** — multi-cycle continuity gerçek user reportu beklemede.

Öncelik kararı için: `docs/backlog.md` canonical view, `tespit.md` "Execution-stage proof-point" bölümü, `M5-design.md` §13 mapping, `docs/item-template.md` yeni item şablonu.
