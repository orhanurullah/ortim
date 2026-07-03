# Ortim — Kapsamlı Kullanım Rehberi (Türkçe)

> Bu rehber, Ortim CLI'ın **her adımını ve karşılaşabileceğin her durumu** uçtan uca anlatır:
> kurulumdan ilk projeye, gate (onay kapısı) yönetiminden hata kurtarmaya, çoklu sağlayıcı
> yönlendirmesinden bulut yönetişimine kadar. Komut adları ve seçenekler 0.9.5 kod tabanından
> doğrulanmıştır.
>
> İngilizce muadilleri: [`docs/tutorial/getting-started.md`](../tutorial/getting-started.md) (öğretici),
> [`docs/runbook/failure-recovery.md`](../runbook/failure-recovery.md) (kurtarma).

## İçindekiler

1. [Ortim nedir, ne zaman kullanılır](#1-ortim-nedir)
2. [Kurulum ve ilk yapılandırma](#2-kurulum)
3. [Temel kavramlar](#3-temel-kavramlar)
4. [Komut haritası (tam liste)](#4-komut-haritası)
5. [Uçtan uca akış — yeni proje (greenfield), adım adım + her durum](#5-greenfield)
6. [Mevcut kod tabanı (brownfield) akışı](#6-brownfield)
7. [Onay kapıları (G1–G7) detaylı](#7-gateler)
8. [State machine — tüm durumlar ve geçişler](#8-state-machine)
9. [Görev yürütme: execute / run-all](#9-yurutme)
10. [Gözlemlenebilirlik ve denetim](#10-gozlem)
11. [İterasyon: refine / scope / extend](#11-iterasyon)
12. [Çoklu sağlayıcı (LLM) yönlendirmesi](#12-saglayici)
13. [Workspace (çalışma alanı) yönetimi](#13-workspace)
14. [Skill (proje-özel desen) sistemi](#14-skill)
15. [Ortim Cloud — yönetişim (önizleme)](#15-cloud)
16. [Sorun giderme ve kurtarma — her hata durumu](#16-sorun-giderme)
17. [Maliyet yönetimi](#17-maliyet)
18. [Hızlı referans (cheatsheet)](#18-cheatsheet)

---

<a name="1-ortim-nedir"></a>
## 1. Ortim nedir, ne zaman kullanılır

Ortim, **tek paragraflık bir brief'i → çalışan, gözden geçirilmiş, denetim izli koda** dönüştüren
disiplinli, çok-ajanlı bir "AI yazılım fabrikası"dır. Çıplak bir LLM'e "bana şunu yaz" demenin tipik
hatalarını (mimariyi keyfine göre seçme, test atlama, kütüphane uydurma, kapsam kayması, denetlenemezlik)
**yapısal olarak** engeller:

- **Deterministik state machine** — onay kapıları tavsiye değil, yapısaldır; atlanamaz.
- **İki zorunlu insan kapısı** (G1 = PRD, G2 = RFC) + 5 koşullu kapı.
- **Hash-zincirli denetim kaydı** (`.ortim/audit.jsonl`) — kurcalama tespit edilebilir.
- **Kapsam-kilitli görev DAG'ı** — her görev bir modül sınırına hapsedilir.
- **Mimariyi LLM seçmez** — kural-tabanlı bir scorer 12 tier arasından seçer.

**Ne zaman Ortim:** "Gerçek bir brief'i gerçek bir hattan geçir, 6 ay sonra ne olduğunu ve neden
olduğunu açıklayabil." Greenfield + brownfield, savunulabilir olması gereken hatlar.

**Ne zaman IDE asistanı (Cursor/Claude Code/Aider):** "Ben bakarken şu fonksiyonu düzelt." Bunlar
tamamlayıcıdır — birçok kullanıcı iskeleti + kritik özellikleri Ortim ile üretip günlük düzenlemeyi
IDE eklentisiyle yapar.

---

<a name="2-kurulum"></a>
## 2. Kurulum ve ilk yapılandırma

### 2.1 Kurulum

```bash
pip install ortim
```

Gereksinim: **Python ≥ 3.11**. Komut iki isimle de çalışır: `ortim` (kanonik) ve `ai-factory` (eski alias).

### 2.2 Sağlayıcı (LLM) yapılandırması — iki yol

**Önerilen yol — `ortim config init` (interaktif sihirbaz).** `~/.ortim/config.toml` dosyasına yazar;
`.env` gerekmez ve her dizinden çalışır:

```bash
ortim config init        # sağlayıcı → model → API anahtarı (tek seferlik)
ortim config show        # neyin çözüldüğünü, her alanın kaynağıyla göster
ortim config path        # config dosyasının yolu
```

İlgili config alt-komutları:

| Komut | İşlev |
|---|---|
| `ortim config set-provider <anthropic\|deepseek\|ollama>` | Varsayılan sağlayıcı |
| `ortim config set-model <model-id>` | Varsayılan model |
| `ortim config set-key <provider>` | Bir sağlayıcının anahtarı |
| `ortim config set-role architect --provider anthropic` | Rol bazlı override |
| `ortim config setup-local` | Yerel Ollama'yı API anahtarsız bağla |

**Alternatif — ortam değişkenleri (`.env`).** Hâlâ desteklenir; `~/.ortim/config.toml` yalnız boşlukları
doldurur, asla override etmez:

```ini
# .env — minimum
DEEPSEEK_API_KEY=sk-...

# Hibrit — yargı gerektiren rollerde premium model
ANTHROPIC_API_KEY=sk-ant-...
ARCHITECT_PROVIDER=anthropic
SECURITY_REVIEWER_PROVIDER=anthropic
```

**Çözümleme önceliği (yüksekten düşüğe):** `--provider` bayrağı → kabuk/`.env` ortam değişkeni →
`~/.ortim/config.toml` → kodda gömülü varsayılan.

### 2.3 Sağlık kontrolü

Her şeyin hazır olduğunu doğrula:

```bash
ortim doctor     # anahtarlar, çalışma zamanları (git/node/python), prompt'lar, şablonlar
```

`doctor` çıktısı **required** (zorunlu) ve **recommended** (önerilen) kontrolleri ayırır. PyPI kurulumunda
`MISS` satırları görüyorsan 0.9.5+ kullandığından emin ol (eski tekerlekler markdown asset'lerini paketlemiyordu).

### 2.4 Hiç API anahtarı olmadan denemek

```bash
ortim demo                       # uçtan uca, girdisiz mini tur
ortim demo --provider ollama     # tamamen yerel, sıfır API anahtarı (Ollama kuruluysa)
ortim score-tier --state --auth --scale medium --compliance KVKK
#  ^ deterministik tier scorer — API anahtarı YOK, workspace YOK, tekrarlanabilir
```

---

<a name="3-temel-kavramlar"></a>
## 3. Temel kavramlar

### 3.1 Boru hattı (pipeline) ve ajanlar

```
[brief]
   ↓  Babel        (herhangi bir dil → yapısal niyet; token-tutumlu)
intent.json
   ↓  Analyst       (IntentAnalyst + StackAnalyst + PRDAnalyst)
PRD.md + stack.json
   ↓  G1 — insan onayı (ZORUNLU)
   ↓  Architect     (Call 1: scorer girdileri; Call 2: RFC + modül kırılımı)
RFC.md + golden_path_inputs.json
   ↓  G2 — insan onayı (ZORUNLU)
   ↓  Orchestrator  (TaskDAG; her görev RFC modüllerinin alt kümesi)
task_dag.json + .ortim/tasks/T-NNN.md
   ↓  Worker × N    (FILE_BLOCK çıktısı, görev başına git dalı)
   ↓  Reviewer zinciri (Code → Security → Test → Perf)
   ↓  Hook'lar      (pre_commit / pre_deploy)
DONE
```

**İki değişmez kural:**
- **LLM asla tier seçmez.** Architect Call 1 parametre üretir; `ortim/architecture/golden_paths.py`
  kural-tabanlı puanlar (12 tier: T0–T6 web, M0–M2 mobil, D0–D1 masaüstü).
- **DAG'lar runtime'da doğrulanır.** LLM döngü, eksik bağımlılık veya RFC-dışı modül üretirse, doğrulayıcı
  3 kez dener, sonra `AWAITING_HITL`'e yükseltir.

### 3.2 Project Mode vs Pool (legacy)

0.9'dan itibaren komutlar **cwd-aware** (bulunduğun dizinden çalışma alanını keşfeder):

| Mod | Metadata yeri | Nasıl oluşur |
|---|---|---|
| **Project Mode** (varsayılan) | `<proje-dizinin>/.ortim/` | `ortim init` |
| **Pool** (legacy) | `workspaces/<id>/` | eski `ortim new` |

Komutları proje dizininin içinden çalıştır. Dışarıdaysan veya birden fazla çalışma alanın varsa,
her komutta `--project / -p <id>` bayrağı çalışır. `ortim ls` tüm bilinen çalışma alanlarını listeler.

### 3.3 `.ortim/` içindeki dosyalar (artefaktlar)

| Dosya | İçerik |
|---|---|
| `state.json` | **Tek doğru kaynak** — state machine durumu + geçmiş |
| `intent.json` | Babel'in çıkardığı yapısal niyet (`user_stack_hints` dahil) |
| `PRD.md` | Ürün gereksinim dokümanı |
| `scope.json` | MVP kapsam kilidi (özellik → faz/öncelik) |
| `RFC.md` | Mimari karar dokümanı (§4 stack, §7 modül kırılımı) |
| `golden_path_inputs.json` | Tier scorer girdileri |
| `task_dag.json` | Görev DAG'ı |
| `tasks/T-NNN.md` | Görev başına brief + kabul kriterleri |
| `task_status.json` | Görev başına durum, `last_review_reasons`, retry sayısı |
| `audit.jsonl` | Hash-zincirli denetim kaydı |
| `policy.json` | (Cloud bağlıysa) önbelleğe alınmış org politikası |
| `.ortim.env` | Projeye özel ortam değişkenleri (örn. `ORTIM_TEST_CMD`) |

> `state.json` her zaman gerçeğin kaynağıdır; bir sorunu teşhis ederken doğrudan açmak meşru bir adımdır.

---

<a name="4-komut-haritası"></a>
## 4. Komut haritası (tam liste)

### Kurulum / sağlık
- `ortim doctor` — anahtar/çalışma zamanı/prompt/şablon kontrolü
- `ortim config init | show | path | set-provider | set-model | set-key | set-role | setup-local`
- `ortim demo` — girdisiz uçtan uca tur

### Proje yaşam döngüsü
- `ortim init "<brief>"` — bulunduğun dizinde `.ortim/` oluştur (greenfield/brownfield otomatik)
- `ortim run` — sıradaki ajanı çalıştır (Babel→Analyst→Architect→Orchestrator)
- `ortim scope [--show|--lock|--reset|--set-phase ...]` — MVP kapsam kilidi
- `ortim lock [-y]` — aktif diyalog durumunu kilitle, sonrakine geç
- `ortim advance <hedef> [--note ...]` — durumu elle ilerlet (HITL onayları + acil durum)
- `ortim refine "<geri bildirim>"` — aktif diyalog ajanını geri bildirimle yeniden çağır
- `ortim show [--artifact intent|stack|prd|scope|current]` — artefaktı yazdır
- `ortim run-all [--phase N] [--parallel] [--continue-on-fail]` — DAG'ı topolojik partiler hâlinde çalıştır
- `ortim execute T-NNN [--max-attempts N] [--human-reviewed]` — tek görevi hattan geçir
- `ortim extend "<yeni özellik>"` — DONE projeye delta döngüsü ekle
- `ortim extensions` — extend döngü geçmişi

### Gözlemlenebilirlik / denetim
- `ortim status` — durum + geçmiş
- `ortim tasks` — görev DAG'ı
- `ortim gates` — açık HITL kapıları (G1–G7) + bütçe durumu
- `ortim states` — tüm state machine + yasal geçişler
- `ortim budget [--by-provider]` — token + USD
- `ortim retro` — denetim kaydı üzerinden çok-eksenli özet
- `ortim drift-check` — RFC ↔ DAG ↔ status ↔ audit hizalaması
- `ortim audit-verify` — hash zincirini yürü, kurcalamayı işaretle
- `ortim score-tier ...` — deterministik tier scorer (API anahtarsız)
- `ortim mutation-test` — Reviewer mutation testi
- `ortim inspect | rescan | baseline` — brownfield tarama/yeniden tara/test temel çizgisi

### Çalışma alanı (her yerden)
- `ortim ls` — tüm bilinen çalışma alanları ('*' = aktif)
- `ortim use <id|name>` — aktif işaretçiyi ayarla
- `ortim workspace show | archive | unarchive | cleanup | migrate | doctor`

### Skill
- `ortim skill list | show <name>`

### Cloud (önizleme)
- `ortim cloud login <email> | logout | status | orgs | link --org <id> | sync | policy`

---

<a name="5-greenfield"></a>
## 5. Uçtan uca akış — yeni proje (greenfield), adım adım + her durum

Aşağıda **her adım** ve o adımda karşılaşabileceğin **her durum/karar dalı** anlatılır.

### Adım 0 — Dizin oluştur ve başlat

```bash
mkdir ~/dev/task-tracker && cd ~/dev/task-tracker
ortim init "Python + SQLite ile küçük bir görev takip CLI'ı, tek kullanıcı, yalnız yerel."
```

**`init` seçenekleri:**
- `--name "<ad>"` — kısa proje adı (varsayılan: dizin adı).
- `--greenfield` — brownfield otomatik-tespitini zorla atla (boş dizin gibi davran).
- `--brownfield` — manifest yoksa bile kod tabanını tara.
- `--app-class web|mobile|desktop` — uygulama sınıfını **baştan kilitle**. Ayarlanırsa Babel/LLM
  ipuçları sonradan değiştiremez. Ayarlanmazsa brief metni "mobile app", "Android", "desktop" gibi
  terimler için taranır (Babel sonradan yine override edebilir).

> **Durum — yanlış sınıflandırma riski:** Mobil/masaüstü bir proje yapıyorsan ve geçmişte Babel'in
> "web"e düşürdüğünü gördüysen, baştan `--app-class mobile` ver. Bu, en sık görülen erken-aşama hatasını
> (M5 bug ailesi) kökten engeller.

**Çıktı:** `Initialized <id> (<ad>, greenfield)`, `State: intake`, `App class: web` (veya kilitliyse `(locked)`).

> **Durum — `init` zaten var olan `.ortim/`'e:** Aynı dizinde tekrar `init` çağırırsan `InitError`
> alırsın. Sıfırdan başlamak istiyorsan §16.9'a bak (eski `.ortim`'i yeniden adlandır).

### Adım 1 — Planlama hattını çalıştır (Babel + Analyst)

```bash
ortim run
```

`ortim run` **sıradaki** ajanı otomatik seçer (`--step auto`, varsayılan). İstersen tek adımı zorla:

```bash
ortim run --step babel        # yalnız Babel
ortim run --step analyst      # yalnız Analyst zinciri
ortim run --step architect    # yalnız Architect
ortim run --step orchestrator # yalnız Orchestrator (DAG)
ortim run --provider ollama --model qwen2.5-coder:7b   # bu çağrı için sağlayıcı override
```

**Diyalog modu (varsayılan açık, `ORTIM_DIALOG_MODE=on`):** `run`, brief'i konuşarak netleştiren diyalog
durumlarına girer: `intake_dialog → stack_dialog → prd_dialog`. Her durumda:

- `ortim show` — aktif taslağı (niyet/stack/PRD) gör.
- `ortim refine "<geri bildirim>"` — ajanı geri bildirimle yeniden çağır (örn. *"etiketleme özelliğini ekle"*).
- `ortim lock` — mevcut taslağı kilitle, bir sonraki duruma geç (diff gösterir, onay ister; `-y` atlar).

> **Durum — diyalog modunu kapatmak:** `.env`'de `ORTIM_DIALOG_MODE=off` ile Babel doğrudan PRD taslağına
> geçer (eski/headless akış). CI veya scriptlerde işe yarar.

> **Durum — `run` hata verdi (API anahtarı yok):** "requires ANTHROPIC_API_KEY or DEEPSEEK_API_KEY" görürsen
> `ortim config init` ile anahtar gir veya `.env` ayarla; sonra `ortim run` tekrar.

### Adım 2 — MVP kapsam kilidi

PRD taslağı hazır olunca state `MVP_SCOPE_LOCKING`'e gelir. Burada her özelliğe **faz** (1 = MVP,
2+ = ertelenmiş) ve **öncelik** (`must`/`later`) atanır.

```bash
ortim scope --show            # önerilen kapsamı tablo olarak gör (düzenleme yok)
ortim scope                   # interaktif düzenleme
ortim scope --set-phase "feature-x=2" --set-phase "feature-y=1"   # headless atama
ortim scope --reset           # intent.json'dan yeniden tohumla (kullanıcı düzenlemeleri silinir)
ortim scope --lock            # interaktif düzenlemeyi atla, mevcut kapsamı kilitle ve G1'e geç
```

**Kapsam neden önemli:** Orchestrator, Phase 2 özellikleri için **sıfır görev** üretir; onlar daha sonra
`ortim extend` ile gelir. Kapsam kayması böyle engellenir.

> **Durum — alternatif:** `ortim lock` da bu durumu kilitleyip ilerletir; `ortim scope --lock` ise
> doğrudan kapsamı kilitleyip G1'e taşır. İkisi de G1'e götürür.

### Adım 3 — G1: PRD onayı (ZORUNLU kapı)

State şimdi `PRD_AWAITING_APPROVAL`.

```bash
ortim show --artifact prd     # PRD'yi oku
ortim gates                   # açık kapıyı doğrula (G1)
ortim advance prd_approved    # onayla
# veya düzeltme iste:
ortim advance prd_drafting --note "kapsamı daralt"   # geri adım, sonra ortim run
```

> **Durum — onaylamadan önce yeniden kapsamlamak:** `ortim advance mvp_scope_locking` ile kapsama dön.

### Adım 4 — RFC üretimi (Architect)

```bash
ortim run                     # Architect → RFC_AWAITING_APPROVAL
```

Architect iki çağrı yapar: Call 1 scorer girdilerini üretir; deterministik scorer tier'ı seçer; Call 2
RFC'yi (tier, stack, modüller, riskler, iki-katmanlı modül tablosu) yazar.

### Adım 5 — G2: RFC + Golden Path onayı (ZORUNLU kapı)

```bash
ortim show --artifact rfc
ortim advance rfc_approved
```

> **Durum — Architect yanlış stack seçti** (örn. "SQLite dedim, PostgreSQL yazdı): §16.6'ya bak. Özetle:
> `intent.json` içinde `user_stack_hints` boşsa brief'i somutlaştır (teknolojiyi açıkça adlandır); doluysa
> `ortim advance rfc_drafting && ortim run` ile yeniden üret veya `RFC.md` §4'ü elle düzeltip onayla.

### Adım 6 — Görev DAG'ı üretimi (Orchestrator)

```bash
ortim run                     # Orchestrator → tasks_ready
ortim tasks                   # üretilen DAG'ı gör
```

> **Durum — G3 (şema kapısı) devreye girer:** DAG'da şema/migration görevi varsa state `tasks_ready`
> yerine `schema_awaiting_approval`'a gidebilir. §7'ye bak; `ortim advance schema_approved` ile devam et.

### Adım 7 — Görevleri çalıştır (Worker + Reviewer)

```bash
ortim run-all --phase 1       # yalnız MVP (faz 1) görevlerini çalıştır
# veya tek görev:
ortim execute T-003
```

`run-all` topolojik partiler hâlinde ilerler. Bir görev `FAILED` veya `AWAITING_HITL`'e düşerse varsayılan
olarak **durur** (`--stop-on-fail`). Detaylar ve seçenekler §9'da.

### Adım 8 — Tamamlama

Tüm görevler geçince state `DONE`. Gözlemle:

```bash
ortim status                  # DONE + geçmiş
ortim retro                   # token + USD maliyet özeti
ortim drift-check             # RFC ↔ DAG ↔ status bütünlüğü
ortim audit-verify            # hash zincirini doğrula
```

> **Durum — sonradan özellik eklemek:** `ortim extend "<yeni özellik>"` (§11.3).

---

<a name="6-brownfield"></a>
## 6. Mevcut kod tabanı (brownfield) akışı

`ortim init` bir dizinde `package.json` / `pyproject.toml` / `Cargo.toml` / `go.mod` / `pubspec.yaml`
görürse **otomatik** brownfield moduna girer: import-graph çıkarımı + kapsam-farkında görev üretimi.

```bash
cd ~/dev/mevcut-proje
ortim init "kullanıcı profili modülü ekle"   # manifest → otomatik brownfield
ortim inspect                                 # kod tabanı tarama özeti (framework'ler, modüller)
ortim run                                     # Architect Babel'i atlar, mevcut koddan PRD taslar
```

İlgili brownfield komutları:

| Komut | İşlev |
|---|---|
| `ortim inspect` | Kod tabanı tarama özeti |
| `ortim rescan` | Büyük değişiklikten sonra taramayı yenile |
| `ortim baseline --recapture` | Test paketini yeniden çalıştır, temel çizgiyi sakla |

> **Durum — brownfield'ı zorlamak/engellemek:** Manifest yoksa ama yine de taramak istiyorsan
> `ortim init "..." --brownfield`. Tersine, dolu bir dizini boş gibi ele almak için `--greenfield`.

---

<a name="7-gateler"></a>
## 7. Onay kapıları (G1–G7) detaylı

Açık kapıları her an `ortim gates` ile gör. Bir kapı, görevi/projeyi bir bekleme durumunda duraklatır;
`ortim advance <durum>_approved` ile devam edilir.

| Kapı | Durum / tetik | Zorunlu mu | Devam komutu |
|---|---|---|---|
| **G1** PRD | `prd_awaiting_approval` | **Evet** | `ortim advance prd_approved` |
| **G2** RFC + Golden Path | `rfc_awaiting_approval` | **Evet** | `ortim advance rfc_approved` |
| **G3** Şema/migration | `schema_awaiting_approval` | Koşullu (DAG'da şema görevi) | `ortim advance schema_approved` |
| **G4** Dış entegrasyon | görev → `AWAITING_HITL` | Koşullu (yeni dış SDK/URL) | görevi gözden geçir + `ortim execute T-NNN --human-reviewed` |
| **G5** Güvenlik | görev → `AWAITING_HITL` | Koşullu (SecurityReviewer hard veto) | sorunu düzelt, sonra `ortim execute T-NNN` |
| **G6** Deploy | `deploy_awaiting_approval` | Koşullu (deploy görevi) | `ortim advance deploy_approved` |
| **G7** Bütçe | `budget_awaiting_approval` | Koşullu (cap aşıldı) | `ortim advance budget_approved` |

**G1/G2** her zaman atılır — boru hattının omurgası. **G3, G6, G7** birer proje state'idir (yukarıdaki
state machine'de görünür). **G4 ve G5** görev-seviyesi kapılardır: ilgili görev `task_status.json`'da
`AWAITING_HITL`'e düşer (proje state'i değişmez).

> **Durum — bir kapıyı "atlamaya" çalışmak:** State machine seni kasıtlı engeller. `InvalidTransition`
> hatası alırsan §16.8'e bak; `ortim states` ile yasal geçişleri listele.

> **Durum — Cloud politikası zorunlu kapı dayatıyor:** Org'a bağlıysan (`ortim cloud link`), politika
> bazı kapıları zorunlu işaretleyebilir. Zorunlu bir kapıyı baypas eden bir run `policy_violation` denetim
> olayı + `Exit(2)` ile reddedilir. §15'e bak.

---

<a name="8-state-machine"></a>
## 8. State machine — tüm durumlar ve geçişler

`ortim states` tam tabloyu yazdırır. Ana hat:

```
intake → babel_processing → intake_dialog → stack_dialog → prd_dialog
       → mvp_scope_locking → prd_awaiting_approval → prd_approved
                                   ↑ G1 (zorunlu)
       → rfc_drafting → rfc_awaiting_approval → rfc_approved
                              ↑ G2 (zorunlu)
       → tasks_generating → tasks_ready → executing → done
                                ↘ schema_awaiting_approval (G3)
                  executing ↘ budget_awaiting_approval (G7)
                  executing ↘ deploy_awaiting_approval (G6)
```

**Tüm durumlar:**

- Planlama: `intake`, `babel_processing`, `intake_dialog`, `stack_dialog`, `prd_dialog`, `prd_drafting`,
  `mvp_scope_locking`, `prd_awaiting_approval`, `prd_approved`
- Mimari: `rfc_drafting`, `rfc_awaiting_approval`, `rfc_approved`
- Yürütme: `tasks_generating`, `tasks_ready`, `schema_awaiting_approval`, `executing`,
  `budget_awaiting_approval`, `deploy_awaiting_approval`, `done`
- Özel: `failed`, `paused`
- Extend döngüsü (DONE sonrası): `extend_dialog`, `extend_prd_dialog`, `extend_prd_awaiting_approval`,
  `extend_prd_approved`, `extend_rfc_drafting`, `extend_rfc_awaiting_approval`, `extend_rfc_approved`

**Geri adımlar yasaldır** (çoğu durumda): `prd_awaiting_approval → prd_drafting`,
`mvp_scope_locking → prd_dialog`, `rfc_awaiting_approval → rfc_drafting`, `executing → paused`,
`paused → birçok durum`. Bir durumu elle ayarlamak meşrudur: `ortim advance <durum>`.

**Duraklat / devam et:** `ortim advance paused --note "..."` herhangi bir aktif durumdan duraklatır;
`paused`'tan birçok duruma geri dönebilirsin.

> **`failed` terminaldir** — oradan çıkış yoktur; çalışma alanını yeniden başlatman gerekir (§16.9).

---

<a name="9-yurutme"></a>
## 9. Görev yürütme: execute / run-all

### 9.1 Tek görev — `ortim execute`

```bash
ortim execute T-003
ortim execute T-005 --max-attempts 3        # reddedildikten sonra azami deneme (varsayılan 3)
ortim execute T-007 --human-reviewed        # hassas (auth/pii/payment) görevde insan onayı sinyali
```

- `--max-attempts N` (varsayılan 3): Reddedilince Worker'a kaç kez daha şans verilir. Her denemede
  Reviewer geri bildirimi prompt'a enjekte edilir.
- `--human-reviewed`: Faz 1.5. `sensitive_categories` (auth/pii/payment) etiketli görevler, Reviewer'dan
  geçseler bile bu bayrak olmadan `AWAITING_HITL`'e düşer. Bayrak, "insan inceledi" sinyalidir.

### 9.2 Tüm DAG — `ortim run-all`

```bash
ortim run-all                              # tüm fazlar, sıralı
ortim run-all --phase 1                    # yalnız faz ≤ 1 (MVP) görevleri
ortim run-all --continue-on-fail           # bir görev düşse de devam et (varsayılan: dur)
ortim run-all --parallel --max-workers 4   # parti içi paralel (git worktree gerektirir)
ortim run-all --max-attempts 3
```

Seçenekler:
- `--stop-on-fail` (varsayılan) / `--continue-on-fail`: Bir görev `FAILED`/`AWAITING_HITL`'e düşünce
  dur ya da devam et.
- `--parallel` / `--sequential` (varsayılan): Paralel mod, bir parti içindeki görevleri
  ThreadPoolExecutor + git worktree ile koşturur; merge'ler seridir, status kayıtları kilit altında.
  **Gereksinim:** PATH'te `git` ve `ORTIM_GIT_ENABLED != false`.
- `--max-workers N` (varsayılan 4): Paralel modda azami iş parçacığı.
- `--phase N`: `scope.json`'da `phase > N` işaretli görevler atlanır (DAG'da kalır, `PENDING` olurlar).

**Reviewer zinciri (her görev):** Code → Security → Test → Perf. Verdict'ler kural-şekillidir; `unverifiable`
(doğrulanamaz) `pass`'tan farklı ele alınır — eksik bir test runner sahte onaya yol açmaz, ayrı bir moda düşer.

> **Durum — paralel mod git yok diye çalışmıyor:** `GitNotAvailable` görürsen ya git'i kur ya da
> `--sequential` kullan.

> **Durum — bir görev AWAITING_HITL'e takıldı:** §16.2'deki beş etikete (sandbox/criterion/test_infra/
> security_veto/criteria_design) göre teşhis et ve kurtar.

---

<a name="10-gozlem"></a>
## 10. Gözlemlenebilirlik ve denetim

```bash
ortim status                  # state + geçmiş
ortim tasks                   # görev DAG'ı + durumlar
ortim gates                   # açık HITL kapıları (G1–G7) + bütçe
ortim states                  # tüm state machine + yasal geçişler
ortim budget --by-provider    # token + USD, sağlayıcı bazında
ortim retro                   # denetim kaydı üzerinden çok-eksenli özet (maliyet/retry/HITL)
ortim drift-check             # RFC ↔ DAG ↔ status ↔ audit hizalaması
ortim audit-verify            # hash zincirini yürü, kurcalamayı işaretle
ortim show --artifact rfc     # bir artefaktı yazdır (intent|stack|prd|scope|current)
```

**Denetim kaydını elle incelemek** (Project Mode):

```bash
type .ortim\audit.jsonl                 # Windows — tüm kayıt
findstr "T-005" .ortim\audit.jsonl      # Windows — göreve göre filtrele
# cat .ortim/audit.jsonl                # Unix
# grep "T-005" .ortim/audit.jsonl       # Unix
```

Pool legacy'de denetim kaydı `workspaces/<id>/audit.jsonl` altındadır.

> **`audit-verify` ne işe yarar:** Her LLM çağrısı, state geçişi, kapı kararı ve hook çıktısı hash-zincirli
> JSONL'e iner. `audit-verify` zinciri baştan sona yürür; bir satır değiştirilmiş/silinmişse tespit eder.
> Regüle sektörlerde (KVKK/finans) bu, "ne oldu, neden oldu" sorusuna savunulabilir cevaptır.

---

<a name="11-iterasyon"></a>
## 11. İterasyon: refine / scope / extend

### 11.1 `ortim refine` — diyalog içi düzeltme

Aktif diyalog durumunun ajanını geri bildirimle yeniden çağırır:

```bash
ortim refine "must-have özelliklere etiketleme ekle"
ortim refine "..." --force        # tur sınırını kasıtlı aş
```

> **Durum — tur sınırı:** Bir diyalog durumunda çok fazla refine yaptıysan sistem seni durdurur; gerçekten
> devam etmek istiyorsan `--force`.

### 11.2 `ortim scope` — MVP kapsamı

§5 Adım 2'ye bak. `--show / --lock / --reset / --set-phase` seçenekleriyle faz/öncelik atanır.

### 11.3 `ortim extend` — DONE projeye yeni özellik

```bash
ortim extend "kullanıcılara avatar yükleme ekle"   # proje DONE olmalı
ortim extensions                                    # extend döngü geçmişi
```

Extend, ilk akışı taklit eder (niyet → PRD → **G1 (döngü N)** → RFC → **G2 (döngü N)** → DAG → exec) ama
StackAnalyst'i atlar (LockedStack sonsuza dek kilitli) ve PRD/RFC'yi tam yeniden yazmak yerine **ekleme-yalnız**
bölüm olarak işler. Mevcut DONE görevler DONE kalır; yalnız yeni `PENDING` görevler çalışır.

> **Durum — stack'le çelişen özellik:** ExtenderAgent bir `BLOCKED-STACK` işareti üretirse hiçbir bölüm
> yazılmaz ve sen bilgilendirilirsin; özelliği kilitli stack'e uyacak şekilde yeniden ifade et.

---

<a name="12-saglayici"></a>
## 12. Çoklu sağlayıcı (LLM) yönlendirmesi

Ortim her ajan rolünü kendi sağlayıcısına yönlendirebilir. Çoğu üretim kurulumu bütçe için **DeepSeek**
kullanır; yargı önemli olduğunda Architect ve Security Reviewer'ı **Anthropic**'e yönlendirir. Anahtar yoksa
yerel **Ollama**.

**Üç yöntem (öncelik sırasıyla):**

```bash
# 1) Çağrı başına override — en yüksek öncelik
ortim run --provider ollama --model qwen2.5-coder:7b
ortim demo --provider ollama

# 2) Ortam / .env değişkeni
#   ARCHITECT_PROVIDER=anthropic
#   SECURITY_REVIEWER_PROVIDER=anthropic
#   WORKER_PROVIDER=anthropic   WORKER_MODEL=claude-opus-4
#   LLM_PROVIDER=deepseek       (tüm roller için varsayılan)

# 3) Kalıcı config / rol override
ortim config set-role architect --provider anthropic
ortim config setup-local      # yerel Ollama bağla
```

**Yaklaşık maliyetler** (TR brief, 6–8 görev, %80+ ilk-deneme onayı):
- DeepSeek-only: planlama başına **$0.02–0.05**, görev başına **$0.02–0.04**.
- Hibrit (Architect + SecRev Anthropic): **$0.05–0.10** planlama, **$0.04–0.08** görev.
- Ollama-only: **$0.00** (yerel; verim donanıma bağlı).

Desteklenen sağlayıcılar: `anthropic`, `deepseek`, `ollama` (yerel), herhangi bir OpenAI-uyumlu endpoint.

> **Durum — bir görev 3 denemede çözülemiyor:** Worker LLM'i yükselt — `WORKER_PROVIDER=anthropic` veya
> `WORKER_MODEL=claude-opus-4`. Bazen sorun implementasyon değil, özellik tasarımıdır (§16.3).

---

<a name="13-workspace"></a>
## 13. Workspace (çalışma alanı) yönetimi

Her yerden çalışır:

```bash
ortim ls                               # tüm bilinen çalışma alanları; '*' = aktif
ortim use <id|name>                    # aktif işaretçiyi ayarla (registry-destekli)
ortim status -p <id>                   # belirli bir çalışma alanını hedefle
ortim workspace show <id>
ortim workspace archive <id>           # arşivle (mutasyon engellenir)
ortim workspace unarchive <id>
ortim workspace migrate                # eski layout'u güncel düzene taşı
ortim workspace doctor                 # registry / layout sorunlarını teşhis et
ortim workspace cleanup --older-than 30 --archived-only --yes
```

> **Durum — arşivli çalışma alanında mutasyon:** Arşivli bir projede `run`/`advance` gibi mutasyon
> denemeleri engellenir. Önce `ortim workspace unarchive <id>`.

> **Durum — eski pool çalışma alanları:** Komutlar pool ID'lerini hem konumsal argüman hem `-p` bayrağıyla
> çözer. Project Mode'a taşımak için `ortim workspace migrate`.

---

<a name="14-skill"></a>
## 14. Skill (proje-özel desen) sistemi

Skill'ler, Worker/Reviewer prompt'larına proje-özel desenler enjekte eder (örn. Docker deploy şablonları,
güvenlik inceleme kontrol listeleri). Yalnız brief'te ilgili tetik (anahtar kelime + tier + app_class)
varsa devreye girer; varsayılan olarak açık değildir.

```bash
ortim skill list              # mevcut skill'ler
ortim skill show <name>       # bir skill'in içeriği
```

Kendi skill'ini yazmak için: [`docs/skills/authoring-guide.md`](../skills/authoring-guide.md)
(skill anatomisi: frontmatter, tetikler, gövde; resolver semantiği).

---

<a name="15-cloud"></a>
## 15. Ortim Cloud — yönetişim (önizleme)

Denetim izi yerel-öncelikli ve hesapsız çalışır. Paylaşılan yönetişime ihtiyaç duyan ekipler için
`ortim cloud`, boru hattını **değiştirmeden** üstüne bir **Observer (gözlemci) katmanı** ekler.

```bash
ortim cloud login you@org.com    # cloud.ortim.dev'e kimlik doğrula
ortim cloud status               # bağlantı + giriş durumu
ortim cloud orgs                 # üyesi olduğun organizasyonlar
ortim cloud link --org <id>      # bu çalışma alanını bir org projesine bağla
ortim cloud sync                 # redakte denetim metadata'sını gönder (offline-güvenli)
ortim cloud policy               # org yönetişim politikasını çek + göster
ortim cloud logout
```

**Önemli güvenceler:**
- **Ne senkronlanır:** yalnız redakte denetim metadata'sı + boru hattı durumu. **Kaynak kod asla
  gönderilmez**; PII makineyi terk etmeden önce redakte edilir.
- **Offline-güvenli:** bulut erişilemezse `cloud sync` uyarı basıp **exit 0** döner — yerel hat asla
  bloke olmaz; imleç (cursor) ilerlemez.
- **Politika dayatma:** bir org politikası zorunlu kapıları, izinli sağlayıcı listesini ve bütçe cap'ini
  sabitleyebilir; CLI bunu çeker ve **yerel olarak** dayatır.

> **Durum — politika ihlali:** İzinsiz bir sağlayıcı veya zorunlu bir kapıyı baypas eden run,
> `policy_violation` denetim olayı + `Exit(2)` ile reddedilir. Çözüm mesajı her ihlal için yazdırılır.

> **Durum — free-tier / abonelik yok:** Politika boş döner → enforcement kapalı (yerel-degrade). Bu
> tasarım gereğidir; abonelik sona erince de aynı şekilde degrade olur.

Tam yük şekli + tehdit modeli: [`docs/cloud.md`](../cloud.md).

---

<a name="16-sorun-giderme"></a>
## 16. Sorun giderme ve kurtarma — her hata durumu

> **Önce teşhis et, sonra müdahale et.** Proje dizininden:
> ```bash
> ortim status        # state machine + geçmiş
> ortim retro         # maliyet + retry oranı + HITL yükseltmeleri
> ortim drift-check   # RFC ↔ DAG ↔ status hizalaması
> ```
> `state.json` her zaman gerçeğin kaynağıdır; doğrudan açmak meşrudur.

### 16.1 Hata-durum haritası (hızlı tablo)

| Belirti | Bölüm |
|---|---|
| Görev `AWAITING_HITL`'e takıldı | §16.2 |
| Worker 3 denemede başarısız | §16.3 |
| G7 bütçe kapısı tetiklendi | §16.4 |
| Eski workspace yüklenemiyor (şema migration) | §16.5 |
| Architect yanlış stack seçti | §16.6 |
| Sandbox yazımı reddediyor (`module_scope` ihlali) | §16.7 |
| "Cannot transition" hatası | §16.8 |
| Hiçbir şey çalışmıyor — sıfırla | §16.9 |

### 16.2 Görev `AWAITING_HITL`'e takıldı

`.ortim/task_status.json`'ı aç; her görevin durumu, `last_review_reasons` ve retry sayısı orada. Beş etiket:

| Etiket | Anlamı | Kurtarma |
|---|---|---|
| `[sandbox]` | Worker `module_scope` dışına yazdı | §16.7 |
| `[criterion]` | Bir kabul kriteri başarısız | aşağıda (a) |
| `[test_infrastructure_unavailable]` | Test runner eksik/bozuk | aşağıda (b) |
| `[security_veto]` | SecurityReviewer hard veto verdi | aşağıda (c) |
| `[criteria_design_failure]` | Kriterin kendisi muğlak | aşağıda (d) |

**(a) Kriter başarısız — Worker karşılayamıyor.** Önce nerede yetersiz kaldığını anla (audit + git log),
sonra ya görevi yeniden çalıştır (önerilen) ya da `.ortim/tasks/T-NNN.md`'deki kabul kriterlerini sıkılaştır:

```bash
ortim execute T-005 --max-attempts 3
```

Elle kod düzeltmek Worker'ı baypas eder ama Reviewer zinciri yine çalışır; denetim geçmişini tutarsız
bırakabileceği için yeniden çalıştırmak tercih edilir.

**(b) `test_infrastructure_unavailable`.** Worker test yazdı ama runner sıfır-dışı döndü:

```bash
type .ortim.env            # ORTIM_TEST_CMD doğru mu? (Windows)
npm install                # veya pip install -r requirements.txt
npx vitest run             # komutu elle dene
ortim execute T-005        # çalışıyorsa yeniden koştur
```

`ORTIM_TEST_CMD` yanlışsa `.ortim.env`'i düzelt + yeniden koştur.

**(c) `security_veto`.** SecurityReviewer hard veto verdi (gömülü secret, SQL injection, eval, ...):

```bash
findstr "T-005" .ortim\audit.jsonl | findstr "security"   # Windows
```

Verdict somut sorunu adlandırır. Ya `.ortim/tasks/T-005.md`'ye açık bir kriter ekle (örn. "auth secret
ortam değişkeninden okunur") ve yeniden koştur, ya da kodu elle düzeltip ilerle.

**(d) `criteria_design_failure`.** Orchestrator muğlak bir kriter üretti (Hard Rule 10 — "okunabilir",
"kullanıcı-dostu" gibi belirsiz kelimeler yasak). `.ortim/tasks/T-005.md`'yi elle düzelt + yeniden koştur.
Aynı desen tekrar ederse sistemik çözüm `agents/orchestrator.md`'deki yasak-kelime listesini sıkılaştırmaktır.

### 16.3 Worker 3 denemede başarısız

3 deneme varsayılan tavandır; state `AWAITING_HITL`'e geçer. Yeni 3 deneme için:

```bash
ortim execute T-005 --max-attempts 3
```

Yine olmuyorsa sistem şunu söylüyordur: kriter muğlak, kod Worker LLM için fazla karmaşık, ya da görev
fazla geniş. Çözümler:
- **Görevi böl** — `.ortim/tasks/T-005.md`'yi elle 2–3 küçük göreve ayır; `.ortim/task_dag.json`'ı yamala.
- **Worker LLM'i yükselt** — `.env`'de `WORKER_PROVIDER=anthropic` veya `WORKER_MODEL=claude-opus-4`.
- **Reviewer geri bildirimini PRD/RFC'ye taşı** — bazen özellik tasarımının kendisi yanlıştır.

### 16.4 G7 bütçe kapısı tetiklendi

State `BUDGET_AWAITING_APPROVAL`, `run-all` durur. Üç seçenek:

```bash
# Devam et (aşımı kabul et)
ortim advance budget_approved --note "T-005–T-008 için aşım onaylandı"

# Önce cap'i yükselt
#   .env: ORTIM_BUDGET_CAP_USD=5.00  → yeni terminal aç (env yeniden okunsun)
ortim advance budget_approved

# Duraklat
ortim advance paused --note "bütçe aşıldı; inceleniyor"
```

Duraklattıktan sonra `ortim retro` harcamayı kategoriye böler: Architect retry mi, bir görev tüm retry
bütçesini mi yaktı, PRD/RFC çok mu büyük (yüksek token)?

### 16.5 Eski workspace yüklenemiyor (şema migration)

`pydantic ... ValidationError` görürsen, diskteki `state.json`/`scope.json` eski şemayla yazılmış. Pydantic
varsayılanları çoğu eski dosyayı uyumlu kılar; yine de sert hata alırsan:

1. **Yedekle:** `xcopy /E /I .ortim .ortim.bak` (Windows) / `cp -r .ortim .ortim.bak` (Unix).
2. **JSON'u elle düzenle** — eksik alanları ekle (örn. `"user_stack_hints": []`, `"phase": 1`).
3. **Migration'ı logla:** `echo "$(date) — elle migration" >> .ortim/MIGRATIONS.md`.

> Otomatik migration aracı Faz 4'e ertelendi; şimdilik elle.

### 16.6 Architect yanlış stack seçti

RFC §4 istemediğin bir teknolojiyi adlandırıyor (örn. "SQLite dedim, PostgreSQL yazdı"):

```bash
type .ortim\intent.json | findstr "user_stack_hints"   # Windows
```

- **Boş:** Babel ipucu çıkaramamış → brief'i somutlaştır, teknolojiyi açıkça adlandır ("PostgreSQL",
  "SQLite", "FastAPI") — genel terim ("veritabanı", "API") değil.
- **Dolu ama RFC override etmiş:** Faz 1.2 B-2 düzeltmesi bunu kapsamalı; hâlâ görüyorsan tekrar-üretimle
  issue aç.

**Düzelt:**

```bash
ortim advance rfc_drafting && ortim run        # Architect yeniden üretir
# veya .ortim/RFC.md §4'ü elle düzelt:
ortim advance rfc_awaiting_approval
ortim advance rfc_approved --note "stack bölümü elle düzeltildi"
```

### 16.7 Sandbox yazımı reddediyor (`module_scope` ihlali)

`.ortim/audit.jsonl`'de `executor_sandbox_violation: Worker tried to write 'auth/foo.ts' but module_scope
is 'tasks'`. Worker, görevin `module_scope`'u dışındaki bir modüle dosya yazmaya çalıştı; sandbox doğru
reddetti (L1 modül sınırı savunması). Önce sandbox-feedback retry'ın çalışmasına izin ver; 3 denemede aynı
ihlal sürerse:

```bash
# Görev brief'ini beklenen yolu açıkça verecek şekilde düzelt
#   .ortim/tasks/T-005.md → "`tasks/repository.ts` dosyasını oluştur (auth/... DEĞİL)"
ortim execute T-005
# veya DAG'ı yeniden üret:
ortim advance rfc_approved && ortim run
```

### 16.8 "Cannot transition" hatası

```
InvalidTransition: Cannot transition prd_drafting -> rfc_drafting.
Allowed: ['failed', 'mvp_scope_locking']
```

State machine seni kasıtlı engelliyor (bir kapıyı atlamaya çalıştın). Yasal geçişleri listele:

```bash
ortim states
```

Geri geçişler çoğu durumda yasaldır (yukarıda §8). Bir durumu elle ayarlamak meşrudur:
`ortim advance <durum>`.

### 16.9 Hiçbir şey çalışmıyor — çalışma alanını yeniden başlat

```bash
# Seçenek A: dizini koru, yalnız metadata'yı sıfırla
#   Windows: .ortim'i .ortim.broken-YYYYMMDD olarak yeniden adlandır
ortim init "$(cat brief.txt)"          # taze .ortim/

# Seçenek B: registry'de arşivle, yeni dizin aç
ortim workspace archive <id>
mkdir ~/dev/cool-project-v2 && cd ~/dev/cool-project-v2
ortim init "$(cat brief.txt)"
```

**Eski çalışma alanından taşınabilir:** `.ortim/intent.json`, `PRD.md`, `RFC.md` (elle kopyala, sonra
kapılardan ilerlet). **Taşıma:** `state.json` (şema değişmiş olabilir), `audit.jsonl` (yeni projenin hash
zincirini bozar).

### 16.10 Yardım isterken ekle

`ortim doctor` çıktısı + `ortim status`/`retro`/`drift-check` + `.ortim/audit.jsonl`'nin son 30 satırı (PII
temizle) + tekrar-üretim brief'i. GitHub: [github.com/orhanurullah/ortim/issues](https://github.com/orhanurullah/ortim/issues)

---

<a name="17-maliyet"></a>
## 17. Maliyet yönetimi

- **Bütçe cap'i koy:** `.env`'de `ORTIM_BUDGET_CAP_USD=2.00`. Aşılırsa G7 kapısı durdurur (§16.4).
- **Sağlayıcıyı role göre ayarla:** Pahalı yargı (Architect, Security Reviewer) premium; gerisi DeepSeek.
  En büyük tasarruf burada (§12).
- **Token israfını azalt:** Babel, TR/diğer brief'i pahalı çağrıdan önce yapısal niyete çevirir; "premium"
  modeller Architect + Security Reviewer'a saklanır.
- **Nereye gittiğini gör:** `ortim budget --by-provider` ve `ortim retro` — harcama kategorisi (Architect
  retry, görev retry bütçesi, büyük PRD/RFC).
- **Yerel = $0:** Ollama ile planlama/yürütmeyi tamamen yerel koş (verim donanıma bağlı).

---

<a name="18-cheatsheet"></a>
## 18. Hızlı referans (cheatsheet)

```bash
# Kurulum + sağlık
pip install ortim
ortim config init
ortim doctor
ortim demo                                 # API anahtarsız tur

# Yeni proje (greenfield)
mkdir ~/dev/cool && cd ~/dev/cool
ortim init "<brief>"                       # --app-class web|mobile|desktop ile kilitleyebilirsin
ortim run                                  # Babel + Analyst
ortim scope --lock                         # kapsamı kilitle → G1
ortim show --artifact prd
ortim advance prd_approved                 # G1
ortim run                                  # Architect → RFC
ortim show --artifact rfc
ortim advance rfc_approved                 # G2
ortim run                                  # Orchestrator → tasks_ready
ortim run-all --phase 1                    # MVP görevleri

# Brownfield
ortim init "<brief>"                       # manifest → otomatik brownfield
ortim inspect

# Gözlem + bütünlük
ortim status / tasks / gates / states
ortim budget --by-provider / retro / drift-check / audit-verify
ortim show --artifact intent|stack|prd|scope|rfc|current

# İterasyon
ortim refine "<geri bildirim>"
ortim extend "<yeni özellik>"              # DONE proje → delta döngüsü
ortim extensions

# Kapı devamı
ortim advance prd_approved | rfc_approved | schema_approved | budget_approved | deploy_approved
ortim advance paused --note "..."

# Tek görev / kurtarma
ortim execute T-003 [--max-attempts 3] [--human-reviewed]

# Çalışma alanı (her yerden)
ortim ls / use <id|name>
ortim workspace archive|unarchive|cleanup|migrate|doctor

# Sağlayıcı override
ortim run --provider ollama --model qwen2.5-coder:7b
ortim config set-role architect --provider anthropic

# Cloud (önizleme)
ortim cloud login <email> / link --org <id> / sync / policy

# Tier scorer (API anahtarsız, deterministik)
ortim score-tier --state --auth --scale large --compliance KVKK,GDPR --audit-heavy
```

---

İlgili dokümanlar:
- [Öğretici (TR)](tutorial/getting-started.md) · [Kurtarma runbook (TR)](runbook/failure-recovery.md)
- [Neden Ortim (EN)](../why-ortim.md) · [Mimari spec](../../Ortim_Architecture.md) · [Cloud (EN)](../cloud.md)
- [Changelog](../../CHANGELOG.md)
