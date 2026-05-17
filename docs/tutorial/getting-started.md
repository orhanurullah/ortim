# Ortim — Başlangıç Rehberi

> İlk projeni 15 dakikada bitirmek için adım adım kılavuz. Yazılım geliştirici için yazılmıştır; terminal kullanımı + bir LLM API key'i + temel git bilgisi gerektirir.

Bu rehber:
- Ne **değil**: mimari spec (o [`Ortim_Architecture.md`](../../Ortim_Architecture.md)). Tüm CLI komutlarının referansı (o `ortim --help`).
- Ne **dir**: sıfırdan ilk projene kadar yapılacaklar listesi + neyin neden öyle çalıştığı.

İçindekiler:
1. [Kurulum + ortam](#1-kurulum--ortam)
2. [ortim doctor — sağlık kontrolü](#2-ortim-doctor--sağlık-kontrolü)
3. [İlk run — `ortim demo`](#3-i̇lk-run--ortim-demo)
4. [Gerçek proje — `ortim new`'dan DONE'a](#4-gerçek-proje--ortim-newdan-donea)
5. [Trust calibration — AI yazdı, ben imzalıyorum](#5-trust-calibration--ai-yazdı-ben-i̇mzalıyorum)
6. [Yaygın sorunlar + çözümleri](#6-yaygın-sorunlar--çözümleri)
7. [Buradan sonra nereye](#7-buradan-sonra-nereye)

---

## 1. Kurulum + ortam

### 1.1 Repo'yu klonla

```bash
git clone https://github.com/<owner>/ortim.git
cd ortim
python -m venv .venv
.venv/Scripts/activate            # Windows
# source .venv/bin/activate       # macOS/Linux
pip install -e .
```

`pip install -e .` editable mode'da kurar — repo dosyalarını değiştirdiğinde `ortim` komutu güncel kalır.

### 1.2 API key'ler — `.env` dosyası

Repo kökünde `.env.example` var. Kopyala:

```bash
cp .env.example .env
```

`.env` içine en az birini ekle:

```ini
# Tercih edilen — ucuz, hızlı, hepsi-DeepSeek routing'i çalışır
DEEPSEEK_API_KEY=sk-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx

# Opsiyonel — Architect/Reviewer kritik rolleri için "premium" model isteğin varsa
ANTHROPIC_API_KEY=sk-ant-xxxxxxxxxxxxxxxxxxxxxxxxxxxxx

# Opsiyonel — proje başına maliyet üst sınırı (USD)
AI_FACTORY_BUDGET_CAP_USD=2.00
```

**Neden ikisi de opsiyonel ama DEEPSEEK_API_KEY pratik gereklilik?**

Ortim **multi-provider** — her ajan rolü ayrı bir provider'a yönlendirilebilir. Hiç provider key'i yoksa LLM çağrısı yapan komutlar (`new`, `run`, `demo`, `run-all`, `extend`) çalışmaz; ama deterministic komutlar (`status`, `tasks`, `drift-check`, `score-tier`, `retro`) provider olmadan da çalışır.

Yalnız DeepSeek key'i ile sistem tamamen işler. Anthropic key'i eklersen kritik rolleri (Architect, SecurityReviewer) Anthropic'e yönlendirebilirsin (`.env`'de `ARCHITECT_PROVIDER=anthropic` gibi). Maliyet ~10× artar, kalite kısmi olarak artar — ekibin priority'sine göre seç.

**DeepSeek key'i nasıl alınır?** [platform.deepseek.com](https://platform.deepseek.com) → Sign up → API Keys → Create. İlk $5 free credit gelir; bir planning chain ~$0.01 olduğundan 500 proje free.

### 1.3 Workspace dizini

Default: `ortim/workspaces/`. Her proje bu dizin altında kendi UUID kısa-id'siyle bir alt-klasör olur. `.gitignore`'da olduğu için commit'lenmez (kendi projen içinde de aynı pattern'i takip et).

İstersen `.env`'de `AI_FACTORY_WORKSPACE_ROOT=/path/to/dir` ile değiştir.

---

## 2. ortim doctor — sağlık kontrolü

İlk komut, her zaman:

```bash
ortim doctor
```

Çıktıdan örnek (kısaltılmış):

```
Ortim doctor — Environment health check

┌────────────────────┬────────┬────────────────────────────────┐
│ Check              │ Status │ Detail                         │
├────────────────────┼────────┼────────────────────────────────┤
│ Python ≥ 3.11      │   OK   │ 3.14.0                         │
│ DEEPSEEK_API_KEY   │   OK   │ set (length 35)                │
│ ANTHROPIC_API_KEY  │  MISS  │ not set                        │
│ Node.js            │   OK   │ v24.11.1 (T1-T4 web)           │
│ npm                │   OK   │ 11.6.4                         │
│ Flutter            │   OK   │ Flutter 3.38.3                 │
│ Go                 │   --   │ not installed                  │
│ Skills directory   │   OK   │ 7 skill file(s)                │
└────────────────────┴────────┴────────────────────────────────┘

required: 5/5  recommended: 4/5  optional: 5/6
```

**Üç check sınıfı:**

- **required** (FAIL = sistem çalışmaz): Python sürümü, workspace yazma izni, L1 prensip dosyası, audit log dizini, agent prompt dosyaları.
- **recommended** (MISS = pratik olarak engelleyici): en az bir LLM API key, Git binary'si.
- **optional** (MISS = sadece o stack'i kullanan projeleri etkiler): Node, Flutter, Cargo, Go, JVM. Sadece o stack'te bir proje yapacaksan kur.

Bir check `MISS`/`FAIL` çıkarsa altta `Fix hints` bölümü neyi nasıl ekleyeceğini söyler.

---

## 3. İlk run — `ortim demo`

`ortim demo` — kullanıcı etkileşimi olmadan tüm planning chain'i sondan sona çalıştırır. Yeni gelene "sistem ne yapıyor" cevabını gösteren en hızlı yol.

```bash
ortim demo
```

Default brief İngilizce bir todo CLI'sı. Kendi brief'inle çalıştırmak için:

```bash
ortim demo --brief "Kucuk bir kisisel finans REST API'si yapmak istiyorum. JWT auth, gelir/gider CRUD, aylik ozet. Python + FastAPI + SQLite kullanalim. Tek kisi, lokal."
```

### 3.1 Demo ne yapıyor?

Şu zinciri otomatik koşturur:

```
Brief (TR)
  ↓ Babel (TR→EN structured intent)
intent.json
  ↓ Analyst (PRD draft)
PRD.md
  ↓ MVP_SCOPE_LOCKING (auto-lock for demo)
scope.json
  ↓ G1 — PRD approval (auto-approved in demo)
  ↓ Architect (RFC + tier selection)
RFC.md + golden_path_inputs.json
  ↓ G2 — RFC approval (auto-approved in demo)
  ↓ Orchestrator (DAG generation)
task_dag.json + tasks/T-001.md ... T-NNN.md
  → tasks_ready
```

Çıktının son satırında bir workspace ID görürsün, örn. `workspaces/2050c9291eb7`. Bu projeyi açıp dosyalara bak:

```bash
cd workspaces/2050c9291eb7
ls
# PRD.md  RFC.md  intent.json  scope.json  golden_path_inputs.json  state.json  task_dag.json  tasks/
```

### 3.2 Her artifact ne işe yarar?

| Dosya | Ne tutuyor | Kim üretti |
|---|---|---|
| `intent.json` | Brief'ten çıkarılan structured intent (goal, must_have, user_stack_hints) | Babel |
| `PRD.md` | İnsan-okunabilir ürün gereksinim dokümanı | Analyst |
| `scope.json` | Her feature'a phase + priority ataması | `ortim scope` (demo: auto) |
| `golden_path_inputs.json` | Tier scorer'ın girdileri (auth, scale, app_class…) | Architect Call 1 |
| `RFC.md` | Mimari karar dokümanı — tier, stack, modüller, riskler | Architect Call 2 |
| `task_dag.json` | Atomik iş paketleri DAG'ı | Orchestrator |
| `tasks/T-NNN.md` | Her task için Worker'ın okuyacağı brief | Orchestrator |
| `state.json` | Project state machine history | runtime |

`ortim show <id> --artifact prd|rfc|scope|intent|stack` ile herhangi birini konsola bas.

### 3.3 Maliyet kontrolü

```bash
ortim retro <workspace-id>
```

Token kullanımı + USD maliyet tablosu döner. Planning-only demo tipik ~$0.01 (DeepSeek). Architect Anthropic'teyse ~$0.05–0.10.

---

## 4. Gerçek proje — `ortim new`'dan DONE'a

Demo "izle, gör" içindir; gerçek proje açmak için `ortim new` kullan.

### 4.1 Proje aç

```bash
ortim new "Cool Project Adı" --brief "TR brief'in burada..."
```

Brief uzun olabilir. `--brief @path/to/brief.txt` ile dosyadan da okur.

Çıktıda **project_id** görürsün (12-karakter hex). Sonraki tüm komutlar bu id'yi alır.

```
Created project: 'Cool Project Adı'
  project_id: 7f3a2b9c1d4e
  state:      intake
  workspace:  workspaces/7f3a2b9c1d4e
```

### 4.2 Babel + planning'i çalıştır

```bash
ortim run 7f3a2b9c1d4e
```

`run` komutu state'e göre uygun ajanı çağırır. İlk çağrı Babel'i koşturur, intent.json üretir, PRD_DRAFTING state'ine geçer.

Default davranış: **dialog mode kapalı** ise `run` tek seferde Babel + Analyst'i ardışık koşturur ve seni MVP_SCOPE_LOCKING'e bırakır. Dialog mode (M2 conversational) açıksa state machine her dialog state'i ayrı ele alır — `ortim refine` + `ortim lock` ile ilerlersin.

### 4.3 Scope locking — Faz 1.1

PRD draftlanınca state `MVP_SCOPE_LOCKING` olur. `scope.json` otomatik seed olur (must_have→phase 1, nice_to_have→phase 2). Şimdi karar verme zamanı:

```bash
ortim scope 7f3a2b9c1d4e
```

İnteraktif tablo + her feature için phase atama prompt'u açılır. Default'u kabul etmek için Enter'a bas.

Headless (CI veya hızlı kullanım):

```bash
# Bir feature'ı Phase 2'ye taşı, scope'u kilitle, G1'e geç
ortim scope 7f3a2b9c1d4e --set "social login=2" --lock
```

`--set "<substring>=<phase>"` ile birden çok feature düzenlenebilir. `--lock` interactive prompt'u atlar ve PRD_AWAITING_APPROVAL'a geçer.

**Neden bu adım gerekli?** Architect Call 2 RFC §7 Module Breakdown'u **iki-katmanlı** üretir (Phase 1 MVP / Phase 2+ Deferred). Phase 2 olarak işaretlenen feature'lar için Orchestrator hiç task üretmez — onlar `ortim extend` ile sonraki sprint'e kalır.

### 4.4 G1 — PRD onayı

```bash
ortim show 7f3a2b9c1d4e --artifact prd
```

Oku. Her must_have feature beklenen şekilde yer alıyor mu? Non-goal'lar net mi? open_questions varsa cevaplaman gerekli mi?

Onayla:

```bash
ortim advance 7f3a2b9c1d4e prd_approved --note "reviewed"
```

PRD'de düzeltme istersen `ortim refine` (dialog mode açıksa) veya `ortim advance 7f3a2b9c1d4e prd_drafting` ile geri at, sonra PRD.md'yi elle düzenle veya `ortim run` ile tekrar üret.

### 4.5 Architect — RFC + tier

```bash
ortim run 7f3a2b9c1d4e
```

Architect Call 1 PRD'den `GoldenPathInputs` çıkarır. Eğer Babel `user_stack_hints` capture etmişse (örn. "Flutter", "SQLite"), main.py app_class ve tier scorer hint'lerini override eder (Faz 1.2 fix).

Sonra deterministic scorer tier'ı seçer, Architect Call 2 RFC.md drafter.

### 4.6 G2 — RFC onayı

```bash
ortim show 7f3a2b9c1d4e --artifact rfc
```

Bak:
- §2 **Selected Tier** doğru mu (T0–T6 web / M0–M2 mobile / D0–D1 desktop)?
- §4 **Tech Stack** brief'inde adlandırdığın araçları gösteriyor mu? "user-named" etiketi var mı?
- §7 **Module Breakdown** iki-katmanlı (Phase 1 | Phase 2+) mi?
- §9 **Risks** boş değil mi (en az 3 risk olmalı)?

Sorun varsa: `ortim advance 7f3a2b9c1d4e rfc_drafting` ile geri, RFC.md'yi elle düzenle. Sorun yoksa:

```bash
ortim advance 7f3a2b9c1d4e rfc_approved --note "reviewed"
```

### 4.7 Orchestrator — DAG generation

```bash
ortim run 7f3a2b9c1d4e
```

Orchestrator RFC'yi okur, atomik task'lar üretir. Validator'ler (cycle yok, missing dep yok, module_scope ∈ RFC §7, phase ∈ {1, 2+}) ihlali yakalarsa retry'la (max 3 kez).

```bash
ortim tasks 7f3a2b9c1d4e
```

Task listesi + dependency tablosu çıkar. Her task `tasks/T-NNN.md` dosyasında.

### 4.8 Worker — implementasyon

```bash
ortim run-all 7f3a2b9c1d4e --phase 1
```

`--phase 1` bayrağı sadece MVP task'larını koşturur (Phase 2+ PENDING kalır). Default sequential mode, her task git branch'inde isolation.

Worker her task için:
1. RFC + task brief + skill'leri okur
2. Kod yazar (FILE_BLOCK formatında WorkerOutput)
3. Sandbox structural validator geçer mi?
4. Test runner çalışır (`.ai-factory.env`'de tanımlı `AI_FACTORY_TEST_CMD`)
5. Reviewer chain (Code/Security/Test/Perf) verdict döner
6. APPROVED → DONE; REJECT → 3 retry'la kadar; AWAITING_HITL → durur

### 4.9 İlerleme izleme

```bash
ortim status 7f3a2b9c1d4e         # state + history
ortim drift-check 7f3a2b9c1d4e    # RFC ↔ DAG ↔ status integrity
ortim retro 7f3a2b9c1d4e          # cost + retry rate + HITL escalations
```

Her şey DONE'a indiyse `ortim run-all` README.md'yi de otomatik draft eder.

---

## 5. Trust calibration — AI yazdı, ben imzalıyorum

Ortim deterministic state machine + audit trail ile "AI ne yaptı" sorusunu cevaplar, ama **kararı sen verirsin**. Her gate'te şunu sor:

### G1 — PRD onayı
- Brief'inde olmayan feature PRD'de var mı? **Varsa reddet.** (Babel/Analyst hayali feature ekleyebilir; nadir ama olur.)
- open_questions cevaplanmadıysa devam etmemen lazım — Architect varsayım yapar.
- `inferred_compliance` (KVKK/GDPR) brief'ine uygun mu?

### G2 — RFC onayı
- Tier doğru mu? Self-audit: "küçük bir backend için T4 monolith mantıklı, T5 microservices değil."
- Stack senin adlandırdığın gibi mi? §4'te "user-named" etiketi varsa iyi sinyal.
- §9 Risks gerçek riskler mi yoksa boilerplate mi? "Monitor closely" gibi laflar yetersiz — somut mitigation iste.
- §10 Decisions Locked: her seçim için "rationale" var mı?
- §11-§16 (deployment, observability, security, test strategy, DR, runbook): `**[NEEDS-INPUT]**` etiketleri varsa cevaplaman lazım — Architect bilmiyor, sen biliyorsun.

### G3 — Schema/migration onayı (otomatik tetiklenir)
- DAG'da schema/migration task'ı varsa state `SCHEMA_AWAITING_APPROVAL` olur. SQL'i oku, prod-time'da downtime riski var mı bak.

### G7 — Budget gate (otomatik tetiklenir)
- `AI_FACTORY_BUDGET_CAP_USD` aşılınca state `BUDGET_AWAITING_APPROVAL`. Cap'i artır veya `paused`'a düşür.

### Task-level — AWAITING_HITL
- Worker üç deneme sonra başarısız olursa veya SecurityReviewer hard veto verirse o task `AWAITING_HITL`. Manuel müdahale gerek (bkz. [`failure-recovery.md`](../runbook/failure-recovery.md)).

### Audit log
- `runtime/audit/<date>.jsonl` — her LLM çağrısı, her state transition, her gate openning. Hash-chain ile değiştirilirse fark edilir (`ortim audit-verify`).

### Reviewer'ın gerçekten yakaladığı şeyler
- L1 prensip ihlali (DI eksikliği, side effect in module init)
- Acceptance criteria mismatch
- Module boundary leak (barrel import yokken raw path)
- SQL injection / XSS / hardcoded secret (SecurityReviewer)
- Test infrastructure missing (Item 24 mode)

### Reviewer'ın yakalayamadığı şeyler
- Mantıksal bug'lar (algoritmanın yanlış olması)
- Business rule eksikleri (user şunu dedi ama PRD farklı yazdı)
- UX hataları (frontend görsel sorunları)

**Gerçeği şu:** Reviewer kapısı **kod-kalitesi + güvenlik temel taraması** içindir, kod review'unu **yerine koymaz**. Production'a alacaksan kendi review'un + integration test'in + canary deploy'un olmalı.

---

## 6. Yaygın sorunlar + çözümleri

### 6.1 "DEEPSEEK_API_KEY not set"

`.env` dosyası doğru yerde mi? Repo kökünde olmalı. Dosyayı kaydedip yeni terminal aç (env vars cache'lenebilir).

### 6.2 Architect yanlış tier seçti

- "T4 ise neden T5 verdi?" → muhtemelen `team_size: large` veya `expected_scale: large` çıkardı. `golden_path_inputs.json` aç, bak.
- "T2 BaaS verdi ama self-hosted istiyorum" → Faz 1.2 B-1 fix bunu kapatıyor, eğer hâlâ oluyorsa `user_stack_hints` capture edildi mi (`intent.json`)? Yoksa brief'inde "SQLite", "Postgres", "FastAPI" gibi self-hosted teknolojiyi açıkça adlandırmamış olabilirsin.

### 6.3 Task AWAITING_HITL'e takıldı

İki ana sebep:
- **Sandbox/criteria failure** — Worker 3 deneme sonra başarısız. `tasks/T-NNN.md` ve audit log'a bak. `last_review_reasons` field'ı sebebi gösterir.
- **`test_infrastructure_unavailable`** — test runner yoksa veya kırıksa (item 24). `.ai-factory.env`'deki `AI_FACTORY_TEST_CMD` doğru mu?

Çözüm yolu: [`failure-recovery.md`](../runbook/failure-recovery.md).

### 6.4 Cost spike

`AI_FACTORY_BUDGET_CAP_USD` set et (örn. 2.00 USD). Cap aşılınca G7 açılır, otomatik durur.

Aşan kalemler genellikle:
- Architect Anthropic'te + RFC drafting retry'a girdi (drift validator tetikledi)
- Worker bir task için 3× retry yaptı
- Çok büyük PRD/RFC (token sayısı yüksek)

`ortim retro <id>` ile breakdown'u gör.

### 6.5 State machine hatası — "Cannot transition X -> Y"

Geçersiz state'ler arasında geçmek istedin. `ortim states` ile tüm transition'ları listele. Geri atmak istiyorsan genelde mümkün:
- `prd_awaiting_approval` → `prd_drafting` (PRD'yi düzenle)
- `mvp_scope_locking` → `prd_dialog` (PRD'yi yeniden yaz)
- `rfc_awaiting_approval` → `rfc_drafting`
- `executing` → `paused`

### 6.6 "command not found: ortim"

Venv aktive değil. `.venv/Scripts/activate` (Windows) veya `source .venv/bin/activate` (macOS/Linux).

Veya editable install kopuk: `pip install -e .` tekrar.

### 6.7 Workspace dolu — disk yer kaplıyor

`workspaces/*/node_modules`, `*/.venv`, `*/target` (Rust) gibi dependency klasörleri büyür. Hâlâ ihtiyacın olmayan workspace'leri sil veya arşivle.

`ortim list-projects` ile son N proje durumu görünür.

---

## 7. Buradan sonra nereye

- **Daha derin mimari:** [`Ortim_Architecture.md`](../../Ortim_Architecture.md) — agent'lar, state machine, audit, RAG.
- **Tier seçim mantığı:** [`docs/golden-paths/`](../golden-paths/) — her tier için reference doc.
- **Yeni skill yazmak:** [`docs/skills/authoring-guide.md`](../skills/authoring-guide.md) (yakında — Faz 2).
- **Brownfield (mevcut codebase):** `ortim new --from-existing <path>` — bkz. `ortim inspect --help`.
- **Iteratif geliştirme:** `ortim extend <id> "<yeni feature brief>"` — DONE projeye delta ekler.
- **Audit + drift kontrolü:** `ortim drift-check`, `ortim audit-verify`.
- **Roadmap + bilinen açıklar:** [`docs/plans/2026-Q2-roadmap.md`](../plans/2026-Q2-roadmap.md), [`docs/backlog.md`](../backlog.md).

---

## Cheatsheet

```bash
# Sağlık + kurulum
ortim doctor

# Hızlı tanıtım (no input)
ortim demo

# Yeni proje
ortim new "name" --brief "TR brief"
ortim run <id>                    # Babel + Analyst → MVP_SCOPE_LOCKING
ortim scope <id> --lock           # scope'u auto-lock + G1
ortim show <id> --artifact prd
ortim advance <id> prd_approved
ortim run <id>                    # Architect → RFC_AWAITING_APPROVAL
ortim advance <id> rfc_approved
ortim run <id>                    # Orchestrator → tasks_ready
ortim run-all <id> --phase 1      # Worker × N

# Gözlem
ortim status <id>
ortim tasks <id>
ortim retro <id>
ortim drift-check <id>
ortim show <id> --artifact rfc

# İterasyon
ortim refine <id> "feedback"      # dialog mode
ortim extend <id> "yeni feature"  # DONE sonrası delta
```

Tutorial'ı bitirdin. Bir sorunla karşılaşırsan veya tutorial'da boşluk gördüysen GitHub issue aç.
