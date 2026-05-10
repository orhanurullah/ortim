# Ortim

> Yapay zeka destekli, sıkı kurallı, çok-ajanlı yazılım geliştirme platformu.

**Lisans:** FSL-1.1-Apache-2.0 (core) + Commercial (enterprise/). Bkz. `LICENSE` ve `LICENSE.commercial`.

7-katmanlı orchestrator + 12 ajan + document-driven flow (PRD → RFC → Task) + Golden Paths (T0–T6 web, M0–M2 mobile, D0–D1 desktop) + 7 HITL gate.

Felsefe: **markdown bilgiyi söyler, runtime kuralı zorlar**. LLM "atlamak" istese bile state machine, deterministic tier scorer ve DAG validator engeller.

Detaylı spec: **[Ortim_Architecture.md](./Ortim_Architecture.md)**

CLI komutu: `ortim` (canonical) — `ai-factory` alias geriye uyumluluk için korunur.

## Status: v0.6d

| Bileşen | Durum |
|---|---|
| State machine + project lifecycle | OK |
| CLI (`new` / `run` / `execute` / `run-all` / `status` / `tasks` / `budget` / `score-tier` / `advance` / `states` / `list-projects`) | OK |
| Babel — TR brief → structured intent + TR round-trip | OK |
| Memory loader — L1 principles, glossary, templates, agent prompts | OK |
| Analyst agent — intent → PRD | OK |
| Architect agent — PRD → GoldenPathInputs → tier (deterministic) → RFC | OK |
| Orchestrator agent — RFC → TaskDAG (cycle/dep validation, max 3 retry) | OK |
| Golden Paths scorer — T0–T6, T4 default, blocker-aware | OK |
| Worker (source code + sandbox whitelist) + Code Reviewer + status sidecar | OK (v0.5b) |
| Git branch isolation (`task/<id>` + merge/abandon, opt-out via env) | OK (v0.5b) |
| Test runner (`AI_FACTORY_TEST_CMD`, opt-in, blocks reviewer approval on failure) | OK (v0.5b) |
| `run-all` DAG batch executor (sequential per batch) | OK (v0.5b) |
| LLM client (Anthropic), Budget tracker, file lock | OK |
| Audit JSONL — append-only + thread-safe write lock | OK (v0.5c) |
| Paralel batch executor — `--parallel` + `ThreadPoolExecutor` + `git worktree` | OK (v0.5c) |
| Workspace exec lock + serileştirilmiş merge/status save | OK (v0.5c) |
| Batch-level audit metrikleri (wall/sum süre, speedup, merge wait) | OK (v0.5c) |
| Multi-LLM provider abstraction — Anthropic + DeepSeek (Anthropic-uyumlu API) | OK (v0.6a) |
| Per-role model atama (`BABEL_PROVIDER`, `ARCHITECT_PROVIDER`, vb.) | OK (v0.6a) |
| Per-provider audit/budget — `ortim budget --by-provider` | OK (v0.6a) |
| Security Reviewer + Test Strategist (hard veto) + Perf Reviewer (soft) | OK (v0.6b) |
| `AI_FACTORY_HARD_REVIEWERS=on` reviewer chain — task → AWAITING_HITL on hard veto | OK (v0.6b) |
| HITL G3 (schema), G6 (deploy), G7 (budget) — yeni project state'ler | OK (v0.6c) |
| Gate detector'lar (schema/external/security/budget) + `ortim gates <id>` | OK (v0.6c) |
| Hooks framework — `pre_commit` (lint/format) + `pre_deploy` | OK (v0.6c) |
| RFC template §11–§16 (deployment, observability, security, tests, DR, runbook) | OK (v0.6d) |
| 6 yeni tier doc (T0/T1/T2/T3/T5/T6) — daha önce sadece T4 detaylıydı | OK (v0.6d) |
| Drift detector + GC + migration agent | İter 7+ |

`Ortim_Architecture.md § 9` v0.1 zamanından kalma, güncellenecek.

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
| `ortim new <brief> --name <ad>` | Yeni proje aç |
| `ortim run <id> [--step babel\|analyst\|architect\|orchestrator\|auto]` | Mevcut state'e göre uygun ajanı koştur |
| `ortim status <id>` | Proje detayı + history |
| `ortim list-projects` | Tüm projeler |
| `ortim tasks <id>` | TaskDAG + paralel batch'ler |
| `ortim execute <id> <task-id> [--max-attempts N]` | Tek task'ı Worker → tests → Reviewer pipeline'ından geçir |
| `ortim run-all <id> [--max-attempts N] [--continue-on-fail] [--parallel] [--max-workers N]` | DAG'ı topolojik batch'lerde koştur (default sıralı; `--parallel` ile worktree'li thread pool) |
| `ortim budget [<id>]` | Token + USD raporu (audit log üzerinden) |
| `ortim states` | Tüm state'ler ve izinli geçişler |
| `ortim advance <id> <target> [--note]` | Manuel state ilerletme (HITL onayları + acil durum) |
| `ortim score-tier [...]` | Verilen input'larla tier seçim algoritmasını koştur (API key gerekmez) |

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

### İter 7 — Drift detector + GC + Migration agent
- Periyodik kod ↔ RFC karşılaştırması
- Dead code / stale flag sweep
- Schema migration özel ajanı

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

İter 5a + 5b + 5c tamamlandı. Uçtan uca akış (Babel → PRD → RFC → DAG → Worker → tests → Reviewer → git merge) artık paralel batch'lerde koşuyor; bağımsız task'lar `git worktree` ile izole, merge ve status save serileşmiş, audit thread-safe. Sıradaki: İter 6 — multi-reviewer (Security/Test/Perf hard veto) + hooks + HITL G3–G7.
