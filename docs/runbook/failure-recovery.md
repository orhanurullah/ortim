# Ortim — Failure Recovery Cookbook

> Bir şey ters gittiğinde ne yapacağın listesi. Tutorial'ı bitirdiysen ve gerçek bir projede takıldıysan buradan başla.

İçindekiler:
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

## 1. Senin tarafında durum tespiti

Sorunu anlamadan müdahale etme. Şu üç komut neredeyse her teşhisi açar:

```bash
ortim status <id>       # state machine + history
ortim retro <id>        # cost + retry rate + HITL escalations
ortim drift-check <id>  # RFC ↔ DAG ↔ status alignment
```

Daha derin:

```bash
# Audit log son 50 event
type runtime\audit\$(date +%Y-%m).jsonl | findstr "<id>"   # Windows
# cat runtime/audit/$(date +%Y-%m).jsonl | grep "<id>"     # Unix

# Task durumlarının tek-bakış tablosu
ortim tasks <id>

# Belirli bir task'ın audit kaydı
ortim tasks <id> --task T-005 --verbose
```

`state.json` her zaman ground truth — workspace dizininden manuel okumak da meşru bir adım.

---

## 2. Task AWAITING_HITL'e takıldı

### Belirti

`ortim tasks <id>` çıktısında bir veya birden çok task `AWAITING_HITL` durumunda. `ortim run-all` bu state'te kendiliğinden durur.

### Sebep tespiti

```bash
ortim tasks <id> --task T-005 --verbose
```

`last_review_reasons` field'ına bak. Üç ana kategori:

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
# Worker'ın son output'u
ortim show <id> --artifact worker-output --task T-005

# Reviewer'ın verdict'i
ortim show <id> --artifact review --task T-005
```

İki seçenek:

**A) Kodu elle düzelt + advance**

```bash
cd workspaces/<id>
git checkout task/T-005
# kodu düzenle
git add . && git commit -m "manual fix for T-005"
ortim advance <id> --task T-005 done --note "manual completion"
```

**B) Task'ı yeniden koş**

```bash
ortim execute <id> T-005 --reset
```

`--reset` retry counter'ı sıfırlar ve Worker'a sıfırdan çağırır.

### 2.2 Criterion belirsiz — Reviewer doğru reddetti

Eğer reviewer verdict'i `status: unverifiable` + mode `criteria_design_failure` ise Orchestrator yanlış criterion emit etmiş demektir (Hard Rule 10 ihlali — "readable", "user-friendly" gibi belirsiz kelimeler).

Çözüm: criterion'u manuel düzenle.

```bash
# tasks/T-005.md aç, "Acceptance Criteria" listesini düzelt
# Belirsiz: "stdout shows todos in readable format"
# Net: "stdout matches /^(\[ \] [0-9a-f-]{36} .+\n)*$/"

ortim execute <id> T-005 --reset
```

Veya DAG'ı yeniden generate et (daha temiz ama pahalı):

```bash
ortim advance <id> rfc_approved
ortim run <id>            # Orchestrator yeniden çağrılır
```

### 2.3 `test_infrastructure_unavailable`

Worker test yazdı ama test runner çağrısı exit ≠ 0 (test runner missing veya broken).

```bash
# .ai-factory.env içeriği
cat workspaces/<id>/.ai-factory.env
# AI_FACTORY_TEST_CMD=npx vitest run
```

Test komutu doğru mu, ilgili package install edildi mi?

```bash
cd workspaces/<id>
npm install        # veya pip install -r requirements.txt
# elle test komutunu koş
npx vitest run
```

Komut OK ise:

```bash
ortim execute <id> T-005 --reset
```

`AI_FACTORY_TEST_CMD` yanlışsa `.ai-factory.env` dosyasını elle düzelt + reset.

### 2.4 `security_veto`

SecurityReviewer hard veto verdi (hardcoded secret, SQL injection, eval, vs.). Kod review et:

```bash
ortim show <id> --artifact review --task T-005
```

Verdict somut bir issue gösterir. Kodu elle düzelt → advance. Veya criterion'u (örn. "auth uses environment variable") açıkça yaz → reset.

### 2.5 `criteria_design_failure`

Orchestrator'ın Hard Rule 10 ihlali kaçırdığı criterion. Manuel düzelt, reset. `agents/orchestrator.md` Hard Rule 10'da banned-word listesi var; benzer pattern'ler için Orchestrator prompt'unu sertleştirmek de bir adım (sistemik fix).

---

## 3. Worker 3 deneme sonra başarısız oldu

3 deneme = max retry. State `AWAITING_HITL`'e geçer (§2'ye bak). Yeniden 3 deneme istemen için:

```bash
ortim execute <id> T-005 --reset --max-attempts 3
```

**Üç deneme bitti, hâlâ başarısız** = sistem sana sinyal veriyor: ya criterion belirsiz, ya kod karmaşık, ya Worker LLM'in kapasitesini aşıyor.

Çareler:
- Task'ı **böl** — `tasks/T-005.md`'yi 2-3 daha küçük task'a manuel parçala, DAG'ı elle güncelle.
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
ortim advance <id> budget_approved --note "approved overage for T-005-T-008"
```

**Cap'i artır (önce):**

```bash
# .env dosyasında
AI_FACTORY_BUDGET_CAP_USD=5.00
# yeni terminal aç (env reload)
ortim advance <id> budget_approved
```

**Durdur:**

```bash
ortim advance <id> paused --note "budget exceeded; reviewing"
```

Pause sonrası `ortim retro <id>` ile maliyet breakdown'u: hangi kategori spike ettin?
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
   cp -r workspaces/<id> workspaces/<id>-backup
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

3. **Migration logu yaz:**
   ```bash
   echo "$(date) — manual migration v0.7 → v0.8" >> workspaces/<id>/MIGRATIONS.md
   ```

> **Otomatik migration tooling Faz 3'e ertelendi** (roadmap 3.2). Şu an manuel.

---

## 6. Architect yanlış stack seçti

### Belirti

RFC §4'te brief'te söylemediğin bir teknoloji var (örn. "SQLite dedim, PostgreSQL yazıldı").

### Tespit

```bash
cat workspaces/<id>/intent.json | grep -A 10 user_stack_hints
```

`user_stack_hints` array boş mu, yoksa senin söylediklerini içeriyor mu?

**Boşsa:** Babel hint'lerini çıkaramamış. Brief'i daha açık yaz (örn. "PostgreSQL kullanalim" gibi açık isim, "veritabani" değil).

**Doluysa ama RFC ezdi:** Faz 1.2 B-2 fix bunu kapatıyor. Hâlâ oluyorsa bir bug — issue aç + reproduce et.

### Çözüm

State'i RFC_DRAFTING'e geri at, RFC.md'yi elle düzelt veya Architect'i yeniden çağır:

```bash
ortim advance <id> rfc_drafting
ortim run <id>
```

Veya direkt RFC.md'yi düzenle + onayla:

```bash
# RFC.md'yi metin editöründe aç, §4'ü düzelt
ortim advance <id> rfc_awaiting_approval
ortim advance <id> rfc_approved --note "manually edited stack section"
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
# tasks/T-005.md → "Create the file `tasks/repository.ts` (NOT auth/...)"
ortim execute <id> T-005 --reset
```

Veya Orchestrator'ı yeniden çağır (DAG'ı yeniden üretir):

```bash
ortim advance <id> rfc_approved
ortim run <id>
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

Manuel state set etmek istersen `ortim advance <id> <state>` doğrudan transition çalıştırır.

---

## 9. Hiçbir şey çalışmıyor — workspace'i sıfırdan başlat

Bazen en hızlı yol baştan başlamaktır. Mevcut workspace'i arşivle:

```bash
mv workspaces/<id> workspaces/<id>-broken-$(date +%Y%m%d)
```

Sonra yeni proje aç:

```bash
ortim new "name" --brief @path/to/brief.txt
```

**Eski workspace'ten ne alırsın:**
- `intent.json`, `PRD.md`, `RFC.md` — manuel kopyalama meşru, yeni state'lere advance et
- `task_dag.json` — Orchestrator'ı yeniden çağırarak daha temiz

**Eski workspace'ten ne almaman gerekir:**
- `state.json` — schema değişebilir
- `audit.jsonl` — yeni hash chain'le karışmasın

---

## Yardım istemek için

Issue açarken şunları ekle:
- `ortim doctor` çıktısı
- `ortim status <id>` + `ortim retro <id>` + `ortim drift-check <id>`
- audit log son 30 satır (PII yokmuş gibi temizle)
- Tekrar üretim için kullandığın brief

GitHub: `https://github.com/<owner>/ortim/issues`

---

İlgili dokümanlar:
- [Tutorial](../tutorial/getting-started.md) — sıfırdan başlangıç
- [Architecture](../../Ortim_Architecture.md) — sistem nasıl çalışır
- [Backlog](../backlog.md) — bilinen açık item'lar
