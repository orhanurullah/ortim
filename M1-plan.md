# M1 — Brownfield Codebase Reader + Mobile Golden Paths

**Scope:** İter 7'nin 7a + 7c fazları. Bu iki parça birbirine bağımlı tasarlanır; ayrı ayrı teslim edilirse "reader Flutter projeyi okuyor ama Architect hâlâ T4 atıyor" senaryosuna düşülür.

**Çıkış kriteri (single demo):**

```
ai-factory new --from-existing C:\Flutter\projects\<flutter-app> \
               --brief "ana sayfaya arama çubuğu ekle"
ai-factory run <id>           # Babel skip → PRD → RFC → tasks
```

Beklenen sonuç:
1. Architect Call 1 çıktısında `app_class=mobile`, `target_platforms=["ios","android"]`
2. Tier scorer M1 (Flutter cross-platform) seçer
3. RFC §7 Module Breakdown'da projenin gerçek `lib/features/<X>/` yapısı geçer (uydurma değil)
4. RFC §4 Tech Stack'te Flutter sürümü ve mevcut state-mgmt seçimi (Riverpod/Bloc/Provider — repo'dan tespit edilen) doğru basılır
5. Task'lar `lib/features/home/` altında oluşur, `src/` görmez

**Demo başarısızlık durumu:** Architect tier=T4 atarsa, ya da RFC'de `lib/features/imaginary_module/` gibi uydurma path geçerse, M1 fail.

---

## Productization kararları (M1 başlamadan sabitlenen)

Bu üç karar M1'in ilk satır kodu yazılmadan alınır; geri dönüşü maliyetli.

### P1 — Lisans modeli: open core + enterprise tier

**Core (`runtime/`, `agents/`, `docs/`, `runtime/architecture/golden_paths.py` dahil tüm temel pipeline):**
**FSL-1.1-Apache-2.0** (Functional Source License, 2 yıl sonra Apache-2.0'a otomatik dönüşür)

- Serbest: internal kullanım, danışmanlık, fork, contribution, on-prem deployment, akademik
- Yasak: "competing service" — yani ai-factory'yi yeniden paketleyip SaaS olarak satmak
- 2 yıl sonra Apache-2.0'a düşer; "trapped contributor" sorunu yok

**Enterprise tier (`enterprise/` alt-dizini):** Commercial License — kapalı kaynak, ayrı `LICENSE.commercial`

Enterprise içeriği (M1 scope'unda boş; iskeleti şimdi koyuyoruz):
- Multi-tenant orchestrator
- SSO / SAML hooks
- Long-term audit retention + S3 export
- SLA-backed support
- Priority bug fixes

**Repo yapısı (monorepo):**
```
ai-factory/
├── LICENSE                      # FSL-1.1-Apache-2.0 (core)
├── LICENSE.commercial           # Commercial (enterprise/ için)
├── NOTICE                       # third-party attribution
├── runtime/                     # FSL
├── agents/                      # FSL
├── docs/                        # FSL
├── tests/                       # FSL
└── enterprise/                  # Commercial — M1'de iskelet + README.commercial.md
    └── README.commercial.md
```

**Source file headers (her .py için):**
```python
# SPDX-License-Identifier: FSL-1.1-Apache-2.0
# Copyright (c) 2026 <Project Owner>
```

`enterprise/` altındaki dosyalar:
```python
# SPDX-License-Identifier: LicenseRef-Commercial
# Copyright (c) 2026 <Project Owner>. All rights reserved.
```

**M1 deliverable:** `LICENSE`, `LICENSE.commercial`, `NOTICE`, `enterprise/README.commercial.md`, ve **mevcut tüm `.py` dosyalarına SPDX header retrofit** (mekanik script).

**Alternatif değerlendirildi, reddedildi:**
- MIT/Apache: permisif, "competing service" engellemiyor → ürünleştirme öldürür
- BSL 1.1: FSL'in eski versiyonu, daha karmaşık variants
- AGPL: SaaS rakipler için yeterli ama "open" değil "copyleft" — danışmanlık projesinde müşteriler kontamine olabilir endişesi
- SSPL: çok agresif, OSI tarafından "open source" sayılmıyor; brand zararı

### P2 — Audit log compliance upgrade

Mevcut `runtime/audit/logger.py` JSON-lines yazıyor — internal kullanım için OK ama compliance/danışmanlık satışına uygun değil. M1'de üç ekleme:

1. **`redact_pii: bool = True`** (default true)
   - PRD/brief metinleri audit'a yazılmadan önce e-posta, T.C. kimlik no, telefon pattern'ları `[REDACTED]` ile değiştirilir
   - `runtime/audit/redact.py` — regex tablosu (KVKK için T.C., GDPR için PII genel)
   - Bypass: `AI_FACTORY_AUDIT_RAW=1` (debug için, prod'da set edilmemeli)

2. **Tamper-evidence hash chain**
   - Her event'e `prev_hash` field'ı; önceki event'in JSON serialization'ının SHA-256'sı
   - İlk event'in `prev_hash = "0" * 64`
   - `runtime/audit/verify.py` — chain doğrulama CLI: `ai-factory audit-verify <id>`
   - Birisi log dosyasından event silerse/değiştirirse chain kırılır, doğrulama fail eder

3. **Structured event taxonomy**
   - Her event `category: Literal["intake","architect","worker","reviewer","executor","budget","gate"]`
   - Compliance/danışmanlık raporlarında filter için
   - Mevcut event isimleri taxonomy'ye map'lenir (sözlük tablosu)

**M1 deliverable:** `runtime/audit/redact.py`, `runtime/audit/verify.py`, `logger.py` upgrade, `tests/test_audit_redact.py`, `tests/test_audit_chain.py`.

### P3 — Multi-tenant marker'ları (kararı bana bıraktın)

**Karar: ŞİMDİ ekliyoruz, ama iskelet/passthrough şeklinde.** Argüman var, default `"default"`, M1'de tek-tenant davranışı değişmez. Retrofit maliyeti 1+ gün; şimdi 30 dakika.

Etki alanı (her birine `tenant_id: str = "default"` parametresi):
- `Project.workspace_path(project_id, root)` → `Project.workspace_path(project_id, root, tenant_id)`
- `WORKSPACE_ROOT / tenant_id / project_id / ...` (default'ta `WORKSPACE_ROOT / "default" / ...`)
- `BudgetTracker(project_id)` → `BudgetTracker(project_id, tenant_id)`
- `AuditLogger(project_id)` → `AuditLogger(project_id, tenant_id)`
- CLI: `--tenant <id>` global flag (default `"default"`)

**M1'de bilerek YAPMADIKLARIMIZ:**
- Tenant authentication / authorization (M5+)
- Per-tenant LLM API key mapping (enterprise/)
- Tenant-aware rate limiting (enterprise/)
- Cross-tenant audit dashboard (enterprise/)

**Kritik test:** Mevcut 134 test'in hepsi `tenant_id` argümanı geçmeden çalışmalı (default değer çekmeli). Tek bir test break'i = retrofit yanlış yapıldı.

---

## Mimari görünüm

```
┌─────────────────────────────────────────────────────────────┐
│                       CLI                                    │
│  ai-factory new --from-existing <path>                      │
│         │                                                    │
│         ▼                                                    │
│  intake.bootstrap_brownfield(path)                          │
│    ├─ symlink/copy → workspaces/<id>/                       │
│    ├─ codebase.scan() → .cache/codebase.json               │
│    ├─ baseline.capture() → .cache/baseline.json            │
│    └─ AppClass detection → state.json["app_class"]         │
└─────────────────────────────────────────────────────────────┘
                  │
                  ▼
┌─────────────────────────────────────────────────────────────┐
│  ArchitectAgent                                              │
│    Call 1: extract_inputs(prd, codebase_summary, app_class) │
│    deterministic: select_tier(inputs)                       │
│    Call 2: draft_rfc(prd, tier, codebase_summary)          │
└─────────────────────────────────────────────────────────────┘
                  │
                  ▼
┌─────────────────────────────────────────────────────────────┐
│  WorkerAgent.execute(task, rfc, related_files)              │
│    related_files = codebase.read_related(task.module_scope) │
│    sandbox.check_extension(path, app_class)                 │
└─────────────────────────────────────────────────────────────┘
```

Reader **iki farklı consumer**'a hizmet veriyor:
- Architect: `CodebaseSummary` (özet — tree, languages, framework hints, public symbols)
- Worker: `read_related` (full content — sadece task'ın scope'undaki dosyalar, byte-cap altında)

Cache her ikisi için ortak: `workspaces/<id>/.cache/codebase.json`.

---

## Bileşen A — `runtime/codebase/`

### A.1 — `CodebaseSummary` schema

```python
# runtime/codebase/schema.py
from pydantic import BaseModel, Field

class FileEntry(BaseModel):
    path: str                       # POSIX-relative to root
    size_bytes: int
    mtime_ns: int
    sha1: str                       # cache invalidation key
    language: str | None            # "python","dart","ts","yaml",...
    role: str | None                # "source","test","config","doc","build"

class ModuleSymbols(BaseModel):
    path: str                       # "lib/features/home/"
    public_names: list[str]         # AST/regex extract: top-level def/class/widget
    imports: list[str]              # external + relative; for graph

class FrameworkHint(BaseModel):
    name: str                       # "flutter","fastapi","nextjs","tauri",...
    confidence: float               # 0.0-1.0
    evidence: list[str]             # ["pubspec.yaml:flutter_sdk","lib/main.dart:Flutter"]
    version: str | None             # parsed from manifest if available

class CodebaseSummary(BaseModel):
    root: str                       # absolute path (just-in-case audit)
    scanned_at: str                 # iso utc
    file_count: int
    truncated: bool                 # true → max_files cap hit
    files: list[FileEntry]          # ALL within cap, ordered by path
    languages: dict[str, int]       # ext → file count
    frameworks: list[FrameworkHint]
    modules: list[ModuleSymbols]    # discovered top-level modules
    deps_manifests: dict[str, str]  # "pubspec.yaml": <content>
    app_class_hint: str | None      # "web"|"mobile"|"desktop" — first-pass guess

    def cache_key(self) -> str:
        # used by Architect/Worker to detect stale summaries
        return f"{self.scanned_at}:{self.file_count}"
```

**Kararlar:**
- `sha1` content hash — cache invalidation için hem mtime hem hash. mtime tek başına Windows'ta güvensiz (1s granularity, OS update'inde değişebilir).
- `role` heuristic: path'te `test/` → test, `*.lock|*.toml|*.yaml` config root'taysa → config, `lib/`, `src/`, `app/` → source.
- `modules` Python/Dart/TS için doldurulur; başka dil = boş liste (M1 scope dışı).

### A.2 — `scan_codebase()` algoritması

```python
# runtime/codebase/reader.py
def scan_codebase(
    root: Path,
    max_files: int = 2000,
    max_bytes_per_file: int = 200_000,
    cache_path: Path | None = None,
) -> CodebaseSummary: ...
```

Adımlar:

1. **gitignore-aware walk** — `pathspec` paketi (PyPI). `.gitignore` + `.git/info/exclude` yüklenir. Eklenecek hard-skip: `.venv`, `node_modules`, `build`, `.dart_tool`, `.next`, `dist`, `target`, `.cache`, `__pycache__`. Bu hard-skip her zaman aktif (gitignore varsa bile, çünkü açık unutulmuş repo'lar olur).

2. **Cache short-circuit** — `cache_path` varsa yükle. Her dosya için `(path, mtime_ns, size)` tuple'ı eski cache ile karşılaştır. Hiçbiri değişmediyse cache'i döndür. Değişen varsa sadece o dosyaları yeniden parse et, gerisini cache'ten taşı.

3. **Per-file processing**:
   - `size > max_bytes_per_file` → `sha1` hesaplama atla, `language=None`, `role=None` (büyük binary/asset)
   - Language by extension (deterministik tablo)
   - Role by path heuristic
   - `modules` listesine eklemek için: `*.py`/`*.dart`/`*.ts` + path'de `__init__.py`/`pubspec.yaml`-altı/`index.ts` benzeri marker varsa modül başlangıcı

4. **Public symbols extraction**:
   - **Python:** `ast.parse` → top-level `FunctionDef`/`ClassDef`/`AsyncFunctionDef`. Underscore-prefixed exclude.
   - **Dart:** regex `^(class|abstract\s+class|enum|mixin|extension)\s+(\w+)` + `^(\w+\s+)?(\w+)\s*\(.*\)\s*(\=>|{)` (top-level fonksiyonlar). M1'de **regex yeterli** — Dart AST için tree-sitter Python'da güvensiz, ileride upgrade.
   - **TS/JS:** regex `^export\s+(default\s+)?(class|function|const|let|var|interface|type)\s+(\w+)`.

5. **Framework detection** — `runtime/codebase/frameworks.py` bir kural tablosu:
   ```python
   FRAMEWORK_RULES = [
       FrameworkRule(
           name="flutter",
           manifest="pubspec.yaml",
           manifest_match=r"flutter:\s*\n\s*sdk:\s*flutter",
           code_glob="lib/**/*.dart",
           code_match=r"import\s+'package:flutter/",
           app_class="mobile",  # implication
           parse_version=lambda m: re.search(r"sdk:\s*['\"]?>=([\d.]+)", m),
       ),
       # fastapi, nextjs, tauri, electron, swiftui, ...
   ]
   ```
   Confidence = `sum(matched_signals) / len(rule_signals)`.

6. **App-class hint** — frameworks içindeki ilk hit'in `app_class`'ı. Çakışırsa (Flutter + FastAPI = monorepo) → `mixed`.

**Performans hedefleri:**
- Cold scan, 1000 dosya: < 3s
- Warm scan (cache hit, 0 değişim): < 200ms
- Warm scan (5 dosya değişmiş): < 500ms

### A.3 — `read_related()` algoritması

Worker için relevance triage. Naif "task description'da geçen dosya isimleri" yetmez — büyük projede 50 false-positive verir.

```python
def read_related(
    summary: CodebaseSummary,
    root: Path,
    module_scope: list[str],
    task_description: str,
    max_total_bytes: int = 30_000,
) -> dict[str, str]:
    """Returns {posix_path: content}. Token-budget aware."""
```

Adımlar:

1. **Direct match** — `module_scope` listesindeki her path için; o path'in altındaki tüm dosyalar kandidat. Path bir dosyaysa kendisi.

2. **Description match** — `task_description` içinde regex ile `[A-Z]\w+(Page|Widget|Service|Repository)` pattern'ı çek (Dart konvansiyonları); summary.modules.public_names ile intersect et. Match olan dosyaları kandidata ekle (1 hop).

3. **Import-graph 1-hop** — Direct match dosyalarının `imports` listesinden, summary.modules'da map'lenebilenleri kandidata ekle. Sadece **proje-içi** import'lar (external paket değil).

4. **Ranking** — kandidatlar şu skorla sıralanır:
   - +100 direct match
   - +50 description match
   - +20 1-hop import
   - -10 her 1KB dosya boyutu için (büyük dosyalar bütçe yer)
   - -1000 `sha1` summary'de yoksa (stale → güvensiz, atla)

5. **Greedy fill** — sıralı kandidatları total_bytes ≤ max_total_bytes olana kadar ekle. Her dosyanın content'ini disk'ten taze oku (cache içerik tutmuyor, sadece metadata).

6. **Header annotation** — her dosyanın başına `// FILE: lib/features/home/home_page.dart (327 bytes, sha1=...)` yorum satırı eklenir; Worker hangi dosyayı gördüğünü prompt'ta açık görür.

**Bütçe matematiği:**
- Worker prompt'unda mevcut: ~3KB system + ~2KB L1 + ~4KB RFC section + ~1KB retry block ≈ **10KB sabit yük**
- max_total_bytes = 30KB → toplam ~40KB ≈ ~10K token
- Claude Sonnet 4.6'da 200K context → bol kalır ama maliyet için sıkı tutmak gerek
- Override: `AI_FACTORY_RELATED_FILES_BYTES` env

### A.4 — Cache şeması

```
workspaces/<id>/
├── state.json
├── PRD.md
├── RFC.md
├── task_dag.json
├── source/                    # symlink veya copy → kullanıcının repo'su
└── .cache/
    ├── codebase.json          # CodebaseSummary serialized
    ├── baseline.json          # { tests_passing: int, captured_at: str, cmd: str }
    └── codebase.lock          # filelock — concurrent scan'leri serialize
```

**Stale detection:**
- `Project.run()` her başlangıçta `scan_codebase(root, cache_path=...)` çağırır
- Reader cache'in `scanned_at`'ı 24 saatten eski ise full rescan
- Aksi halde değişen dosyaları diff ile yakala (mtime + size)

**Cache reset CLI:** `ai-factory rescan <id>` — manuel invalidation.

---

## Bileşen B — App-class + Mobile/Desktop golden paths

### B.1 — `AppClass` enum + `GoldenPathInputs` genişlemesi

```python
# runtime/architecture/golden_paths.py
class AppClass(str, Enum):
    WEB = "web"           # default — T0..T6
    MOBILE = "mobile"     # M0..M2
    DESKTOP = "desktop"   # D0..D1
    MIXED = "mixed"       # monorepo — Architect explicit input gerekir

class GoldenPathInputs(BaseModel):
    # mevcut alanlar...
    app_class: AppClass = AppClass.WEB
    target_platforms: list[str] = Field(default_factory=list)
    offline_required: bool = False
    native_features: list[str] = Field(default_factory=list)
    # ["camera","biometric","push","background-sync","ble"]
```

### B.2 — Yeni tier'lar

```python
class Tier(str, Enum):
    # mevcut T0..T6
    M0 = "M0"   # Native mobile (Swift / Kotlin)
    M1 = "M1"   # Cross-platform (Flutter / RN) — DEFAULT
    M2 = "M2"   # PWA + wrapper (Capacitor)
    D0 = "D0"   # Native desktop (SwiftUI / WinUI / GTK)
    D1 = "D1"   # Cross-platform desktop (Tauri / Electron) — DEFAULT
```

Tier-name table extend, `_score_m0`/`_score_m1`/`_score_m2`/`_score_d0`/`_score_d1` fonksiyonları.

### B.3 — Branched `score_all`

```python
def score_all(inputs: GoldenPathInputs) -> list[TierScore]:
    if inputs.app_class == AppClass.WEB:
        return [scorer(inputs) for scorer in _WEB_SCORERS]
    if inputs.app_class == AppClass.MOBILE:
        return [scorer(inputs) for scorer in _MOBILE_SCORERS]
    if inputs.app_class == AppClass.DESKTOP:
        return [scorer(inputs) for scorer in _DESKTOP_SCORERS]
    # MIXED → Architect zaten explicit choice yaptı; raise ValueError
    raise ValueError("MIXED app_class needs explicit tier; cannot auto-score")
```

`select_tier` aynı kalır — fallback "default tier" tanımı her sınıf için ayrı:
- WEB default = T4
- MOBILE default = M1
- DESKTOP default = D1

### B.4 — Mobile scorer kuralları

**M0 (Native):**
- +30 `"ble" in native_features` (BLE Flutter'da güvenilmez)
- +20 `"high-fps-game" in native_features` (Skia limit)
- +20 `target_platforms == ["ios"]` veya `== ["android"]` (tek platform)
- BLOCK: hiçbiri tetiklenmediyse skor 0 (M1 default'a yol verir)

**M1 (Flutter / RN) — DEFAULT:**
- 60 base
- +15 `len(target_platforms) >= 2` (cross-platform değer)
- +15 `team_size in (SOLO, SMALL)` (single-codebase win)
- +10 `offline_required` (Flutter offline-first matür)
- -10 `"high-fps-game" in native_features`

**M2 (PWA wrapper):**
- 30 base
- +30 sadece web'de mevcut codebase varsa (`frameworks` içinde "react"/"vue"/"svelte" + mobile target)
- BLOCK: `"push" in native_features and "ios" in target_platforms` (iOS PWA push güvenilmez)

### B.5 — Desktop scorer kuralları

**D0 (Native):**
- +30 `len(target_platforms) == 1`
- +20 `"deep-os-integration" in native_features`
- BLOCK: cross-platform requested

**D1 (Tauri/Electron) — DEFAULT:**
- 60 base
- +15 `len(target_platforms) >= 2`
- +10 `team_size in (SOLO, SMALL)`

### B.6 — Yeni golden path docs

5 yeni dosya — `docs/golden-paths/`:

| Dosya | İçerik özeti |
|---|---|
| `M0-native-mobile.md` | Swift/Kotlin, ne zaman seçilir (BLE/AR/yüksek FPS), modül layout, native test (XCTest/Espresso), CI (Fastlane), migration M0←M1 |
| `M1-flutter-rn.md` | Flutter (default) **ve** RN seçimi; `lib/features/X/` layout; Riverpod vs Bloc karar matrisi; offline-first (drift/isar); secure_storage; deep links; widget+integration test; FastLane/EAS CI |
| `M2-pwa-wrapper.md` | Capacitor, ne zaman caiz (mevcut SPA mobile'a açılıyor); push/biometric limitleri; service worker; migration M2→M1 |
| `D0-native-desktop.md` | SwiftUI/WinUI/GTK; OS integration deep; tek platform fokus |
| `D1-cross-desktop.md` | Tauri (Rust) vs Electron (web); paketleme; updater; migration D1↔D0 |

Her doc T-tier docs'unun yapısına uyar: When/When NOT, Stack matrisi, Layout, Cross-cutting, Test, CI, Risks, Migration.

`docs/golden-paths/index.md`'ye yeni "App Class" bölümü eklenir.

---

## Bileşen C — Integration

### C.1 — `ArchitectAgent` genişlemesi

```python
def extract_inputs(
    self,
    prd_markdown: str,
    project_id: str,
    codebase: CodebaseSummary | None = None,
) -> GoldenPathInputs:
```

Prompt değişikliği — codebase varsa user_prompt'a önce şu blok eklenir:

```
## Existing codebase summary

Detected app class hint: mobile (frameworks: flutter@3.16.0)
File count: 234 (truncated: false)
Top-level modules:
  lib/features/home/    (HomePage, HomeController, ...)
  lib/features/auth/    (LoginPage, AuthRepository, ...)
  lib/core/             (ApiClient, AppRouter, ...)
Languages: dart=187, yaml=12, gradle=3, swift=8, kotlin=5
Dep manifests: pubspec.yaml, ios/Podfile

Treat the codebase as ground truth for module structure and tech stack.
Set app_class accordingly. Do not invent modules that do not exist.
```

Token cap: özet 2KB'a sığar (hash ve detay alanları çıkarılır, summary serialize için ayrı `to_prompt_text(max_bytes=2000)` metodu yazılır).

`agents/architect.md` Call 1 kurallarına ekleme:
> 9. `app_class`: `existing_codebase_summary` blok varsa onun `app_class hint`'ini kullan; yoksa PRD anahtar kelimelerinden çıkar (`flutter`/`mobile app` → mobile, `desktop`/`tauri`/`electron` → desktop, default web).
> 10. `target_platforms`: PRD veya codebase platform klasörlerinden (`ios/`, `android/`, `windows/`, `macos/`) tespit.

### C.2 — `draft_rfc` güncellemesi

```python
def draft_rfc(
    self,
    prd_markdown: str,
    tier_score: TierScore,
    project_name: str,
    project_id: str,
    codebase: CodebaseSummary | None = None,
) -> str:
```

Tier doc dynamic loading: `docs/golden-paths/{tier.value}-*.md` dosyası system prompt'a eklenir (sadece seçilen tier'ınki — 7K token limit altında).

`agents/architect.md` Call 2'ye ekleme:
> If `existing_codebase_summary` is present, §7 Module Breakdown MUST list ONLY modules that appear in the summary's `modules` list, plus new modules required by the PRD. Mark new modules with `(new)`. §4 Tech Stack MUST match the detected `frameworks` and `dep_manifests`.

### C.3 — `WorkerAgent` genişlemesi

```python
def execute(
    self,
    task: TaskSpec,
    rfc_text: str,
    project_id: str,
    prior_review_reasons: list[str] | None = None,
    related_files: dict[str, str] | None = None,
) -> WorkerOutput:
```

Prompt'a (retry_block'tan önce):

```
## Related existing files (read these — do not regenerate unrelated lines)

// FILE: lib/features/home/home_page.dart (4327 bytes)
[content]

// FILE: lib/features/home/home_controller.dart (1284 bytes)
[content]

If your task is to modify these files, output `operation: overwrite` (M1 scope)
with the full new content. Preserve all unrelated logic exactly.
```

**Not:** `update`/`patch` operation M2'de gelir (bu plan dışında). M1'de `overwrite` yeterli, ama Reviewer'a "diff ratio" ölçümü eklenir; eski `related_files[path]` ile yeni `output.files[i].content` arasında %50+ değişim varsa yumuşak bayrak.

### C.4 — `runtime/executor/runner.py` related_files build

```python
# execute_task(...) içinde, worker.execute()'tan ÖNCE:

related_files: dict[str, str] | None = None
if codebase_summary is not None:  # bootstrap'ta yüklenmiş ise
    related_files = read_related(
        summary=codebase_summary,
        root=task_workspace,
        module_scope=task.module_scope,  # str → tek elemanlı liste'e wrap
        task_description=task.title + "\n" + task.acceptance_criteria_text(),
        max_total_bytes=int(os.getenv("AI_FACTORY_RELATED_FILES_BYTES", "30000")),
    )
```

`codebase_summary` runner argümanına eklenir; `Project.run` orchestrator'ı bootstrap'ta yükleyip pass eder.

---

## Bileşen D — Conditional sandbox extension

Mevcut `_ALLOWED_EXTS` her şey her yerde. Mobile-only `.dart`, desktop-only `.rs` web projesinde sandbox'ı geçmemeli — tipo veya halüsinasyondur.

```python
# runtime/executor/sandbox.py
_BASE_EXTS = frozenset({  # her zaman OK
    ".md",".rst",".txt",".json",".yaml",".yml",".toml",".ini",".cfg",
    ".env",".lock",".sh",".bat",".csv",".sql",
})
_WEB_EXTS = frozenset({".py",".pyi",".js",".jsx",".ts",".tsx",".mjs",
                       ".cjs",".html",".css",".scss",".vue",".svelte",
                       ".go",".rb",".java"})
_MOBILE_EXTS = frozenset({".dart",".swift",".kt",".kts",".gradle",".plist",
                          ".xcconfig",".pbxproj",".m",".mm",".java",".kt"})
_DESKTOP_EXTS = frozenset({".rs",".swift",".cpp",".cc",".c",".h",".hpp",
                           ".cs",".xaml"})

def check_extension(path: PurePosixPath, app_class: str = "web") -> None:
    allowed = _BASE_EXTS | {
        "web": _WEB_EXTS,
        "mobile": _MOBILE_EXTS | _WEB_EXTS,  # mobile back-end yazabilir
        "desktop": _DESKTOP_EXTS | _WEB_EXTS,
        "mixed": _WEB_EXTS | _MOBILE_EXTS | _DESKTOP_EXTS,
    }[app_class]
    # ... mevcut basename + ext check
```

`app_class` her sandbox check'e thread'lenir — runner'dan worker.execute'a, oradan check_extension'a. Default `"web"` geriye uyumluluk için.

---

## Bileşen E — Brownfield baseline contract

**Sözleşme:** Brownfield projeyle başlayan iş, projenin **mevcut geçen test sayısını düşürmemeli**. Eğer düşürürse, Worker output kabul edilse bile task `AWAITING_HITL`'e gider.

### E.1 — Bootstrap

`--from-existing` ile project yaratıldığında:

```python
# runtime/codebase/baseline.py
@dataclass
class TestBaseline:
    cmd: str                # AI_FACTORY_TEST_CMD veya auto-detect
    captured_at: str
    passing: int            # parsed test count
    skipped: int
    failed: int             # ideali 0; > 0 ise warn ve baseline yine de yaz
    full_output: str        # debug için son 4KB

def capture(workspace: Path, cmd: str | None = None) -> TestBaseline: ...
```

Auto-detect:
- `pubspec.yaml` var → `flutter test`
- `pyproject.toml` var → `pytest`
- `package.json` var + `"test"` script → `npm test`

### E.2 — Per-task check

`runner.py` her task sonunda (commit'ten önce):

```python
if has_baseline and test_result and test_result.passed:
    current = parse_test_count(test_result)
    if current.passing < baseline.passing:
        # regresyon
        record.last_review_reasons.append(
            f"[baseline] regression: {baseline.passing} → {current.passing} tests passing"
        )
        record.status = TaskStatus.AWAITING_HITL
        return ExecutionResult(..., blocked_by="baseline")
```

Test parser tier-aware: `flutter test`, `pytest`, `jest` farklı format. Basit regex; M1 scope'unda Flutter+pytest yeterli.

### E.3 — `ai-factory baseline <id>` CLI

- `baseline <id>` — mevcut baseline'ı göster
- `baseline <id> --recapture` — yeniden yakala (kullanıcı kendi elle değişiklik yaptıysa)
- `baseline <id> --override <count>` — manuel override (test parse fail durumunda)

---

## Bileşen F — CLI surface

### F.1 — `ai-factory new --from-existing`

```python
@app.command()
def new(
    brief: str = typer.Argument(...),
    name: str = typer.Option("untitled"),
    from_existing: Path | None = typer.Option(None, "--from-existing"),
    link_mode: str = typer.Option("symlink", help="symlink|copy"),
) -> None:
```

Davranış:
1. Project oluştur (mevcut)
2. `from_existing` varsa:
   - Windows symlink dev-mode gerektirir; başarısızsa otomatik `copy` fallback (warn)
   - `workspaces/<id>/source/` symlink/copy
   - `scan_codebase()` → `.cache/codebase.json`
   - `baseline.capture()` → `.cache/baseline.json`
   - `app_class` hint'ten state.json'a yaz
   - Babel skip — `intent.json`'a stub yaz, doğrudan `PRD_DRAFTING`'e geç
3. Brief opsiyonel (zorunlu argüman olmaktan çıkar — `from_existing` ile boş olabilir, kullanıcı PRD'yi elle yazar)

### F.2 — Yardımcı komutlar

- `ai-factory rescan <id>` — codebase summary'i invalidate + yeniden scan
- `ai-factory baseline <id> [--recapture|--override N]`
- `ai-factory inspect <id>` — `.cache/codebase.json`'u tablo halinde dump (debugging)

---

## Bileşen G — State machine değişimi

Mevcut: `INTAKE → BABEL_PROCESSING → PRD_DRAFTING → ...`

Brownfield path:

```python
# runtime/orchestrator/state_machine.py — yeni transition
TRANSITIONS[ProjectState.INTAKE].add(ProjectState.PRD_DRAFTING)  # brownfield skip
```

`Project.bootstrap_brownfield(path, link_mode)` metodu:
- `intent.json`'u stub yazar: `{"goal":"existing-codebase","brief_tr":<orig>,"app_class":<hint>}`
- `state` doğrudan `PRD_DRAFTING`
- `history`'ye `bootstrap_brownfield` event'i

Yeni state tanıtmak gereksiz — mevcut state'lerin transition graph'ı genişler.

---

## Token budget — concrete math

Architect Call 1 (extract_inputs):
- system: agents/architect.md (≈3KB)
- user: PRD (≈3KB) + codebase_summary.to_prompt_text(2000) (≈2KB) = ≈5KB
- **toplam input: ~8KB ≈ ~2K token. Cap: 1500 output token.** OK.

Architect Call 2 (draft_rfc):
- system: architect.md (3KB) + L1 (2KB) + RFC template (4KB) + tier doc (5KB) + tier_brief (1KB) = ≈15KB
- user: PRD (3KB) + codebase summary (2KB) = ≈5KB
- **toplam input: ~20KB ≈ ~5K token. Cap: 6000 output token.** OK ama sıkı; tier doc 5KB üstü olmamalı.

Worker execute (with related_files):
- system: worker.md (2KB) + L1 (2KB) = ≈4KB
- user: task.json (1KB) + rfc_section (3KB) + retry (1KB) + related_files (30KB cap) = ≈35KB
- **toplam input: ~39KB ≈ ~10K token. Cap: 8000 output token.** Bütçe sıkı; mobile dosyalar (Dart) Python'dan sıkıştır oranlı, 30KB güvenli.

**Hard limit:** Worker prompt 50KB üstüne çıkarsa, `read_related` `max_total_bytes`'ı dinamik düşür.

---

## Test stratejisi — concrete cases

### Reader unit (`tests/test_codebase_reader.py`)

1. `scan_codebase` boş dizinde → `file_count=0, truncated=False`
2. Bu repo'nun kendisi (`runtime/`) → `frameworks` içinde Python tooling, `modules` içinde `runtime.executor`, `runtime.orchestrator`, ...
3. Geçici Flutter sample (`pubspec.yaml` + `lib/main.dart` + `lib/features/foo/foo_page.dart`) → `frameworks[0].name == "flutter"`, `modules` içinde `lib/features/foo/`, `app_class_hint == "mobile"`
4. `max_files=10` → `truncated=True`
5. `.gitignore`'da `build/` → o klasör yok
6. Aynı dizini iki kere scan et, ikinci `cache_path` ile → ikinci scan < 200ms (mtime karşılaştırma)
7. Bir dosyaya touch + içerik değiştir → ikinci scan o dosyayı yeniden parse, gerisini cache'ten

### `read_related` unit

8. `module_scope=["lib/features/home"]` → home altındaki dosyalar dönüyor
9. `task_description="HomePage'e arama ekle"` → home_page.dart skoru +50
10. Import-graph: home_page.dart → home_controller.dart import; controller da kandidat
11. `max_total_bytes=1000`, 5x500-byte dosya → en yüksek skorlu 2 dosya seçildi
12. Stale: summary'de olmayan dosya → -1000 ile elendi

### Golden path scorer (`tests/test_golden_paths.py` extend)

13. `app_class=mobile, target_platforms=["ios","android"]` → tier=M1
14. `app_class=mobile, native_features=["high-fps-game"], target_platforms=["ios"]` → tier=M0
15. `app_class=mobile, target_platforms=["ios"], native_features=["push"]` + frameworks içinde react → M2 BLOCKED, fallback M1
16. `app_class=desktop, target_platforms=["macos","windows"]` → tier=D1
17. `app_class=web` (mevcut tüm testler) → değişmemiş

### Sandbox conditional (`tests/test_executor.py` extend)

18. `check_extension("home.dart", app_class="web")` → SandboxViolation
19. `check_extension("home.dart", app_class="mobile")` → OK
20. `check_extension("util.py", app_class="mobile")` → OK (mobile back-end yazabilir)
21. `check_extension("main.rs", app_class="mobile")` → SandboxViolation

### Architect integration (`tests/test_architect_brownfield.py` yeni)

22. Mock LLM, `extract_inputs` çağrısında user_prompt'ta `Existing codebase summary` bloğu var mı
23. `draft_rfc` Flutter sample ile çağrıldığında system_prompt'ta `M1-flutter-rn.md` içeriği var mı
24. `extract_inputs` codebase=None ise user_prompt'ta summary bloğu yok (geriye uyumluluk)

### Baseline (`tests/test_baseline.py` yeni)

25. `pubspec.yaml` olan workspace → auto-detect `flutter test`
26. `pytest -q` çıktısı parse → `passing=N`
27. Regresyon: baseline=10, current=8 → task AWAITING_HITL
28. Baseline yok ise (greenfield) → check skip, mevcut davranış

### CLI (`tests/test_cli_brownfield.py` yeni)

29. `new --from-existing <fixture-flutter>` → `state == PRD_DRAFTING` (Babel skip)
30. `new --from-existing` Windows + symlink fail → fallback copy + warn

**Mevcut 134 → hedef ~165 test, %100 geçer.**

---

## Risk listesi + mitigation

| Risk | Olasılık | Etki | Mitigation |
|---|---|---|---|
| Symlink Windows'ta dev-mode gerektirir | Yüksek | Kullanım engellenir | Otomatik copy fallback + warn |
| Cache dosyası corrupt → parse fail | Düşük | Project boot fail | try/except → log + full rescan |
| Flutter sample fixture CI'da agresif yer kaplar | Orta | CI yavaşlığı | tmp_path + minimal 5-dosyalık fixture |
| Codebase summary'nin `modules` listesi büyük repo'da 100+ → prompt budget patlar | Orta | Architect Call 1 yavaş/pahalı | `to_prompt_text(max_bytes)` üst K modülle truncate (path uzunluğuyla skorla) |
| `read_related` import-graph'i regex-based, false-positive | Orta | Worker yanlış dosya görür | M1'de kabul; M2'de tree-sitter veya `pyright`/`dart analyze` upgrade |
| Mobile tier RFC'si Flutter detail seviyesi yetersiz | Orta | RFC §7 cilasız | `M1-flutter-rn.md` doc kalitesi fixture-test ile assert (Riverpod kelimesi geçmeli, vb.) |
| Baseline parse `flutter test`'in stdout formatına bağımlı | Orta | False regression alarm | Parser strict değil — sayı bulunamazsa baseline mode'u disable + warn |
| Conditional sandbox geriye uyumluluk kırılır | Yüksek | Eski testler patlar | `app_class` default `"web"`; tüm mevcut çağrılar implicit web |

---

## Deliverables checklist

```
# Productization (P1+P2+P3 — yeni)
LICENSE                         (new — FSL-1.1-Apache-2.0 tam metin)
LICENSE.commercial              (new — Commercial license stub for enterprise/)
NOTICE                          (new — third-party attribution)
README.md                       (modify — license section + commercial contact)
enterprise/
├── README.commercial.md        (new — enterprise tier roadmap stub)
└── .gitkeep

scripts/
└── add_spdx_headers.py         (new — mekanik header insertion script)

(her mevcut runtime/**/*.py → SPDX header eklenmiş)

runtime/audit/
├── logger.py                   (modify — redact_pii, prev_hash, category)
├── redact.py                   (new — PII regex tablosu)
└── verify.py                   (new — chain doğrulama)

# Codebase reader (M1 ana)
runtime/codebase/
├── __init__.py                 (new)
├── schema.py                   (new — pydantic models)
├── reader.py                   (new — scan_codebase, read_related)
├── frameworks.py               (new — detection rules)
└── baseline.py                 (new — capture, parse, regression check)

runtime/architecture/
├── golden_paths.py             (modify — AppClass, M/D tiers, branched scorer)
└── __init__.py                 (modify — exports)

runtime/agents/
└── architect.py                (modify — codebase param on both calls)

runtime/executor/
├── sandbox.py                  (modify — conditional check_extension)
├── worker.py                   (modify — related_files param)
└── runner.py                   (modify — read_related call, baseline check)

runtime/orchestrator/
├── project.py                  (modify — bootstrap_brownfield, app_class, tenant_id)
└── state_machine.py            (modify — INTAKE→PRD_DRAFTING transition)

runtime/budget/
└── tracker.py                  (modify — tenant_id passthrough)

runtime/main.py                 (modify — --from-existing, --tenant, rescan,
                                          baseline, inspect, audit-verify)

agents/architect.md             (modify — Call 1/2 rules for codebase context)
agents/worker.md                (modify — related_files protocol, app_class scope)

docs/golden-paths/
├── M0-native-mobile.md         (new)
├── M1-flutter-rn.md            (new)
├── M2-pwa-wrapper.md           (new)
├── D0-native-desktop.md        (new)
├── D1-cross-desktop.md         (new)
└── index.md                    (modify — App Class section)

tests/
├── test_codebase_reader.py         (new — 12 test)
├── test_codebase_baseline.py       (new — 4 test)
├── test_architect_brownfield.py    (new — 3 test)
├── test_cli_brownfield.py          (new — 2 test)
├── test_golden_paths.py            (extend — +5 test)
├── test_executor.py                (extend — +4 test)
├── test_audit_redact.py            (new — 4 test: TC kimlik, e-posta, telefon, bypass)
├── test_audit_chain.py             (new — 3 test: chain build, verify OK, tamper detect)
└── test_tenant_passthrough.py      (new — 3 test: default, custom, path izolasyonu)

pyproject.toml                  (modify — add pathspec dependency, license=FSL-1.1)

fixtures/
├── flutter-sample/             (new — minimal 5-dosyalık Flutter)
└── fastapi-sample/             (new — Python karşılaştırma için)
```

**LOC tahmini (revize):**
- Codebase reader: ~3500 üretim + ~1500 test
- Productization (P1+P2+P3): ~600 üretim + ~400 test + LICENSE/NOTICE metni
- Docs: ~2000
- **Toplam: ~8000 LOC**

**Süre tahmini (revize):** 5–6 günlük dolu çalışma.
1. **Gün 0 (yarım gün):** Productization — LICENSE dosyaları, SPDX header retrofit script, audit upgrade (redact + chain), tenant_id passthrough wiring + 134 baseline test geçer kontrolü
2. **Gün 1:** `runtime/codebase/` skeleton + reader unit tests (1–7)
3. **Gün 2:** Frameworks detection + read_related + tests (8–12)
4. **Gün 3:** AppClass + M/D tiers + scorer tests (13–17) + golden path docs
5. **Gün 4:** Architect/Worker integration + sandbox conditional + integration tests (18–24)
6. **Gün 5:** Baseline + CLI + state machine + E2E demo

**Gün 0 bitiş kriteri:** 134 mevcut test hâlâ %100 geçer + yeni audit/tenant testleri (~10) yeşil. Tek bir mevcut test break ederse Gün 1'e geçilmez — productization retrofit'te hata var demektir.

---

## Demo script — M1 acceptance

```powershell
# 0. Kurulum
$env:ANTHROPIC_API_KEY = "..."
cd C:\Flutter\projects\ai-factory

# 1. Brownfield başlat — kullanıcının gerçek Flutter projesi
ai-factory new `
  --from-existing C:\Flutter\projects\my_app `
  --name my-app-search `
  "ana sayfaya arama çubuğu ekle"

# 2. Inspect — reader doğru gördü mü?
ai-factory inspect <id>
# Beklenen: frameworks=[flutter@3.x], app_class=mobile,
#           modules=[lib/features/home, lib/features/auth, lib/core, ...]

# 3. Baseline — kaç test geçiyor?
ai-factory baseline <id>
# Beklenen: cmd="flutter test", passing=42 (örnek)

# 4. PRD onayla, RFC bekle
ai-factory run <id>
ai-factory approve <id>  # PRD gate

# 5. RFC'yi oku — Module Breakdown'da kullanıcının gerçek modülleri var mı?
cat workspaces/<id>/RFC.md | grep -A20 "Module Breakdown"
# Beklenen:
#   | lib/features/home/   | (existing) | search bar widget eklenecek |
#   | lib/features/search/ | (new)      | search service + state mgmt |

# 6. Tier kontrolü
cat workspaces/<id>/state.json | python -c "import sys,json; d=json.load(sys.stdin); print(d['tier'])"
# Beklenen: M1

# 7. RFC onayla, run-all
ai-factory approve <id>
ai-factory run-all <id> --parallel

# 8. Acceptance — Worker output diff
git -C workspaces/<id>/source log --stat
# Beklenen: lib/features/home/home_page.dart modify (≤30 satır diff)
#           lib/features/search/search_bar.dart create

# 9. Baseline regresyon yok mu?
flutter test  # workspaces/<id>/source içinde
# Beklenen: passing >= 42 (baseline'dan az değil)
```

**Kabul:** Yukarıdaki 9 adımın hepsi yeşil olduğunda M1 DONE. Tek bir adım fail ederse plan revize edilir, M1 yeniden açılır.

---

## M1 sonrası açık kalanlar (M2'ye taşınanlar)

- `WorkerOutput.files[i].operation: "patch"` — full overwrite yerine hunk-based diff (silent rewrite riskini elimine eder)
- `WorkerOutput.files[i].operation: "update"` ile structural diff-ratio guard
- `module_scope: list[str]` — multi-path desteği (M1'de tek string'i implicit listeye wrap'liyoruz, ama TaskSpec şeması değişmiyor)
- `delete` operation
- Patch applier (`unified_diff_apply`)
- Tree-sitter ile Dart/TS public symbol parsing

Bunlar M1 demosunu engellemez — overwrite tek dosya üstünde Worker zaten yapabilir, sadece satır sayısı yüksek olur. Reviewer'ın diff-ratio uyarısı hâlâ devrede.
