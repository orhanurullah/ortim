# Ortim 2026 Q2 Roadmap — v0.8 → v1.0 ekip-grade

> **Amaç.** v0.8 ("ileri seviye prototip with surprising production-grade observability") seviyesinden ekip-grade üretim aracına geçiş için yapısal yol haritası. Kaynak: [`../../ai-factory/16-05-2026_app-state.md`](../../16-05-2026_app-state.md) (senior engineer self-audit, 6 başlık).
>
> **Plan tipi.** Faz-bazlı, ardışık. Her faz "ship + ölç + sonraki fazı doğrula" döngüsüyle ilerler. Erken fazda yapılan keşif sonraki fazın kapsamını değiştirebilir.
>
> **Kanonik konum.** Açık iş kalemleri [`../backlog.md`](../backlog.md)'da; bu dosya **stratejik sıralama** ve **faz kapısı** kararlarını saklar.
>
> **Son güncelleme:** 2026-05-16 (Faz 2.4 — Skill authoring guide + 2 community skills ✅ shipped; pytest 547 → 556, zero regression)

---

## Kilit kararlar (locked)

### SQ-4 — Hedef segment
**Karar:** B = **Startup / küçük ekip** (PRD-driven planlama yapan, AI-assisted dev tool arayan 2-10 kişilik ekipler).

**Sebep:** Ekip-grade gap'lerin (%70'i) kapanması solo kullanıcıyı da ödüllendiriyor (tutorial, recovery cookbook, proof-point breadth solo'ya da yarar). Tersi geçerli değil — solo-odaklı plan team gap'i kapatmıyor.

**Reddedilenler:**
- **A (indie/solo)**: solo gelir "ücretsiz" üstüne, ayrıca SQ-4=A için ayrı yatırım gereksiz.
- **C (ikisi paralel)**: efor 2 katına çıkar, dağılır. Bir seçim disiplini lazım.

**Ne zaman tekrar değerlendir:** Faz 1 sonunda proof-point breadth bir hedef segmenti (agency / fintech / sağlık / saas startup) öne çıkardığında SQ-4'ü daraltıp tekrar locked.

### Sıralama prensibi
**Karar:** MVP scope locking (#1) → proof-point breadth (#2) sırası.

**Sebep:** MVP scope olmadan yeni tier × stack proof-point'leri eski şablonu çoğaltır; scope locking eklendikten sonra her yeni proof-point hem stack hem phase planning'i sınar.

---

## Faz Özeti

| Faz | Tema | Süre | Efor | Çıktı |
|---|---|---|---|---|
| **Faz 1** | Adoption blocker'ları (P0) | ~4 hafta | ~40-50h | Ekip-trial edilebilir v0.9 |
| **Faz 2** | Differentiation (P1) | ~2 hafta | ~20-25h | Marketable v0.9.5 |
| **Faz 3** | Distribution & Ops (P2) | ~3 hafta | ~25-30h | PyPI-shipped v1.0 |
| **Faz 4** | Ertelenenler | Q3-Q4 2026 | — | Yeniden değerlendir |

**Toplam Q2 efor:** ~85-105h. Haftalık 10-15h tempoda 8-11 hafta.

---

## Faz 1 — Adoption Blocker'ları (P0)

**Hedef:** "İlk müşteri ekibine önerebilir miyim?" sorusuna **evet** demek.

**Başarı kriteri (faz çıkışı):**
- 5+ farklı tier × stack proof-point arşivlenmiş (her biri DONE + audit log temiz)
- Yeni kullanıcı 15-dk tutorial sonrası `ortim demo`'yu kendi başına anlayabiliyor
- MVP scope locking ile bir 12+ task'lık proje phase 1/2 ayrımıyla planlanmış
- AWAITING_HITL'e takılan kullanıcı cookbook ile unblock olabiliyor

| # | İş | Kaynak | Efor | Bağımlılık | Durum |
|---|---|---|---|---|---|
| 1.1 | PRD-MVP scope locking | §4 | ~15h | — | ✅ **shipped 2026-05-16** |
| 1.2 | 5-10 proof-point × tier/stack | §6 P0-1 | ~10h | 1.1 |  ✅ **shipped 2026-05-16** (6 yeni stack + 3 structural fix) |
| 1.3 | Onboarding tutorial (15-dk walkthrough) | §6 Day-1 | ~6h | — (paralel) | ✅ **shipped 2026-05-16** ([`docs/tutorial/getting-started.md`](../tutorial/getting-started.md), 457 satır) |
| 1.4 | Failure recovery cookbook | §6 P0-5 | ~4h | — (paralel) | ✅ **shipped 2026-05-16** ([`docs/runbook/failure-recovery.md`](../runbook/failure-recovery.md), 402 satır, 9 senaryo) |
| 1.5 | Worker security gate (auth/PII/payment HITL) | §6 P0-3 | ~6h | — (paralel) | ✅ **shipped 2026-05-16** (TaskSpec.sensitive_categories + deterministic detector + runner gate + --human-reviewed flag + 3 review-checklist skill, pytest 521→534, smoke `a275c03953ec` 12/16 task tagged) |

### 1.1 PRD-MVP scope locking detayı ✅ shipped

Kararlar (locked):
- **Priority binary** (`must` / `later`) — MoSCoW tam ölçek Faz 2'ye ertelendi.
- **MVP_SCOPE_LOCKING G1 öncesi** — PRD_DIALOG/PRD_DRAFTING → MVP_SCOPE_LOCKING → PRD_AWAITING_APPROVAL.

Ship edilenler:
1. ✅ `runtime/scope/{__init__,schema}.py` — `ScopeManifest`, `ScopedFeature`, `suggest_initial_scope` + save/load
2. ✅ `runtime/orchestrator/state_machine.py` — `MVP_SCOPE_LOCKING` state + transitions
3. ✅ `runtime/main.py:scope` — `ortim scope <id>` (interactive + `--set` headless + `--lock` + `--reset` + `--show`)
4. ✅ `runtime/agents/architect.py` + `agents/architect.md` — scope block enjekte edilir, RFC §7 iki-katmanlı tablo Hard Rule
5. ✅ `runtime/agents/orchestrator.py` + `agents/orchestrator.md` Hard Rule 14 — TaskSpec.phase emit zorunlu (scope varsa)
6. ✅ `runtime/orchestrator/task_dag.py` — `TaskSpec.phase: int = 1` + validator; `ortim run-all --phase N` filter
7. ✅ Testler — `tests/test_scope_manifest.py` (10), `tests/test_scope_cli.py` (4), `tests/test_task_dag_phase.py` (5), + state machine yeni testler. **Toplam +20 test, pytest 476 → 496.**

Ek not — show komutu `--artifact scope` desteği aldı (`ortim show <id> --artifact scope`).

Yan etki / breaking change: PRD_DIALOG → PRD_AWAITING_APPROVAL direct transition'ı kaldırıldı. Pre-1.1 workspace'leri PRD_AWAITING_APPROVAL'da takılmazsa fark hissetmez; PRD_DIALOG'da bekleyen workspace'ler bir kere `ortim lock` çağrısında MVP_SCOPE_LOCKING'e düşer ve `ortim scope <id>` ile devam eder.

### 1.2 Proof-point matrisi

Mevcut: T0 Python CLI (aa9d4227233d), T2 Node CLI (b8d60b6f5791), T4 React+Vite (proofpoint48), T4 React extend (1b9c9f9ca18b).

Eklenecek (Faz 1 hedef):
- **T3** Node + Express + Postgres (serverless veya containerized)
- **T3** Python + FastAPI + SQLite
- **T4** Spring Boot + Postgres (Kotlin önerilir — kaynak §6'da SQ-4=B reference stack)
- **T4** Go + Gin + Postgres
- **M1** Flutter mobile (basit todo veya not app)
- **D1** Tauri cross-desktop (opsiyonel, M1 başarılıysa)

Her biri ~1h + ~$0.02 spend; toplam ~10h + ~$0.15-0.20.

**Önemli:** Her yeni proof-point'te MVP scope locking (1.1) kullanıldığında "Phase 1 only" run yapıp gözlem topla — `--phase 1` flag'inin gerçek değeri burada ortaya çıkar veya çıkmaz.

### 1.3 Tutorial içeriği

`docs/tutorial/getting-started.md` veya benzeri tek-dosya walkthrough:

1. `.env` setup (DEEPSEEK_API_KEY nasıl alınır, neden ANTHROPIC opsiyonel)
2. `ortim doctor` — required vs recommended check'lerin anlamı
3. `ortim demo` walkthrough — workspace'te ne yaratılır (PRD/RFC/DAG/intent), bunlar ne işe yarar
4. İlk gerçek proje: `ortim new` → brief gir → G1/G2 review → `run-all` → DONE'a kadar
5. Trust calibration: "AI yazdı, ben imzalıyorum" — kullanıcı her gate'te ne arayacak
6. Common pitfall: stack mismatch, AWAITING_HITL, cost spike

15 dakikada okunur, ~600-800 satır markdown. Video opsiyonel (Faz 3'te yapılabilir).

### 1.4 Failure recovery cookbook

`docs/runbook/failure-recovery.md`:
- "Task AWAITING_HITL'e takıldı, ne yaparım?" — reviewer reason'larını okuma, manual edit, `advance` ile reset
- "Worker 3 deneme sonra başarısız oldu" — prior_reasons sınıflandırma (sandbox/criteria/test_infra)
- "Cost cap'e takıldım, devam edemiyorum" — G7 budget reset
- "Eski workspace state.json incompatible" — migration manuel adımları (Faz 3'te otomatik)
- "Yanlış stack seçildi" — `ortim refine` veya workspace reset

### 1.5 Worker security gate detayı

SecurityReviewer hâlihazırda var ama hard veto coverage'ı dar. Eklenecek:
- Auth/login/session task'larında `requires_human_review: true` flag
- Payment/billing task'larında aynı
- PII handling (email/phone/address) task'larında aynı
- Hard veto pattern catalog: skill olarak `skills/security/auth-review-checklist.md`, `skills/security/pii-review-checklist.md`

Bu Reviewer mutation testing'in (Faz 2) ön-fixture'ı; mutation testing bu hard veto'ları sınar.

---

## Faz 2 — Differentiation (P1)

**Hedef:** "Ortim'i Cursor/Aider/Copilot Workspace'e tercih edilebilir kılan unique angle'ları ship et."

**Başarı kriteri (faz çıkışı):**
- "AI dev tool you can run fully local" iddiası geçerli (Babel + Worker Ollama'da çalışıyor)
- T4-T5 projeleri için Docker skill'i otomatik tetikleniyor, false-positive yok
- Reviewer mutation testing %X catch rate ile ölçüldü (target ≥70%)
- 2+ community skill repo'da, skill yazma rehberi shipped

| # | İş | Kaynak | Efor | Bağımlılık | Durum |
|---|---|---|---|---|---|
| 2.1 | Docker skills (node/python/compose) | §2 | ~5h | 1.5 (skill pattern) | ✅ shipped |
| 2.2 | Local LLM provider (Ollama/LM Studio) | §3 | ~7h | — | ⬜ todo |
| 2.3 | Reviewer mutation testing | §6 P1-7 | ~6h | 1.5 | ⬜ todo |
| 2.4 | Skill yazma rehberi + 2 community skill | §5 dok | ~4h | 2.1 | ✅ shipped |

### 2.1 Docker skills

3 concrete skill:
1. `skills/deploy/dockerfile-node.md` — Node 20-alpine, multi-stage, npm ci, non-root
2. `skills/deploy/dockerfile-python.md` — Python 3.12-slim, uv veya pip, non-root
3. `skills/deploy/docker-compose-microservices.md` — T5+ template

Trigger config (frontmatter):
```yaml
triggers:
  keywords: [deploy, deployment, production, containerize, docker, ship]
  tier: [T4, T5, T6]
  app_class: [web]
  keywords_blocklist: [no docker, without docker, lokal kalsin]
```

Default-on değil — sadece brief'te trigger varsa Worker'a inject.

### 2.2 Local LLM detayı

§3'teki tahmin (6-8h) — yapılacaklar:
- `runtime/llm/providers.py` Ollama provider entry + `OLLAMA_BASE_URL` env (~2h)
- Pricing entry (cost=0), per-role routing dokümante (~1h)
- `docs/local-llm.md` — quality-tier matrix, model size guide, hibrit pattern örnekleri (~1h)
- 3 yeni test (provider abstraction, env fallback, hata mesajları) (~2h)
- 1 live proof-point Qwen-Coder ile (T0 Python CLI brief) (~1-2h)

**Çerçeveleme zorunlu (legal/marketing):** "Babel + Worker local; Architect + Reviewer cloud önerilir" — KVKK uyumluluk vaadi YALANSIZ.

### 2.3 Reviewer mutation testing

`tests/mutation/` altında reviewer'a verilen task output'una bilinen bug enjekte et, catch oranını ölç. Mutation tipleri:
- Off-by-one (loop boundary)
- Null/undefined check kaldır
- Auth bypass (return true)
- SQL injection vulnerability
- Missing await
- Wrong operator (`&&` → `||`)

Target: %70+ catch. %50'nin altındaysa Reviewer prompt'unu sertleştir.

### 2.4 Skill yazma rehberi

`docs/skills/authoring-guide.md`:
- Skill anatomy (frontmatter, triggers, body)
- Resolver semantics (keyword + tier + app_class)
- 2-3 örnek skill (kolay/orta/zor)
- Test pattern: `tests/test_skill_<name>.py` ile resolver coverage

---

## Faz 3 — Distribution & Ops (P2)

**Hedef:** "Ortim keşfedilebilir + yeni gelen kullanıcı 30 gün sonra hâlâ kullanıyor."

**Başarı kriteri (faz çıkışı):**
- `pip install ortim` çalışıyor
- Landing page + demo gif + 1 blog post live
- Workspace cleanup + archive komutları
- Pydantic schema migration discipline (M1.5 öncesi state.json'lar M3.1 sonrası çalışıyor)
- Brand consistency (ortim ↔ ai-factory)

| # | İş | Kaynak | Efor | Bağımlılık | Durum |
|---|---|---|---|---|---|
| 3.1 | PyPI publish + brand consistency | §1 + §5 | ~6h | — | ⬜ todo |
| 3.2 | Pydantic schema migration | §5 ops | ~4h | 1.1 (phase field add) | ⬜ todo |
| 3.3 | `ortim archive` / `ortim cleanup` | §6 Day-30 | ~3h | — | ⬜ todo |
| 3.4 | Landing page + demo gif + 1 blog post | §5 marketing | ~8h | 3.1 (ship-ready) | ⬜ todo |
| 3.5 | Compliance one-pager (KVKK/GDPR) | §6 P1-9 | ~4h | 2.2 (local LLM) | ⬜ todo |

### 3.1 PyPI publish

- `name="ortim"` PyPI'da reserve mi? — kontrol et (SQ-1'in cevabı)
- `pyproject.toml` build target review
- `ai-factory` → `ortim` rename veya package rename
- README'de brand consistency: tüm "ai-factory" geçişlerini "ortim" yap, repo URL'i karar (repo adı `ai-factory` kalabilir, package `ortim`)
- `docker/Dockerfile.draft` (Faz 4 ipliği) — repo'da untracked dursun

### 3.4 Marketing minimum

- `ortim.dev` veya `ortim.io` domain (kontrol edilmeli — SQ-3 cevabı)
- Landing page (basit, tek sayfa): pitch + 30sn demo gif + install komutu + GitHub link
- 1 blog post: "Why we built Ortim — deterministic state machine for AI dev" (1500-2000 kelime)
- `asciinema` veya GIF ile 30sn demo

---

## Faz 4 — Ertelenenler (Q3-Q4 2026 değerlendirmesi)

Bu kalemler Q2 planına **dahil değil**. Faz 1-3 ship sonrası tekrar değerlendir.

| Kalem | Kaynak | Neden ertelendi |
|---|---|---|
| Ortim'in kendisi için Docker imajı | §1 | PyPI publish + tutorial Day-1'i kapsadıktan sonra %20 segment için anlamlı. |
| Web UI dashboard (read-only retro/drift/state) | §6 P2-11 | Önce CLI UX olgunlaşmalı; dashboard kaynak çekiyor. |
| VS Code extension | §6 P2-13 | Editor entegrasyonu için CLI contract'ı stabilize olmalı (Faz 3 sonrası). |
| Multi-tenant deployment (`enterprise/` doldurma) | §6 P2-12 | Önce SQ-2 (enterprise gelir timeline) cevaplanmalı. |
| Ortim hosted (PaaS variant) | §6 P2-14 | Sermaye + ekip gerektirir; tek-kişi tasarımı (§5) sınırı. |
| Multi-environment (dev/staging/prod) | §5 ops | Müşteri talebi gelmedikçe template yapmak — gereksiz. |

---

## Sürekli kalemler (faz-bağımsız)

Bunlar her faz boyunca arka planda işler:

1. **Surveillance items** (backlog DEFERRED): G-1 (M4 export visibility vs barrel-only), G-2 (`test_infrastructure_unavailable` üçüncü mod adayı), Item 45 (IntentAnalyst non-determinism). Her proof-point sonrası tetiklenip tetiklenmediği kontrol edilir; 2 occurrence = OPEN'a promote.
2. **Real-LLM E2E test snapshots**: Her ship sonrası `tests/e2e/fixtures/` güncellenir (DeepSeek ve Anthropic için ayrı, Faz 2 sonrası Ollama için de).
3. **`tespit.md` + `docs/backlog.md` sync**: Her ship + her keşif aynı edit'te iki dosyaya da yazılır (canonical sync protocol).
4. **Tek-kişi tasarımı riski (§5)**: Faz 2 sonunda 1-2 günlük dış code review (paid veya OSS contributor outreach). Yapısal adım değil, strategik.

---

## Karar günlüğü (decision log)

Plan değişiklikleri buraya append-only yazılır.

| Tarih | Karar | Sebep |
|---|---|---|
| 2026-05-16 | Plan v1 oluşturuldu | `16-05-2026_app-state.md` self-audit sonucu, SQ-4=B kilitlendi |
| 2026-05-16 | Faz 1.1 (PRD-MVP scope locking) shipped | 7 sub-task tamamlandı, pytest 476→496, zero regression. Real-LLM proof-point Faz 1.2 ile gelecek. |
| 2026-05-16 | Faz 1.1 smoke test (workspace `b17c24070d44`) | TR todo brief, $0.0099. Architect §7 iki-katmanlı tablo ✅, Orchestrator phase emit ✅, Phase 2 features deferred ✅. Validated end-to-end. |
| 2026-05-16 | Faz 1.2 proof-point #1 — Python FastAPI backend (workspace `bf761fff02b0`) | Tier scorer **T2/BaaS** verdi (Python backend brief'i için 4. BaaS-drift evidence). Architect Supabase substitute etti — kullanıcı "SQLite" dedi, ezildi. **B-2 OPEN P0**. Faz 1.1 zinciri yine yeşil. |
| 2026-05-16 | **B-2 fix shipped** — user_stack_hints via Babel | `StructuredIntent.user_stack_hints` field eklendi, Babel prompt verbatim-capture, Architect dialog-off path hint-block enjekte ediyor. +5 test, pytest 496→501. Re-smoke (workspace `e9d6f345629a`): Architect §4 = `Python (user-named)` + `SQLite (user-named)` + FastAPI (T2 default), §1 Trade-offs'ta tier mismatch surface edildi. **B-2 CLOSED.** |
| 2026-05-16 | Faz 1.2 proof-point #2 — Node+Express+SQLite (workspace `470b59622901`) | Tier T2/BaaS (B-1 5. evidence). Architect §4 hepsi user-named, `better-sqlite3` driver gap-fill. 8 task DAG, hepsi phase 1. $0.0100. |
| 2026-05-16 | Faz 1.2 proof-point #3 — Flutter (workspace `45ed19809dec`) — **B-5 KEŞFEDİLDİ** | Tier scorer T2/BaaS verdi Flutter mobile brief'i için. Cause: legacy Analyst PRD'ye mobile/Flutter sinyalini geçirmiyor, Architect Call 1 LLM "web" default'una düşüyor. **B-5 OPEN P0**. |
| 2026-05-16 | **B-5 fix shipped** — app_class deterministic override | `runtime.babel.app_class_from_hints(hints) -> "mobile"\|"desktop"\|None` helper. main.py Architect Call 1 sonrası override (Flutter/Tauri/RN/Ionic/Capacitor/SwiftUI/Jetpack Compose/Electron/Wails). +10 test, pytest 501→511. Re-smoke (`1e292d942cd5`): Tier **M1**, RFC Dart+Flutter+Hive, §2 NEEDS-INPUT Hive/SharedPreferences çakışmasını surface etti, $0.0134. **B-5 CLOSED.** |
| 2026-05-16 | **B-1 fix shipped** — hint-aware tier scorer | `GoldenPathInputs.user_stack_hints` field, `_self_hosted_signal` classifier (SQLite/Postgres/MySQL/Mongo + FastAPI/Express/Spring/Gin/Rails/etc; BaaS providers Supabase/Firebase/Appwrite suppress), T2 blocker + T4 bonus. main.py Architect Call 1 sonrası hint'leri gp_inputs'a yazıyor. +10 test, pytest 511→521. Re-smoke Python (`2050c9291eb7`): Tier **T4 Modular Monolith**, §2 Rejected: *"T2 (BaaS — user wants local SQLite, not cloud)"*, $0.0095. **B-1 CLOSED.** |
| 2026-05-16 | Faz 1.2 proof-point #4 — Spring Boot + Kotlin + PostgreSQL (`10a6a36c5263`) | Tier T4 (score 105), §2 "T2 (BaaS — user named PostgreSQL, not BaaS)", Architect §4 hepsi user-named + Flyway gap-fill. 7 task DAG (Books/Members/Borrowing/Shared). 0 yeni gap. $0.0100. |
| 2026-05-16 | Faz 1.2 proof-point #5 — Tauri + React + SQLite (`b423faa79147`) | app_class override "desktop", Tier **D1**, Architect §1 "User-named stack aligns well with D1 (Tauri) tier. No substitution needed." Zustand+rusqlite gap-fill, hybrid frontend/backend modules. 6 task. 0 yeni gap. $0.0108. |
| 2026-05-16 | Faz 1.2 proof-point #6 — Go + Gin + SQLite (`5959b30d1946`) | Tier T4 (score 105), §2 "T2 (BaaS — user wants local Go)", §4 hepsi user-named. 8 task DAG. Go binary installed değildi ama planning chain bağımsız çalıştı. 0 yeni gap. $0.0095. |
| 2026-05-16 | **Faz 1.2 wrap** — proof-point breadth tamamlandı | Toplam 6 yeni proof-point (3 web backend T4, 1 mobile M1, 1 desktop D1, 1 web frontend T4 was pre-existing baseline). Tier dağılımı sağlıklı (no all-T2 cluster). 3 structural fix (B-1/B-2/B-5) shipped. Hint-aware sistem 3 katman: Babel capture → main.py app_class override → tier scorer hint-aware. Test 476→521 (+45). Toplam Faz 1.2 spend: ~$0.075. |
| 2026-05-16 | **Faz 1.3 shipped** — onboarding tutorial | `docs/tutorial/getting-started.md` (457 satır, 7 bölüm: kurulum/doctor/demo/gerçek-proje/trust-calibration/sorunlar/sonra). TR primary + EN CLI komutları. Konsept açıklaması + komut cheatsheet. |
| 2026-05-16 | **Faz 1.4 shipped** — failure recovery cookbook | `docs/runbook/failure-recovery.md` (402 satır, 9 senaryo: AWAITING_HITL/3-strike/G7/migration/stack-drift/sandbox/state-error/reset). Her senaryo için belirti+sebep+çözüm adımları. |
| 2026-05-16 | **Faz 1.5 shipped** — Worker security gate | `TaskSpec.sensitive_categories` (auth/pii/payment) + `runtime.security.sensitive_patterns` deterministic detector (regex word-boundary, KVKK/GDPR/HIPAA + Türkçe pattern'lar dahil) + runner gate (reviewer approval sonrası sensitive task → AWAITING_HITL) + `ortim execute --human-reviewed` bypass + 3 skill (`skills/security/{auth,pii,payment}-review-checklist.md`). +13 test, pytest 521→534. Smoke `a275c03953ec` (Stripe + JWT + email auth brief): 12/16 task isabetli tagged. Faz 1 P0 set complete. |

---

## Faz kapısı (gate) protokolü

Bir fazdan diğerine geçerken:

1. **Başarı kriterleri tek tek doğrulanır** (yukarıdaki "Başarı kriteri" bölümleri)
2. **Karar günlüğüne faz kapanış notu eklenir**: ne ship edildi, ne ertelendi, ne keşfedildi
3. **Sonraki faz öncesi yeniden değerlendirme**: önceki fazda keşfedilen yapısal bilgiler sonraki fazın kapsamını değiştirebilir; gerekirse plan amend edilir
4. **Faz çıkışında bir proof-point demo** — kullanıcı veya 1 dış göz "şu an ne ekledik" anlatımıyla validate eder

---

## Referanslar

- Kaynak self-audit: [`../../16-05-2026_app-state.md`](../../16-05-2026_app-state.md)
- Mimari spec: [`../../Ortim_Architecture.md`](../../Ortim_Architecture.md)
- Açık iş kalemi listesi: [`../backlog.md`](../backlog.md)
- Kronolojik keşif log'u: [`../../tespit.md`](../../tespit.md)
- L1 prensipler: [`../principles/core.md`](../principles/core.md)
