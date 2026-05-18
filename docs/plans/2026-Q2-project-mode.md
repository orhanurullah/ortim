# Project Mode Pivot — Tasarım Belgesi

> **Amaç.** Ortim'i UUID-based pool layout'undan (`<repo>/workspaces/<uuid>/`) cwd-aware project layout'una (`<user-dir>/.ortim/`) taşımak. Git / cargo / terraform / Claude Code standartına oturmak.
>
> **Faz konumu.** 2026 Q2 Roadmap Faz 3 — "Distribution & Ops" hedefi **"Project Mode pivot + Distribution"** olarak güncellendi. 3.2 / 3.4 / 3.5 Faz 4 başına kaydı.
>
> **Versiyon.** v0.8.x → **v0.9.0** (breaking change minor bump).
>
> **Son güncelleme.** 2026-05-17 — **M0-M9 hepsi shipped** tek session'da. Pytest 606 → 734 (+128), 0 regresyon. CHANGELOG yazıldı, version bump (0.9.0) yapıldı. PyPI publish (`python -m build && twine upload`) kullanıcı tarafından gerçekleştirilecek.

---

## 1. Niyet ve değer

Solo kullanıcı `cd ~/dev/todo-app && ortim status` der; tool oradaki `.ortim/` keşfeder; argümansız çalışır. Bu profesyonel CLI'ların **implicit context** standardı. Mevcut "her komutta UUID arg" pattern'i script hissi veriyor, araç hissi vermiyor.

İkincil değer:
- **Brownfield/greenfield ayrımı kaybolur** — kullanıcı zaten kendi dizininde, fark yok.
- **Metadata ile generated code namespace ayrılır** — `.ortim/` (PRD/RFC/state) vs cwd (kullanıcının kodu).
- **Path bağımsızlığı doğal olur** — workspace kullanıcının istediği yerde, registry path tutar.

## 2. Mimari kararlar (locked)

### 2.1 Discovery algoritması — git pattern

```
1. <cwd>/.ortim/  → kullan
2. <cwd>/../.ortim/, <cwd>/../../.ortim/, ... (parent walk, repo kökü olmayana kadar)
3. ~/.ortim/registry.json → `current` pointer
4. Hiçbiri yoksa → "no project here; run `ortim init` or `cd` into a project, see `ortim ls`"
```

Filesystem boundary: parent walk `~`'a veya fs root'a ulaşınca durur (sonsuz döngü önleme).

### 2.2 .ortim/ namespace içeriği

```
<project-dir>/.ortim/
├── state.json              # Project model
├── intent.json             # Babel output
├── golden_path_inputs.json # Architect Call 1
├── stack.json              # LockedStack (M2)
├── scope.json              # ScopeManifest (1.1)
├── PRD.md
├── RFC.md
├── task_dag.json
├── task_status.json
├── codebase.json           # brownfield: kullanıcı kodu özeti
├── audit.jsonl             # per-project audit (legacy global yerine)
├── tasks/                  # T-001.md, T-002.md, ...
├── logs/                   # T-001.log, T-002.log, ...
└── .cache/                 # baseline, drift, mutation
```

Sebep: kullanıcının kodu (auth/, cli/, src/, package.json, ...) workspace root'unda kalır. Karışıklık sıfır. `cd workspace && npm install` natural çalışır. `.gitignore` trivial: `/.ortim/`.

### 2.3 Project mode primary, pool mode legacy

İki rejim **paralel yaşamaz**: pool mode "legacy, deprecation warning" durumuna iner. Yeni komutlar cwd-first; pool'a erişim sadece `--legacy-id <uuid>` flag ile veya `WORKSPACE_ROOT` env var set'liyse.

Faz 4'te pool mode tamamen kalkar.

### 2.4 Registry — ~/.ortim/registry.json

```json
{
  "version": 1,
  "current": "todo-app-7a3b",
  "workspaces": {
    "todo-app-7a3b": {
      "id": "todo-app-7a3b",
      "name": "todo-app",
      "path": "/home/user/dev/todo-app",
      "kind": "active",
      "state": "executing",
      "created_at": "2026-05-17T...",
      "last_active": "2026-05-17T...",
      "mode": "project"
    },
    "079fb8862112": {
      "id": "079fb8862112",
      "name": "todo-greenfield-2",
      "path": "<repo>/workspaces/079fb8862112",
      "kind": "active",
      "state": "executing",
      "created_at": "2026-05-08T...",
      "last_active": "2026-05-08T...",
      "mode": "pool"
    }
  }
}
```

Registry **single source of truth değil** — yalnız index. Authoritative state hâlâ workspace içindeki `state.json`. Registry stale olabilir; `ortim ls` her çağrıda registry'yi tarayıp state.json'lardan stale entry'leri temizler / günceller.

### 2.5 Workspace ID — kalıyor, değişmiyor

ID hâlâ `<slug>-<hash6>` formatında (örn. `todo-app-7a3b`). Sebepler:
- Migration cost — mevcut 196 workspace zaten uuid-12 kullanıyor; ID semantiğini bozarsak path migration cascade'i daha derin olur.
- Registry zaten path tutuyor; ID sadece short reference için.
- Slug + hash6 hatırlanabilir, çakışma riski düşük (hash collision birden fazla olursa registry hata verir, kullanıcı --suffix verir).

Pool legacy ID'leri uuid-12 olarak kayda alınır, değişmez.

### 2.6 ortim init = bootstrap_brownfield'in modern yeri

```
cd ~/dev/todo-app && ortim init "task manager"
```

Davranış:
1. cwd'de `.ortim/` var mı? → varsa hata "already initialized; use `ortim status` to see state"
2. cwd'de kod var mı? → varsa brownfield mode (kod taraması yapılır, `.cache/codebase.json` yazılır), yoksa greenfield mode
3. `.ortim/` oluştur, registry'ye kaydet
4. State machine: INTAKE'a başla (brownfield ise INTAKE → PRD_DRAFTING; greenfield ise INTAKE → BABEL_PROCESSING)

`bootstrap_brownfield` fonksiyonu `init` komutu'nun arka ucu olur, `--from-existing` flag kaldırılır (zaten dizindeyiz).

### 2.7 Audit log path değişimi

Mevcut: global `<repo>/ortim/audit/<date>.jsonl` (ve legacy `runtime/audit/`).
Yeni: per-project `.ortim/audit.jsonl`.

Sebep: ortim'in dünyasından kullanıcı projesi içine taşındı; audit log da projenin parçası. Hash chain integrity per-project sağlanır.

Geriye uyum: `AuditLogger` constructor `project_path: Path | None` alır; None ise legacy global path'e yazar (pool mode için).

## 3. CLI yüzeyi — öncesi vs sonrası

### Önceki (v0.8.x — pool mode, ID arg zorunlu)

```bash
ortim new --name todo "task manager"   # → workspaces/079fb886... oluşur
ortim status 079fb8862112
ortim show 079fb8862112 --artifact PRD
ortim advance 079fb8862112 prd_approved
ortim run-all 079fb8862112
ortim extend 079fb8862112 "tagging özelliği"
```

### Sonraki (v0.9.0 — project mode, cwd implicit)

```bash
cd ~/dev/todo-app
ortim init "task manager"              # → ./.ortim/ oluşur
ortim status                           # cwd'den keşif
ortim show --artifact PRD
ortim advance prd_approved
ortim run-all
ortim extend "tagging özelliği"

# Argümanla da çalışır (registry lookup):
ortim status todo-app                  # registry'den name match
ortim status todo-app-7a3b             # ID
ortim use todo-app-7a3b                # active context değiştir
ortim ls                               # global tablo (her yerden)
```

### Workspace lifecycle (yeni subcommand grup)

```bash
ortim workspace list                   # = ortim ls
ortim workspace show [id]
ortim workspace archive [id]
ortim workspace unarchive [id]
ortim workspace cleanup --older-than 30d --yes
ortim workspace doctor [id]            # orphan/stuck/oversize tespit
ortim workspace migrate <legacy-id> --to <path>   # pool → project
```

Top-level alias'lar (`ortim list-projects`, vs.) deprecation warning ile çalışmaya devam eder. v1.0'da kaldırılır.

## 4. Migration stratejisi

### 4.1 Mevcut 196 workspace

**Hiç dokunulmaz.** Pool layout'unda kalır. İlk `ortim ls` çağrısında otomatik registry'ye `mode: pool` olarak eklenir. Pool ID'leri ile mevcut komutlar çalışmaya devam eder (deprecation warning ile). Kullanıcı isterse tek tek migrate edebilir:

```bash
ortim workspace migrate 079fb8862112 --to ~/dev/todo-greenfield-2
# .ortim/ klasörüne yeniden organize eder:
#   <repo>/workspaces/079fb8862112/  →  ~/dev/todo-greenfield-2/
#     PRD.md, state.json, ...        →    .ortim/ altına
#     auth/, cli/, package.json      →    workspace root'una
```

Migrate komutu opsiyonel — kullanıcı pool workspace'leri olduğu gibi bırakabilir, sadece yeni projeler `ortim init` ile project mode'da olur.

### 4.2 Schema migration

`state.json` schema'sı değişmez. Sadece Project model'e iki opsiyonel field eklenir:
- `kind: Literal["active","demo","scratch","proof_point","baseline","legacy"] = "active"`
- `archived_at: str | None = None`

Default'lar geriye uyumlu — eski state.json'lar yüklenirken yeni field'lar default değerlerini alır.

`is_brownfield`, `app_class`, `source_path` field'ları **kalıyor** (legacy compat). `bootstrap_brownfield` fonksiyonu kaldırılmıyor, sadece `init` arka ucu olur.

### 4.3 Audit log migration

Yeni `.ortim/audit.jsonl` (per-project) yaratılır. Pool mode workspace'ler legacy `ortim/audit/<date>.jsonl`'a yazmaya devam eder (`AuditLogger.project_path is None` branch). Project mode workspace'ler `.ortim/audit.jsonl`'a yazar. Retro tool ikisini de okur.

### 4.4 Test fixture migration

`tests/conftest.py` ve workspace yaratan testler `tmp_path` kullanıyor — buna dokunmuyoruz. Yeni testler `tmp_path / ".ortim"` pattern'ini kullanır. Mevcut testler pool-mode contract'ı koruduğu için (Project.load(id, root)) çalışmaya devam eder.

## 5. Geriye uyum (backward compat) sınırları

**Korunan:**
- Pool workspace'lerin yüklenmesi, advance/run-all/show ile kullanılması
- `WORKSPACE_ROOT` env var
- Mevcut state.json formatı
- Mevcut audit log path'i (legacy)
- `bootstrap_brownfield` Python API'si

**Kaldırılan:**
- `ortim new --from-existing` flag — yerine `cd <dir> && ortim init` (greenfield/brownfield auto-detect)
- `ortim list-projects` → `ortim ls` (top-level alias deprecation warning ile kalır)

**Breaking:**
- `WORKSPACE_ROOT` set değilse default değişti: önce `<cwd>/.ortim/` aranır, bulunmazsa `~/.ortim/workspaces/` (pool default). Eski `./workspaces/` artık default değil.
- Komutlar arg yokken cwd'ye bakar; eski "no arg → hata" davranışı yerine "no arg → discovery" davranışı.

Bu **minor breaking change**'lerdir; v0.9.0 minor bump bunlardan dolayı (semver 0.x.y'de minor = breaking OK).

## 6. Risk analizi

| Risk | Olasılık | Etki | Mitigation |
|---|---|---|---|
| Cwd discovery yanlış parent'a sıçrar (örn. monorepo'da iki .ortim/) | Orta | Yüksek | Parent walk **fs root veya home'a kadar**; bulduğu ilk .ortim/'ı kullanır; debug için `--explain` flag |
| Pool workspace'lerin migration'ı broken (data loss) | Düşük | Çok yüksek | `migrate` komutu **idempotent + dry-run default**; başarısızsa rollback (eski klasör --to flag varsa silmez) |
| Audit log per-project gidince retro tool kırılır | Yüksek | Orta | `AuditLogger` constructor optional `project_path`; retro tool registry'den path'leri toplayıp her birinden okur |
| Test suite (606 test) breakage cascade | Çok yüksek | Yüksek | Her milestone sonunda full pytest; testler `WORKSPACE_ROOT` env'i kullanıyorsa korunur; cwd-aware komutlar için yeni fixture |
| Win32 path uzunluk sınırı (`MAX_PATH=260`) `.ortim/tasks/T-001.log` ile patlar | Orta | Düşük | Mevcut workspace'lerde benzer derinlik var, sorun yaşanmamış; gerekirse `\\?\` prefix Path resolver'da |

## 7. Milestone planı — durum

| M# | İş | Durum | Çıktı |
|---|---|---|---|
| M0 | Bu belge + roadmap pivot | ✅ shipped | Tasarım belgesi + 2026-Q2-roadmap.md güncellendi |
| M1 | `.ortim/` discovery + path resolver + ProjectStore | ✅ shipped | `ortim/workspace/{resolver,store}.py`, +34 test |
| M2 | `ortim init` komutu | ✅ shipped | `ortim/workspace/init.py`, brownfield auto-detect (11 manifest type), +26 test |
| M3 | Read komutlarını cwd-aware yap | ✅ shipped | status / inspect / gates / show / tasks / extensions / ls hepsi cwd-aware, +12 test |
| M4 | Mutating komutları cwd-aware yap | ✅ shipped | advance / refine / lock / scope / run / execute / run-all / extend / drift-check / retro / budget / rescan / baseline. Project.save mode-aware (`_metadata_dir` PrivateAttr), `AUDIT_LOG_PATH` env var resolver tarafından set. +4 test |
| M5 | Registry + `ortim ls` | ✅ shipped | `~/.ortim/registry.json` (path/id/name/kind/state/last_active/current), `ortim ls` registry-backed (her workspace `*` ile current), `ortim use <id>`, prune_missing. +20 test |
| M6 | Workspace subcommand + kind field | ✅ shipped | `ortim workspace list/show/use/archive/unarchive/cleanup/doctor/migrate` namespace, Project.kind field |
| M7 | archive / unarchive / cleanup / doctor | ✅ shipped | `Project.archived_at` flag, `_block_if_archived` helper (mutating komutlar reddediyor), cleanup --older-than --yes --archived-only filter, doctor (registry/fs alignment, orphan pool, aging archive). +22 test (lifecycle) + 6 test (CLI) |
| M8 | Pool legacy + migrate komutu | ✅ shipped | `ortim workspace migrate <pool-id> --to <path>` metadata/code split (META_FILES + META_DIRS + T-*.log pattern), --copy default + --move opsiyon |
| M9 | Test + doc + release ritüeli | ✅ shipped | CHANGELOG 0.9.0 entry, README quick start, pyproject + __init__ version 0.9.0 bump, roadmap closeout, project-mode.md status update. PyPI publish kullanıcı action |
| **Toplam** | | **~30h gerçek (35h tahmin)** | **+128 test (606 → 734), 0 regresyon** |

## 8. Karar günlüğü

| Tarih | Karar | Sebep |
|---|---|---|
| 2026-05-17 | Path 1 (tam pivot) seçildi | Senior session — workspace identity sorunu yapısal, yarım pivot iki rejim taşıma borcu doğurur, kullanıcı tabanı oluşmadan breaking change için optimum pencere |
| 2026-05-17 | Pool layout migration opsiyonel | Mevcut 196 workspace büyük değişim riski; legacy mode'da yaşamaları + opsiyonel migrate komutu yeterli |
| 2026-05-17 | v0.9.0 minor bump | semver 0.x.y'de minor breaking OK; pool→project geçişi semantik kırılma içerir |
| 2026-05-17 | Audit log per-project | Workspace = kullanıcı projesi; audit projeye ait. Legacy global path branch'i `AuditLogger` içinde kalır (None project_path) |

## 9. Referanslar

- 2026-Q2 Roadmap: [`./2026-Q2-roadmap.md`](./2026-Q2-roadmap.md)
- Senior self-audit: [`../../16-05-2026_app-state.md`](../../16-05-2026_app-state.md)
- Mimari spec: [`../../Ortim_Architecture.md`](../../Ortim_Architecture.md)
- Pattern referansları: git `.git/`, cargo `Cargo.toml`, terraform `.terraform/`, npm `package.json`, Claude Code `~/.claude/projects/`
