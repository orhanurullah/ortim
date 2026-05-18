# Ortim — Başlangıç Rehberi (TR arşiv)

> **English-canonical:** The English version at [`docs/tutorial/getting-started.md`](../../tutorial/getting-started.md) is the canonical source. This Turkish translation is preserved for historical reference and may lag behind. Yeni özellikler için İngilizce sürümü esas alın.

---

> İlk projeni 15 dakikada bitirmek için adım adım kılavuz. Yazılım geliştirici için yazılmıştır; terminal kullanımı + bir LLM API key'i + temel git bilgisi gerektirir.

Bu rehber:
- Ne **değil**: mimari spec (o [`Ortim_Architecture.md`](../../Ortim_Architecture.md)). Tüm CLI komutlarının referansı (o `ortim --help`).
- Ne **dir**: sıfırdan ilk projene kadar yapılacaklar listesi + neyin neden öyle çalıştığı.

İçindekiler:
1. [Kurulum + ortam](#1-kurulum--ortam)
2. [ortim doctor — sağlık kontrolü](#2-ortim-doctor--sağlık-kontrolü)
3. [İlk run — `ortim demo`](#3-i̇lk-run--ortim-demo)
4. [Gerçek proje — `ortim init`'ten DONE'a](#4-gerçek-proje--ortim-initten-donea)
5. [Trust calibration — AI yazdı, ben imzalıyorum](#5-trust-calibration--ai-yazdı-ben-i̇mzalıyorum)
6. [Yaygın sorunlar + çözümleri](#6-yaygın-sorunlar--çözümleri)
7. [Buradan sonra nereye](#7-buradan-sonra-nereye)

---

## 1. Kurulum + ortam

### 1.1 Repo'yu klonla

```bash
git clone https://github.com/orhanurullah/ortim.git
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
ORTIM_BUDGET_CAP_USD=2.00
```

**Neden ikisi de opsiyonel ama DEEPSEEK_API_KEY pratik gereklilik?**

Ortim **multi-provider** — her ajan rolü ayrı bir provider'a yönlendirilebilir. Hiç provider key'i yoksa LLM çağrısı yapan komutlar (`new`, `run`, `demo`, `run-all`, `extend`) çalışmaz; ama deterministic komutlar (`status`, `tasks`, `drift-check`, `score-tier`, `retro`) provider olmadan da çalışır.

Yalnız DeepSeek key'i ile sistem tamamen işler. Anthropic key'i eklersen kritik rolleri (Architect, SecurityReviewer) Anthropic'e yönlendirebilirsin (`.env`'de `ARCHITECT_PROVIDER=anthropic` gibi). Maliyet ~10× artar, kalite kısmi olarak artar — ekibin priority'sine göre seç.

**DeepSeek key'i nasıl alınır?** [platform.deepseek.com](https://platform.deepseek.com) → Sign up → API Keys → Create. İlk $5 free credit gelir; bir planning chain ~$0.01 olduğundan 500 proje free.

### 1.3 Workspace pattern — Project Mode (0.9+)

Ortim 0.9'dan itibaren **project mode** default'tur — git/cargo gibi davranır. Her projeyi kendi dizininde başlatırsın; Ortim metadata'yı orada bir `.ortim/` namespace'inde tutar, üretilen kodu **proje dizininin köküne** yazar.

```
~/dev/my-cool-project/        ← cwd; istediğin yer olabilir
├── .ortim/                   ← Ortim metadata (state.json, PRD.md, RFC.md, tasks/, audit.jsonl, ...)
├── auth/                     ← Worker'ın yazdığı kod (modül bazında)
├── src/
├── package.json              ← brownfield tespiti için kullanılan manifest
└── ...
```

`.gitignore`'a `.ortim/` ekle istersen — metadata'yı versiyon kontrolüne almak opsiyoneldir. (Bazıları PRD/RFC'yi commit'lemek ister; içlerinde `audit.jsonl` ve `.cache/` da olduğundan tamamı commit'lenirse repo'da gürültü olur.)

**Discovery**: Ortim hangi workspace'le çalışacağını şu sırayla bulur:
1. Komut satırında `--project / -p <id>` flag'i (override)
2. Cwd'de `.ortim/` varsa
3. Cwd'nin parent dizinlerinden ilkinde `.ortim/` varsa
4. `~/.ortim/registry.json` içindeki **current** pointer (`ortim use <id|name>` ile set edilir)
5. Bulunamadıysa friendly error + `ortim init` öner

**Birden fazla projeyi nasıl yönetirsin?**

```bash
ortim ls                      # tüm bilinen workspace'ler — '*' aktif olanı işaretler
ortim use my-cool-project     # active context'i set et (cwd dışından da resolve eder)
ortim workspace show <id>     # detay
ortim workspace archive <id>  # arşivle (mutating komutları bloklar)
```

**Legacy pool layout** (0.8 ve öncesi): repo kökündeki `workspaces/<uuid>/` altında yaşar. 0.9+ mevcut pool workspace'leri okumaya devam eder; istersen `ortim workspace migrate <pool-id> --to <path>` ile project mode'a taşırsın. Yeni projeler için pool mode önerilmez.

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

> **Demo, kendi cwd'ni kirletmez.** Geçici bir pool workspace yaratır (`workspaces/<uuid>/`), oraya yazar — bittiğinde inspect edip silebilirsin. Gerçek proje için §4'teki `ortim init` flow'unu kullan.

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

Çıktının son satırında pool workspace path'ini görürsün, örn. `workspaces/2050c9291eb7`. Bu projeyi açıp dosyalara bak:

```bash
cd workspaces/2050c9291eb7
ls
# PRD.md  RFC.md  intent.json  scope.json  golden_path_inputs.json  state.json  task_dag.json  tasks/
```

> Pool mode demo'ya özel. Gerçek projende dosyalar `<your-dir>/.ortim/` altında olur (§4).

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

`ortim show --artifact prd|rfc|scope|intent|stack` ile herhangi birini konsola bas (cwd-aware; demo dir'inden çalıştır, ya da `--project <id>`).

### 3.3 Maliyet kontrolü

```bash
cd workspaces/<demo-id>
ortim retro
```

Token kullanımı + USD maliyet tablosu döner. Planning-only demo tipik ~$0.01 (DeepSeek). Architect Anthropic'teyse ~$0.05–0.10.

---

## 4. Gerçek proje — `ortim init`'ten DONE'a

Demo "izle, gör" içindir; gerçek proje açmak için kendi dizinine girip `ortim init` çağırırsın. 0.9+ tüm komutlar cwd-aware — workspace'in `.ortim/` namespace'inde çözümlenir; UUID argüman geçmek zorunda değilsin.

### 4.1 Proje dizinini hazırla + init

```bash
mkdir ~/dev/cool-project && cd ~/dev/cool-project
ortim init "TR brief'in burada..."
```

Brief uzun olabilir — shell heredoc veya `$(cat brief.txt)` ile geçirebilirsin. Default isim cwd dizin adı; istersen `--name` flag'iyle override et.

Çıktı:

```
Initialized 7f3a2b9c1d4e (cool-project, greenfield)
Path: /home/you/dev/cool-project
State: intake

Next: ortim run (Babel + Analyst; ANTHROPIC_API_KEY veya DEEPSEEK_API_KEY gerekir)
```

`.ortim/` dizini şimdi cwd'de var. Bundan sonraki tüm komutlar — `run`, `status`, `scope`, `tasks`, `run-all`, ... — bu dizinden veya alt-dizinlerinden çalıştırılırsa otomatik bu workspace'i seçer.

**Brownfield (mevcut codebase)**: Eğer dizinde `package.json`, `pyproject.toml`, `Cargo.toml`, `go.mod` gibi manifest dosyaları varsa `ortim init` otomatik brownfield mode'a düşer — codebase'i tarar, mevcut framework/dil tespit eder, Architect Call 1'i atlayıp doğrudan RFC drafting'e gider. Manuel override: `--greenfield` (boş dizin gibi davran) veya `--brownfield` (zorla codebase tarama).

### 4.2 Babel + planning'i çalıştır

```bash
ortim run
```

Pozisyonel UUID yok — komut cwd'den `.ortim/`'i bulur. Eğer farklı bir dizinden çalıştırıyorsan `--project <id>` veya `ortim use <id>` ile aktif context'i set et.

`run` komutu state'e göre uygun ajanı çağırır. İlk çağrı Babel'i koşturur, intent.json üretir, PRD_DRAFTING state'ine geçer.

Default davranış: **dialog mode kapalı** ise `run` tek seferde Babel + Analyst'i ardışık koşturur ve seni MVP_SCOPE_LOCKING'e bırakır. Dialog mode (M2 conversational) açıksa state machine her dialog state'i ayrı ele alır — `ortim refine` + `ortim lock` ile ilerlersin.

### 4.3 Scope locking — Faz 1.1

PRD draftlanınca state `MVP_SCOPE_LOCKING` olur. `scope.json` otomatik seed olur (must_have→phase 1, nice_to_have→phase 2). Şimdi karar verme zamanı:

```bash
ortim scope
```

İnteraktif tablo + her feature için phase atama prompt'u açılır. Default'u kabul etmek için Enter'a bas.

Headless (CI veya hızlı kullanım):

```bash
ortim scope --set "social login=2" --lock
```

`--set "<substring>=<phase>"` ile birden çok feature düzenlenebilir. `--lock` interactive prompt'u atlar ve PRD_AWAITING_APPROVAL'a geçer.

**Neden bu adım gerekli?** Architect Call 2 RFC §7 Module Breakdown'u **iki-katmanlı** üretir (Phase 1 MVP / Phase 2+ Deferred). Phase 2 olarak işaretlenen feature'lar için Orchestrator hiç task üretmez — onlar `ortim extend` ile sonraki sprint'e kalır.

### 4.4 G1 — PRD onayı

```bash
ortim show --artifact prd
```

Oku. Her must_have feature beklenen şekilde yer alıyor mu? Non-goal'lar net mi? open_questions varsa cevaplaman gerekli mi?

Onayla:

```bash
ortim advance prd_approved --note "reviewed"
```

> `advance` ve `execute`/`extend` çoklu-pozisyonel-arg aldıkları için `--project / -p` flag pattern'i kullanırlar. Cwd-aware çalışıyorsan flag gereksiz; farklı dizindeysen: `ortim advance prd_approved -p 7f3a2b9c1d4e --note ...`.

PRD'de düzeltme istersen `ortim refine "feedback"` (dialog mode açıksa) veya `ortim advance prd_drafting` ile geri at, sonra PRD.md'yi elle düzenle veya `ortim run` ile tekrar üret.

### 4.5 Architect — RFC + tier

```bash
ortim run
```

Architect Call 1 PRD'den `GoldenPathInputs` çıkarır. Eğer Babel `user_stack_hints` capture etmişse (örn. "Flutter", "SQLite"), main.py app_class ve tier scorer hint'lerini override eder (Faz 1.2 fix).

Sonra deterministic scorer tier'ı seçer, Architect Call 2 RFC.md drafter.

### 4.6 G2 — RFC onayı

```bash
ortim show --artifact rfc
```

Bak:
- §2 **Selected Tier** doğru mu (T0–T6 web / M0–M2 mobile / D0–D1 desktop)?
- §4 **Tech Stack** brief'inde adlandırdığın araçları gösteriyor mu? "user-named" etiketi var mı?
- §7 **Module Breakdown** iki-katmanlı (Phase 1 | Phase 2+) mi?
- §9 **Risks** boş değil mi (en az 3 risk olmalı)?

Sorun varsa: `ortim advance rfc_drafting` ile geri, RFC.md'yi elle düzenle. Sorun yoksa:

```bash
ortim advance rfc_approved --note "reviewed"
```

### 4.7 Orchestrator — DAG generation

```bash
ortim run
```

Orchestrator RFC'yi okur, atomik task'lar üretir. Validator'ler (cycle yok, missing dep yok, module_scope ∈ RFC §7, phase ∈ {1, 2+}) ihlali yakalarsa retry'la (max 3 kez).

```bash
ortim tasks
```

Task listesi + dependency tablosu çıkar. Her task `.ortim/tasks/T-NNN.md` dosyasında.

### 4.8 Worker — implementasyon

```bash
ortim run-all --phase 1
```

`--phase 1` bayrağı sadece MVP task'larını koşturur (Phase 2+ PENDING kalır). Default sequential mode, her task git branch'inde isolation.

Worker her task için:
1. RFC + task brief + skill'leri okur
2. Kod yazar (FILE_BLOCK formatında WorkerOutput)
3. Sandbox structural validator geçer mi?
4. Test runner çalışır (`.ortim.env`'de tanımlı `ORTIM_TEST_CMD`)
5. Reviewer chain (Code/Security/Test/Perf) verdict döner
6. APPROVED → DONE; REJECT → 3 retry'la kadar; AWAITING_HITL → durur

Üretilen kod **cwd köküne** yazılır (`auth/`, `src/`, ...). Metadata `.ortim/` altında kalır.

### 4.9 İlerleme izleme

```bash
ortim status         # state + history
ortim drift-check    # RFC ↔ DAG ↔ status integrity
ortim retro          # cost + retry rate + HITL escalations
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
- `ORTIM_BUDGET_CAP_USD` aşılınca state `BUDGET_AWAITING_APPROVAL`. Cap'i artır veya `paused`'a düşür.

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
- **`test_infrastructure_unavailable`** — test runner yoksa veya kırıksa (item 24). `.ortim.env`'deki `ORTIM_TEST_CMD` doğru mu?

Çözüm yolu: [`failure-recovery.md`](../runbook/failure-recovery.md).

### 6.4 Cost spike

`ORTIM_BUDGET_CAP_USD` set et (örn. 2.00 USD). Cap aşılınca G7 açılır, otomatik durur.

Aşan kalemler genellikle:
- Architect Anthropic'te + RFC drafting retry'a girdi (drift validator tetikledi)
- Worker bir task için 3× retry yaptı
- Çok büyük PRD/RFC (token sayısı yüksek)

`ortim retro` ile breakdown'u gör (proje dizini içinden).

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

`node_modules`, `.venv`, `target` (Rust) gibi dependency klasörleri büyür. Bunlar cwd'nin köküne yazıldığı için kendi proje dizininde yönetilir.

```bash
ortim ls                                # tüm bilinen workspace'ler
ortim workspace archive <id>            # mutating komutları blokla, listede sakla
ortim workspace cleanup --older-than 30 --archived-only --yes
                                        # 30+ gündür arşivli olanların .ortim/ dizinlerini sil
ortim workspace doctor                  # registry ↔ disk tutarlılık taraması
```

Project mode'da `cleanup` sadece `.ortim/` namespace'ini siler — kullanıcı kodu dokunulmaz. Pool legacy workspace'lerde tüm dizin silinir.

---

## 7. Buradan sonra nereye

- **Daha derin mimari:** [`Ortim_Architecture.md`](../../Ortim_Architecture.md) — agent'lar, state machine, audit, RAG.
- **Tier seçim mantığı:** [`docs/golden-paths/`](../golden-paths/) — her tier için reference doc.
- **Yeni skill yazmak:** [`docs/skills/authoring-guide.md`](../skills/authoring-guide.md) (yakında — Faz 2).
- **Brownfield (mevcut codebase):** `cd <project> && ortim init "<brief>"` — manifest dosyaları varsa auto-detect. `ortim inspect` ile baseline'ı incele.
- **İteratif geliştirme:** DONE projeye delta ekle — proje dizininden `ortim extend "<yeni feature brief>"`. Farklı dizindeysen `ortim extend "..." -p <id>`.
- **Birden çok workspace yönetimi:** `ortim ls` (liste) · `ortim use <id|name>` (active context) · `ortim workspace {show,archive,cleanup,doctor,migrate}`.
- **Pool → project migration (legacy):** `ortim workspace migrate <pool-id> --to <path>` — pool layout'unu yeni dizine taşır, default `--copy` ile rollback-safe.
- **Audit + drift kontrolü:** `ortim drift-check`, `ortim audit-verify`.
- **Roadmap + bilinen açıklar:** [`docs/plans/2026-Q2-roadmap.md`](../plans/2026-Q2-roadmap.md), [`docs/backlog.md`](../backlog.md).

---

## Cheatsheet

Project mode default'tur — komutlar cwd'den `.ortim/`'i bulur. Aşağıdaki örnekler proje dizini içinden çalıştırılıyor varsayar.

```bash
# Sağlık + kurulum
ortim doctor

# Hızlı tanıtım (no input, pool workspace)
ortim demo

# Yeni proje
mkdir ~/dev/cool-project && cd ~/dev/cool-project
ortim init "TR brief..."          # .ortim/ namespace oluştur (brownfield: auto-detect)
ortim run                         # Babel + Analyst → MVP_SCOPE_LOCKING
ortim scope --lock                # scope'u auto-lock + G1
ortim show --artifact prd
ortim advance prd_approved        # advance/execute/extend: 1-pos + -p flag pattern
ortim run                         # Architect → RFC_AWAITING_APPROVAL
ortim advance rfc_approved
ortim run                         # Orchestrator → tasks_ready
ortim run-all --phase 1           # Worker × N

# Gözlem (cwd-aware)
ortim status
ortim tasks
ortim retro
ortim drift-check
ortim show --artifact rfc

# İterasyon
ortim refine "feedback"           # dialog mode
ortim extend "yeni feature"       # DONE sonrası delta

# Workspace yönetimi (cwd dışından)
ortim ls                          # tüm bilinen workspace'ler (* aktif olanı)
ortim use cool-project            # aktif context'i set et (registry pointer)
ortim status -p 7f3a2b9c1d4e      # belirli bir workspace'i target'la
ortim workspace archive <id>
ortim workspace cleanup --older-than 30 --archived-only --yes
```

Tutorial'ı bitirdin. Bir sorunla karşılaşırsan veya tutorial'da boşluk gördüysen GitHub issue aç.
