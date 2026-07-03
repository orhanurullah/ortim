# Ortim — Failure Recovery Cookbook (TR arşiv)

> **English-canonical:** The English version at [`docs/runbook/failure-recovery.md`](../../runbook/failure-recovery.md) is the canonical source. This Turkish translation is preserved for historical reference and may lag behind. Yeni özellikler için İngilizce sürümü esas alın.

---

> Bir şey ters gittiğinde ne yapacağın listesi. Tutorial'ı bitirdiysen ve gerçek bir projede takıldıysan buradan başla.

İçindekiler:
0. [Project mode komut hızlı referans](#0-project-mode-komut-hızlı-referans)
1. [Senin tarafında durum tespiti](#1-senin-tarafında-durum-tespiti)
2. [Task AWAITING_HITL'e takıldı](#2-task-awaiting_hitle-takıldı)
3. [Worker 3 deneme sonra başarısız oldu](#3-worker-3-deneme-sonra-başarısız-oldu)
4. [G7 budget gate açıldı — devam edemiyorum](#4-g7-budget-gate-açıldı--devam-edemiyorum)
5. [Eski workspace yüklenmiyor (schema migration)](#5-eski-workspace-yüklenmiyor-schema-migration)
6. [Architect yanlış stack seçti](#6-architect-yanlış-stack-seçti)
7. [Sandbox çağrısı reject ediyor (`module_scope` ihlali)](#7-sandbox-çağrısı-reject-ediyor-module_scope-i̇hlali)
8. [State machine "Cannot transition" hatası](#8-state-machine-cannot-transition-hatası)
9. [Hiçbir şey çalışmıyor — workspace'i sıfırdan başlat](#9-hiçbir-şey-çalışmıyor--workspaceyi-sıfırdan-başlat)

---

## 0. Project mode komut hızlı referans

Ortim 0.9'dan itibaren komutlar **cwd-aware**: ilgili workspace'i çalıştığın dizinden (veya parent'larından) keşfeder. Aşağıdaki örneklerde proje dizinin içinden çalıştığın varsayılır.

| Komut sınıfı | Pattern | Örnek |
|---|---|---|
| Read komutları (`status`, `tasks`, `inspect`, `gates`, `show`, `extensions`, `retro`, `drift-check`) | `<cmd>` veya `<cmd> <id>` (legacy pool fallback) | `ortim status` · `ortim retro` |
| Tek-mutating (`run`, `run-all`, `refine`, `lock`, `scope`, `budget`, `rescan`, `baseline`) | `<cmd>` veya `<cmd> <id>` (legacy pool fallback) | `ortim run` · `ortim scope --lock` |
| Çoklu-arg (`advance`, `execute`, `extend`) | `<cmd> <other-arg> [-p <id>] ...` | `ortim advance prd_approved --note "x"` |
| Workspace yönetimi | `ortim ls` · `ortim use <id\|name>` · `ortim workspace {show,archive,cleanup,doctor,migrate}` | `ortim use cool-project` |

Farklı dizinden çalışıyorsan veya birden çok workspace varsa hepsinde `--project / -p <id>` flag'i çalışır. Pool legacy workspace ID'leri de positional/flag olarak resolve edilir.

Metadata path'i: project mode'da `<your-dir>/.ortim/` (state.json, audit.jsonl, tasks/, ...). Pool mode'da `workspaces/<id>/`.

---

## 1. Senin tarafında durum tespiti

Sorunu anlamadan müdahale etme. Proje dizininden çalıştığını varsayarak şu üç komut neredeyse her teşhisi açar:

```bash
ortim status        # state machine + history
ortim retro         # cost + retry rate + HITL escalations
ortim drift-check   # RFC ↔ DAG ↔ status alignment
```

Daha derin:

```bash
# Audit log (project mode: .ortim/audit.jsonl)
type .ortim\audit.jsonl                       # Windows
# cat .ortim/audit.jsonl                      # Unix

# Task durumlarının tek-bakış tablosu
ortim tasks

# Belirli bir task'ın history'si — audit log'u task id ile filtrele
findstr "T-005" .ortim\audit.jsonl            # Windows
# grep "T-005" .ortim/audit.jsonl             # Unix

# Task'ın son review verdict'i + retry count'u — task_status.json sidecar
type .ortim\task_status.json | findstr -A 20 "T-005"   # quick peek
```

Pool legacy workspace ise audit log `workspaces/<id>/audit.jsonl` veya `runtime/audit/<date>.jsonl`'de.

`state.json` her zaman ground truth — project mode'da `.ortim/state.json`'u, pool mode'da `workspaces/<id>/state.json`'u manuel okumak da meşru bir adım.

---

## 2. Task AWAITING_HITL'e takıldı

### Belirti

`ortim tasks` çıktısında bir veya birden çok task `AWAITING_HITL` durumunda. `ortim run-all` bu state'te kendiliğinden durur.

### Sebep tespiti

`.ortim/task_status.json`'u aç (project mode) — her task için status + `last_review_reasons` + retry count tutar. Pool mode'da `workspaces/<id>/task_status.json`. Üç ana kategori:

| Tag | Anlam | Çözüm yolu |
|---|---|---|
| `[sandbox]` | Worker scope dışına yazdı | §7'ye git |
| `[criterion]` | Acceptance criterion karşılanmadı | Aşağıya bak |
| `[test_infrastructure_unavailable]` | Test runner yok/kırık | §2.3'e bak |
| `[security_veto]` | SecurityReviewer hard veto | §2.4'e bak |
| `[criteria_design_failure]` | Criterion'un kendisi belirsiz | §2.5'e bak |

### 2.1 Criterion karşılanmadı — Worker düzeltemiyor

Önce manuel olarak kodun nerede yetersiz kaldığını anla:

```bash
# Worker'ın son output'u + Reviewer verdict'i — audit log'da
findstr "T-005" .ortim\audit.jsonl                                  # Windows
# grep '"T-005"' .ortim/audit.jsonl | jq .                          # Unix

# Mevcut kod durumu için cwd'deki branch'i tara
git log --all --oneline -- '*T-005*'
```

Kod yazılmış ama beklenti karşılanmıyorsa:

**Task'ı yeniden koş (önerilen)**

```bash
ortim execute T-005 --max-attempts 3
```

> Worker'ın görmediği bir sinyali manuel feedback olarak iletmek için `.ortim/tasks/T-005.md`'i aç ve Acceptance Criteria'yı netleştir. Sonra `ortim execute T-005`.

**Kodu manuel düzeltmek istiyorsan** task'ı çalıştırmadan kod değişikliğini commit'le; Reviewer akışı yine de çalışır (Worker'a "skip code emission, use existing" sinyali şu an yok — manuel commit + reset ile karışıklığa girersen task'ın audit history'si tutarsız kalır).

### 2.2 Criterion belirsiz — Reviewer doğru reddetti

Eğer reviewer verdict'i `status: unverifiable` + mode `criteria_design_failure` ise Orchestrator yanlış criterion emit etmiş demektir (Hard Rule 10 ihlali — "readable", "user-friendly" gibi belirsiz kelimeler).

Çözüm: criterion'u manuel düzenle.

```bash
# .ortim/tasks/T-005.md aç, "Acceptance Criteria" listesini düzelt
# Belirsiz: "stdout shows todos in readable format"
# Net: "stdout matches /^(\[ \] [0-9a-f-]{36} .+\n)*$/"

ortim execute T-005
```

Veya DAG'ı yeniden generate et (daha temiz ama pahalı):

```bash
ortim advance rfc_approved
ortim run            # Orchestrator yeniden çağrılır
```

### 2.3 `test_infrastructure_unavailable`

Worker test yazdı ama test runner çağrısı exit ≠ 0 (test runner missing veya broken).

```bash
# .ortim.env içeriği (project mode: cwd kökünde)
type .ortim.env                          # Windows
# cat .ortim.env                         # Unix
# ORTIM_TEST_CMD=npx vitest run
```

Pool mode'da `workspaces/<id>/.ortim.env`.

Test komutu doğru mu, ilgili package install edildi mi?

```bash
npm install        # veya pip install -r requirements.txt
# elle test komutunu koş
npx vitest run
```

Komut OK ise:

```bash
ortim execute T-005
```

`ORTIM_TEST_CMD` yanlışsa `.ortim.env` dosyasını elle düzelt + execute.

### 2.4 `security_veto`

SecurityReviewer hard veto verdi (hardcoded secret, SQL injection, eval, vs.). Audit log'da verdict'in detayını gör:

```bash
findstr "T-005" .ortim\audit.jsonl | findstr "security"   # Windows
# grep '"T-005"' .ortim/audit.jsonl | grep security        # Unix
```

Verdict somut bir issue gösterir. `.ortim/tasks/T-005.md`'deki criterion'u (örn. "auth uses environment variable") açıkça yaz → `ortim execute T-005`.

### 2.5 `criteria_design_failure`

Orchestrator'ın Hard Rule 10 ihlali kaçırdığı criterion. Manuel düzelt, reset. `agents/orchestrator.md` Hard Rule 10'da banned-word listesi var; benzer pattern'ler için Orchestrator prompt'unu sertleştirmek de bir adım (sistemik fix).

---

## 3. Worker 3 deneme sonra başarısız oldu

3 deneme = max retry. State `AWAITING_HITL`'e geçer (§2'ye bak). Yeniden 3 deneme istemen için:

```bash
ortim execute T-005 --max-attempts 3
```

**Üç deneme bitti, hâlâ başarısız** = sistem sana sinyal veriyor: ya criterion belirsiz, ya kod karmaşık, ya Worker LLM'in kapasitesini aşıyor.

Çareler:
- Task'ı **böl** — `.ortim/tasks/T-005.md`'yi 2-3 daha küçük task'a manuel parçala, `.ortim/task_dag.json`'u elle güncelle.
- Architect'i daha güçlü provider'a al — `WORKER_PROVIDER=anthropic` veya `WORKER_MODEL=claude-opus-4`.
- Reviewer'ın geri bildirimini PRD/RFC'ye geri yedir — bazen feature'ın kendisi yanlış tasarlanmış.

---

## 4. G7 budget gate açıldı — devam edemiyorum

### Belirti

```
G7 — Budget cap breached.
Spent $2.34 / cap $2.00 (117%)
```

State: `BUDGET_AWAITING_APPROVAL`. `run-all` durur.

### Üç seçenek

**Devam et (overage'i kabul ederek):**

```bash
ortim advance budget_approved --note "approved overage for T-005-T-008"
```

**Cap'i artır (önce):**

```bash
# .env dosyasında
ORTIM_BUDGET_CAP_USD=5.00
# yeni terminal aç (env reload)
ortim advance budget_approved
```

**Durdur:**

```bash
ortim advance paused --note "budget exceeded; reviewing"
```

Pause sonrası `ortim retro` ile maliyet breakdown'u: hangi kategori spike ettin?
- Architect retry'a girdi mi (drift validator)?
- Worker bir task için 3× retry yaptı mı?
- RFC çok mu büyük (token sayısı)?

---

## 5. Eski workspace yüklenmiyor (schema migration)

### Belirti

```
pydantic_core._pydantic_core.ValidationError: ...
```

State.json veya scope.json eski şema ile yazılmış, yeni kod schema bekliyor.

### Çözüm

Pydantic `default` field'ları geriye uyumlu olmalı (eski JSON'lar yeni field'ları default değerle yükler). Hâlâ patlıyorsa:

1. **Workspace yedeği al:**
   ```bash
   # Project mode: sadece metadata'yı yedekle
   cp -r .ortim .ortim.bak                       # Unix
   xcopy /E /I .ortim .ortim.bak                 # Windows
   # Pool mode: tüm workspace dizinini yedekle
   # cp -r workspaces/<id> workspaces/<id>-backup
   ```

2. **JSON dosyasını manuel düzelt** — eksik field'ları ekle:
   ```json
   // Pre-1.1 state.json'a Faz 1.1 sonrası
   {
     ...
     "user_stack_hints": [],
     "phase": 1
   }
   ```
   Project mode'da `.ortim/state.json`'u, pool mode'da `workspaces/<id>/state.json`'u düzelt.

3. **Migration logu yaz:**
   ```bash
   echo "$(date) — manual migration v0.7 → v0.8" >> .ortim/MIGRATIONS.md
   ```

> **Otomatik migration tooling Faz 4'e ertelendi** (roadmap 3.2 → Faz 4). Şu an manuel.

---

## 6. Architect yanlış stack seçti

### Belirti

RFC §4'te brief'te söylemediğin bir teknoloji var (örn. "SQLite dedim, PostgreSQL yazıldı").

### Tespit

```bash
type .ortim\intent.json | findstr "user_stack_hints"   # Windows
# cat .ortim/intent.json | grep -A 10 user_stack_hints # Unix
```

`user_stack_hints` array boş mu, yoksa senin söylediklerini içeriyor mu?

**Boşsa:** Babel hint'lerini çıkaramamış. Brief'i daha açık yaz (örn. "PostgreSQL kullanalim" gibi açık isim, "veritabani" değil).

**Doluysa ama RFC ezdi:** Faz 1.2 B-2 fix bunu kapatıyor. Hâlâ oluyorsa bir bug — issue aç + reproduce et.

### Çözüm

State'i RFC_DRAFTING'e geri at, RFC.md'yi elle düzelt veya Architect'i yeniden çağır:

```bash
ortim advance rfc_drafting
ortim run
```

Veya direkt `.ortim/RFC.md`'yi düzenle + onayla:

```bash
# RFC.md'yi metin editöründe aç, §4'ü düzelt
ortim advance rfc_awaiting_approval
ortim advance rfc_approved --note "manually edited stack section"
```

---

## 7. Sandbox çağrısı reject ediyor (`module_scope` ihlali)

### Belirti

`audit.jsonl` içinde:
```
executor_sandbox_violation: Worker tried to write 'auth/foo.ts' but module_scope is 'tasks'
```

### Sebep

Worker DAG'da `module_scope: "tasks"` olan bir task için `auth/` altına yazmaya çalıştı — L1 module boundary ihlali. Sandbox doğru rejection yaptı.

İki olası kök neden:
- **Orchestrator bug:** task description'da iki modüle değen iş tanımlandı. DAG'ı yeniden generate etmek lazım.
- **Worker drift:** Architect ipucu vermesine rağmen Worker yanlış path seçti.

### Çözüm

İlk önce Item 15a sandbox feedback retry'ı çalıştırın — auto-retry pattern. Eğer 3 deneme sonra hâlâ aynı ihlal:

```bash
# task brief'i manuel düzelt — beklenen path'i açıkça yaz
# .ortim/tasks/T-005.md → "Create the file `tasks/repository.ts` (NOT auth/...)"
ortim execute T-005
```

Veya Orchestrator'ı yeniden çağır (DAG'ı yeniden üretir):

```bash
ortim advance rfc_approved
ortim run
```

---

## 8. State machine "Cannot transition" hatası

### Belirti

```
InvalidTransition: Cannot transition prd_drafting -> rfc_drafting.
Allowed: ['failed', 'mvp_scope_locking']
```

State machine doğru sebepten engelliyor — bir gate'i atlamaya çalışıyorsun.

### Çözüm

Geçerli transition'ları görmek için:

```bash
ortim states
```

Geri-adımlama meşru: Faz 1.1 sonrası şu back-step transition'lar çalışır:
- `prd_awaiting_approval` → `prd_drafting`
- `mvp_scope_locking` → `prd_dialog` veya `prd_drafting`
- `rfc_awaiting_approval` → `rfc_drafting`
- `executing` → `paused`
- `paused` → birçok state

Manuel state set etmek istersen `ortim advance <state>` doğrudan transition çalıştırır.

---

## 9. Hiçbir şey çalışmıyor — workspace'i sıfırdan başlat

Bazen en hızlı yol baştan başlamaktır.

**Project mode** (önerilen): mevcut workspace'i arşivle veya silme yerine yeni bir dizinden başlat.

```bash
# Opsiyon A: aynı dizinde tut, sadece metadata'yı sıfırla
mv .ortim .ortim.broken-$(date +%Y%m%d)         # Unix
# Windows: rename .ortim .ortim.broken-YYYYMMDD
ortim init "$(cat brief.txt)"                    # taze .ortim/ yarat

# Opsiyon B: registry'den arşivle, yeni dizinde aç
ortim workspace archive <id>
mkdir ~/dev/cool-project-v2 && cd ~/dev/cool-project-v2
ortim init "$(cat brief.txt)"
```

**Pool legacy** workspace ise:

```bash
mv workspaces/<id> workspaces/<id>-broken-$(date +%Y%m%d)
# Sonra yeni dizinde başlat:
mkdir ~/dev/cool-project && cd ~/dev/cool-project
ortim init "$(cat brief.txt)"
```

**Eski workspace'ten ne alırsın:**
- `.ortim/intent.json`, `.ortim/PRD.md`, `.ortim/RFC.md` — manuel kopyalama meşru, yeni state'lere advance et
- `.ortim/task_dag.json` — Orchestrator'ı yeniden çağırarak daha temiz

**Eski workspace'ten ne almaman gerekir:**
- `.ortim/state.json` — schema değişebilir
- `.ortim/audit.jsonl` — yeni hash chain'le karışmasın

---

## Yardım istemek için

Issue açarken şunları ekle:
- `ortim doctor` çıktısı
- `ortim status` + `ortim retro` + `ortim drift-check` (proje dizininden)
- audit log son 30 satır (`.ortim/audit.jsonl`; PII yokmuş gibi temizle)
- Tekrar üretim için kullandığın brief

GitHub: `https://github.com/orhanurullah/ortim/issues`

---

İlgili dokümanlar:
- [Tutorial](../tutorial/getting-started.md) — sıfırdan başlangıç
- [Architecture](../../../Ortim_Architecture.md) — sistem nasıl çalışır
- [Backlog](../../backlog.md) — bilinen açık item'lar
