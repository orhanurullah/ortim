# Ortim — Master Specification

> **License:** FSL-1.1-Apache-2.0 (core). See LICENSE.
> **Status:** v0.6d — Babel + Analyst + Architect + Orchestrator + Worker + Reviewer chain + Hooks + Budget tracking. M1 (Brownfield + Mobile) in active development.

## 1. Vizyon

Ortim, yapay zeka destekli yazılım geliştirmedeki **5 kronik sorunu** çözer:

1. **Mükerrer iş** — aynı kod silinip tekrar yazılır
2. **Sonsuz hata döngüleri** — düzeltme yeni hata yaratır
3. **Token israfı** — özellikle İngilizce dışı dillerde
4. **Over-engineering** — gereksiz mikroservis ve soyutlama
5. **Onay yorgunluğu** — yanlış anlaşılan onaylar gereksiz iş yaratır

Çözüm: dokümantasyon-driven, deterministic, çok-ajanlı bir orchestrator. Felsefe: **markdown bilgiyi söyler, runtime kuralı zorlar**.

## 2. Mimari Genel Bakış

```
[Kullanıcı (TR)]
      ↓
[1. BABEL]          TR→EN intent extraction + glossary
      ↓
[2. MEMORY]         L1 principles + L2 RAG + L3 episodic
      ↓
[3. ARCHITECTURE]   Golden Paths decision matrix (T0–T6 web, M0–M2 mobile, D0–D1 desktop)
      ↓
[4. ORCHESTRATION]  State machine: PRD → RFC → Tasks
      ↓
[5. EXECUTION]      Worker agents (Git branch izole)
      ↓
[6. QUALITY]        Code + Security + Test + Perf reviewers (paralel)
      ↓
[7. GOVERNANCE]     Budget + Audit (PII redacted, hash-chained) + HITL gates
      ↓
[Production]
```

## 3. Katmanlar

### 3.1 Babel (Intent Capture)
- Konum: `ortim/babel/`
- Sözlük: `ortim/_assets/glossary/`
- Görev: Türkçe serbest metin → structured English JSON intent
- Round-trip validation: TR → EN → TR geri çevrim kullanıcıya gösterilir
- Çıktı: `workspaces/{tenant}/{id}/intent.json`

### 3.2 Memory (3-Tier Knowledge)
- **L1 Immutable Principles** — `ortim/_assets/principles/` — her promptta yüklenir (≤500 satır cap)
- **L2 Curated Patterns** — `ortim/_assets/golden-paths/`, `ortim/_assets/skills/` — RAG ile retrieve
- **L3 Episodic Memory** — `docs/adr/` — her PR sonrası yazılır (Reviewer üretir)
- Çakışma önceliği: L1 > L2 > L3
- Konum: `ortim/memory/`

### 3.3 Architecture (Golden Paths)
- Web tier'ları: T0 (static page) → T6 (event-driven/CQRS), default T4
- Mobile tier'ları (M1): M0 (native) / M1 (Flutter, RN — default) / M2 (PWA wrapper)
- Desktop tier'ları (M1): D0 (native) / D1 (Tauri, Electron — default)
- Decision matrix: scale, team size, compliance (KVKK/GDPR/HIPAA), latency SLO, budget
- Compliance overlay: KVKK seçilirse data residency + audit log + RTBF gereksinimleri otomatik inject
- Konum: `ortim/_assets/golden-paths/`

### 3.4 Orchestration (State Machine)
- States: INTAKE → BABEL_PROCESSING → PRD_DRAFTING → PRD_AWAITING_APPROVAL → PRD_APPROVED → RFC_DRAFTING → RFC_AWAITING_APPROVAL → RFC_APPROVED → TASKS_GENERATING → TASKS_READY → EXECUTING → DONE / FAILED / PAUSED
- Transitions explicit ve validate edilir — LLM "atlama" yapamaz
- Persistent state: `workspaces/{tenant}/{id}/state.json`
- Konum: `ortim/orchestrator/`

### 3.5 Execution (Workers)
- Worker ajan tek atomic task çalıştırır
- Git branch izolasyonu: `task/{task-id}`
- Adaptive retry: complexity'e göre (default 3, kompleks task'larda 5)
- Concurrency: file-level lock, task DAG paralelize (worktree mode)
- Sandbox: structural — extension whitelist (app_class'a göre conditional), path scope, symlink resolution
- Konum: `ortim/executor/`

### 3.6 Quality (Multi-Reviewer)
4 paralel reviewer her PR için:

| Reviewer | Kontrol | Veto |
|----------|---------|------|
| Code | RFC compliance, style, structure | Soft |
| Security | OWASP Top 10, secrets, CVE | **Hard** |
| Test | Coverage, mutation, contract | **Hard** |
| Performance | Bundle, query plan, infra cost | Soft (HITL escalation) |

### 3.7 Governance
- Token budget per task + per project
- Cost tracker: her LLM çağrısı log'a düşer
- HITL gates (7 nokta, § 8)
- Audit trail: structured JSONL log per decision, **PII redacted by default**, **hash-chained** (tamper-evidence)

## 4. Agent Roster

| Ajan | Sorumluluk | Scope | Boundary |
|------|-----------|-------|----------|
| **Analyst** | PRD üretimi | İhtiyaç çıkarma | Teknik karar veremez |
| **Architect** | RFC + Golden Path seçimi | Mimari | Implementation yazmaz |
| **Orchestrator** | Task graph + DAG | Yönetim | Kod yazmaz |
| **Worker** | Tek atomic task | Implementation | Scope dışına çıkamaz |
| **Code Reviewer** | RFC compliance | Review | Kod yazamaz |
| **Security Reviewer** | OWASP, secrets, CVE | **Veto** | Diğer reviewer'ları override eder |
| **Test Strategist** | TDD, contract, mutation | **Veto** | Test eksikse merge yok |
| **Perf Reviewer** | Bundle, query, cost | Soft veto | Cost gate tetikler |
| **Spec Custodian** | OpenAPI/SDL koruyucu | Sole-writer | Spec dosyalarına yalnız o yazar |
| **Migration Agent** | Schema değişiklikleri | Spesifik | Sadece migration tasklarında |
| **Drift Detector** | Kod ↔ RFC sapma | Periyodik | Notify-only |
| **Garbage Collector** | Dead code, stale flags | Sweep | PR oluşturur, otomatik merge yok |

## 5. Workflow

```
1. Kullanıcı Türkçe fikir verir (veya `--from-existing` ile mevcut codebase)
2. Babel → intent.json (round-trip validation)  [brownfield modda skip]
3. Analyst → PRD.md (eksik alanları sorar)
4. [HITL Gate G1] PRD onayı
5. Architect → Golden Path seçimi + RFC.md (codebase summary varsa onu temel alır)
6. [HITL Gate G2] RFC onayı
7. Orchestrator → tasks/*.md (DAG)
8. Per task:
   a. Worker branch açar
   b. Worker implement eder (related_files inject edilir M1 sonrası)
   c. 4 Reviewer paralel kontrol
   d. Veto yoksa merge
   e. Veto varsa: max retry → kota dolarsa HITL
9. Baseline regression check (brownfield) — passing test sayısı düşmemeli
10. Drift Detector periyodik sweep
11. Done
```

## 6. Reading Order

**Yeni insan katkıcı:**
1. Bu dosya (Ortim_Architecture.md)
2. `README.md` — kurulum
3. `LICENSE` — FSL-1.1-Apache-2.0 koşulları
4. `ortim/_assets/principles/core.md` — L1 kurallar
5. `ortim/_assets/golden-paths/T4-modular-monolith.md` — default web tier
6. `ortim/_assets/golden-paths/M1-flutter-rn.md` — default mobile tier (M1 sonrası)
7. `ortim/_assets/agents/*.md` — ajan promptları
8. `docs/backlog.md` — açık iş kalemleri

**Runtime başlatma:**
1. `ortim/main.py` — CLI entry
2. `ortim/orchestrator/state_machine.py` — flow tanımı
3. `ortim/orchestrator/project.py` — lifecycle

## 7. Immutable Principles (özet)

Detay: `ortim/_assets/principles/core.md`

- Always use Dependency Injection
- Ports & Adapters for external services
- No secrets in code (env vars only)
- Feature flags for new modules
- One module = one schema (no cross-module DB writes)
- TDD for any logic; spec-first for APIs
- Branch isolation per task
- Explicit error handling **only** at system boundaries

## 8. HITL Gate Definitions

| Gate | Trigger | Bypass |
|------|---------|--------|
| G1 — PRD | PRD draft tamam | Asla bypass yok |
| G2 — RFC | RFC + Golden Path tamam | Asla bypass yok |
| G3 — Schema | Migration task | Asla bypass yok |
| G4 — External | Yeni paid integration | Asla bypass yok |
| G5 — Security | PII / auth / payment kodu | Asla bypass yok |
| G6 — Deploy | Production push | Asla bypass yok |
| G7 — Budget | Token / cost cap aşımı | Override mümkün, log'a düşer |

## 9. Open core boundary

- **Core (FSL-1.1-Apache-2.0):** ortim/ (kod + `_assets/`), docs/, tests/, scripts/, fixtures/, repo root.
- **Enterprise (Commercial):** enterprise/ — multi-tenant orchestrator, SSO, off-site audit retention, SLA support.
- **Boundary rule:** Audit log'tan derive edilebilen her şey core. Tenant'lar arası paylaşılan altyapı gerektiren her şey enterprise.

## 10. Anti-Patterns (KAÇINILACAKLAR)

1. **Tüm tier'ları aynı anda kurma** — T4 ile başla, gerçek talep gelince diğerlerini ekle
2. **5+ ajanı aynı anda devreye alma** — 2 ile başla (Worker + Code Reviewer)
3. **Markdown'ı sistem sanma** — runtime olmadan markdown sadece nottur
4. **G1–G6 onaylarını bypass etme** — absolute, override yok
5. **Ortim'i kendi içinde mikroservis yapma** — modular monolith
6. **Prompt'ı kullanıcıdan sterilize etmeden işleme alma** — prompt injection riski
7. **Determinism'i unutma** — kod task'larında temperature=0
8. **PII'yi audit log'a ham yazma** — `redact_pii=True` default; raw mode sadece debug
