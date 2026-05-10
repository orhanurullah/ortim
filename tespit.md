 1 # İter 7 — Brownfield desteği, mobile/desktop tier'ları, dev-loop UX
    2
    3 ## Context
    4
    5 İter 6 (a→d) sonrası senyör perspektifli "bu sistemi gerçekten kullanır mıyım?" değerlendirmesinde sistem şu ka
      rarla çıktı: **greenfield server-side SaaS için %85 hazır; mevcut projeye plug-in ya da mobile/desktop için kul
      lanılamaz.**
    6
    7 Bu plan o değerlendirmedeki eksiklikleri faz faz kapatır. Niyet: sistemi "Hello World factory"den "production'd
      a gerçek iş gören tool"a yükseltmek. v0.6d → v0.7d hedefi.
    8
    9 İter 7 yedi alt-fazda ilerler. **a→c kritik kapasite genişletmesi**, **d→f dev-loop ergonomisi**, **g uzun vade
      li operasyonel hijyen**. Her faz commit-able durumda kalır; mevcut 134/134 smoke baseline'ı korunacak.
   10
   11 ## Eksiklik haritası — öncelik
   12
   13 | # | Eksiklik | Etki | Faz |
   14 |---|---|---|---|
   15 | 1 | Codebase reader yok — Architect/Worker mevcut kodu okuyamıyor | Kritik. Brownfield desteği yok. | 7a |
   16 | 2 | Worker mevcut dosyayı okuyup diff uygulayamıyor; `operation: "update"` literal var ama mekanizma yok | Kr
      itik. Var olan kod düzgün düzenlenemiyor. | 7b |
   17 | 3 | `module_scope: str` tek path; task çoğu zaman `src/X` + `tests/X` + `migrations/` kapsar | Kritik. Sandbo
      x gerçek iş akışını engelliyor. | 7b |
   18 | 4 | Golden Paths sadece server-side (T0–T6); mobile/desktop için tier yok | Önemli. Repo Flutter altında ama
      Flutter desteği sıfır. | 7c |
   19 | 5 | Proje extend yok — her brief baştan başlıyor; "şu feature'ı da ekle" yapılamıyor | Önemli. İterasyonel ku
      llanım imkansız. | 7d |
   20 | 6 | Test runner her Worker attempt'inde tüm suite koşuyor | Önemli. Yavaşlık + maliyet. | 7e |
   21 | 7 | `run-all` sırasında dev-loop görünürlüğü yok (uzun sessizlik) | Önemli. UX zayıf. | 7e |
   22 | 8 | TDD zorunlu değil — Worker test+kod aynı anda yazıyor; TestReviewer post-hoc test'leri yakalayamıyor | İy
      i olur. | 7f |
   23 | 9 | Mid-task insan müdahalesi yok; sadece pause/abort | İyi olur. | 7f |
   24 | 10 | Bütçe gradient yok — sadece cap'te uyarı | İyi olur. | 7f |
   25 | 11 | Real deploy verification yok — RFC §11 yazıyor ama hiçbir şey `docker build` etmiyor | İyi olur. | 7g |
   26 | 12 | Schema migration agent + drift detector (eski iter 7 kapsamı) | İyi olur. | 7g |
   27
   28 ---
   29
   30 ## Faz 7a — Brownfield Codebase Reader
   31
   32 ### Hedef
   33
   34 Mevcut bir projeyi `WORKSPACE_ROOT` altına alıp Architect + Worker'a "buradaki kod tabanını gör" yeteneği verme
      k. Sistem böylece "FastAPI todo'ya JWT auth ekle" gibi brownfield task'ı için imagine değil read yapar.
   35
   36 ### Mevcut durum
   37
   38 - `runtime/agents/architect.py:32-53` — `extract_inputs(prd_text, project_id)`. Sadece PRD okur.
   39 - `runtime/agents/architect.py:55-96` — `draft_rfc(prd_text, tier_score, ...)`. Yine sadece PRD + template + ti
      er brief.
   40 - Worker `WorkerAgent.execute(task, rfc_text, project_id, prior_reasons)` — RFC + module_scope, mevcut kod yok.
   41 - `runtime/memory/loader.py` sadece static markdown yükler.
   42 - Workspace per-project isolated (`workspaces/<id>/`); mevcut repo eklenebilir mi diye kontrol mekanizması yok.
   43
   44 ### Değişiklikler
   45
   46 **1. `runtime/codebase/reader.py` (yeni)**
   47
   48 ```python
   49 @dataclass(frozen=True)
   50 class CodebaseSummary:
   51     root: Path
   52     file_tree: list[str]              # ilk N entry, gitignore-aware
   53     languages: dict[str, int]         # ext → file count
   54     public_symbols: dict[str, list[str]]  # path → exported names (AST)
   55     framework_hints: list[str]        # detected: ["fastapi", "pytest", ...]
   56     deps_manifests: list[str]         # ["requirements.txt", "pyproject.toml"]
   57
   58 def scan_codebase(root: Path, max_files: int = 2000) -> CodebaseSummary: ...
   59 def read_files(root: Path, paths: list[str], max_total_bytes: int = 100_000) -> dict[str, str]: ...
   60 ```
   61
   62 - `gitignore-aware` walk (`pathspec` kütüphanesi ya da minimal kendi parser).
   63 - Python için `ast.parse` → top-level def/class adları. JS/TS için regex bazlı (`export function`, `export clas
      s`).
   64 - Framework detection: `requirements.txt`/`package.json` parse + import scan top-N file.
   65
   66 **2. `runtime/agents/architect.py` genişlemesi**
   67
   68 - `extract_inputs(prd_text, project_id, codebase: CodebaseSummary | None = None)` — varsa user prompt'a "Existi
      ng codebase summary:" bloğu ekle.
   69 - `draft_rfc(...)` benzer şekilde codebase summary alır; tier seçimi PRD-based kalır (deterministic), ama RFC'n
      in Module Breakdown bölümü mevcut module yapısını referans alır.
   70
   71 **3. `runtime/executor/worker.py` genişlemesi**
   72
   73 - `WorkerAgent.execute(task, rfc_text, project_id, prior_reasons, related_files: dict[str, str] | None = None)`
       — task'ın `module_scope`'una giren mevcut dosyaların içeriği prompt'a inject edilir. `related_files` `runtime/
      codebase/reader.py:read_files()` ile her execute öncesi build edilir.
   74
   75 **4. CLI: `ai-factory new --from-existing <path>` flag'i**
   76
   77 - Mevcut repo'yu workspace'e symlink ya da copy. Default: symlink (hızlı, ama Windows'ta gerektirir admin/dev m
      ode → fallback copy).
   78 - Brief opsiyonel: yoksa Babel atlanır, doğrudan PRD_DRAFTING'e geçer (kullanıcı kendi PRD'sini yazar — "şu fea
      ture'ı ekle").
   79
   80 **5. State machine ek path**
   81
   82 - `INTAKE → PRD_DRAFTING` doğrudan (Babel atlanmış brownfield yolu için). Yeni state gerekmez; transition zaten
       `INTAKE → BABEL_PROCESSING → PRD_DRAFTING`. Workaround: `from-existing` flag'iyle Babel skip edilince intent.j
      son'u stub yaz.
   83
   84 ### Kritik dosyalar
   85
   86 | Dosya | Değişiklik |
   87 |---|---|
   88 | `runtime/codebase/reader.py` | YENİ — `CodebaseSummary`, `scan_codebase`, `read_files` |
   89 | `runtime/codebase/__init__.py` | YENİ — exports |
   90 | `runtime/agents/architect.py` | `codebase: CodebaseSummary` parametresi, prompt enrichment |
   91 | `runtime/executor/worker.py` | `related_files` parametresi |
   92 | `runtime/main.py` | `--from-existing` flag, Babel skip path |
   93 | `agents/architect.md` | "If `existing_codebase_summary` is in your context, base Module Breakdown on the actu
      al modules; do not invent." |
   94 | `agents/worker.md` | "If `related_files` are provided, your `update` operations must be diff-shaped — preserv
      e unrelated content." |
   95 | `tests/test_codebase_reader.py` | YENİ — gitignore, AST symbols, framework detection |
   96
   97 ### Test stratejisi
   98
   99 - Unit test: bu repo'nun kendisini scan et — `runtime` paketi altında public symbol'ler beklenen module'lere ma
      pleniyor mu.
  100 - Integration test: minimal sahte FastAPI projesi (geçici dizin) → scan → JSON snapshot karşılaştırma.
  101 - Read budget testi: `read_files` `max_total_bytes` cap'ini gerçekten enforce ediyor mu.
  102
  103 ---
  104
  105 ## Faz 7b — Worker file-read + multi-path scope
  106
  107 ### Hedef
  108
  109 Worker'ın `update` operasyonu artık gerçekten "mevcut dosyayı oku → ilgili kısmı değiştir → tüm dosyayı geri ya
      z" yapsın. Aynı zamanda `module_scope` çoklu path desteklesin (`src/auth/` + `tests/auth/` + `alembic/versions/
      `).
  110
  111 ### Mevcut durum
  112
  113 - `WorkerOutput.files[i].operation: Literal["create", "overwrite", "delete"]` — `update` literal'i şemada yok a
      slında, sadece prompt'ta sözü geçiyor.
  114 - `runtime/executor/sandbox.py:check_in_scope(path, scope)` — `scope: str` tek path; sibling/lookalike reject e
      der.
  115 - `runtime/orchestrator/task_dag.py:TaskSpec.module_scope: str` — tek string.
  116
  117 ### Değişiklikler
  118
  119 **1. `TaskSpec.module_scope: str | list[str]`**
  120
  121 - Pydantic `Union[str, list[str]]` + validator: list ise her eleman normalize edilir, boş list reject.
  122 - Geriye uyumluluk: tek string'i `[string]`'e çevir.
  123
  124 **2. `sandbox.check_in_scope(path, scope: str | list[str])`**
  125
  126 - Liste ise herhangi birinde geçerli ise OK; hepsinden de dışarıdaysa reject.
  127
  128 **3. `WorkerOutput.files[i].operation` literal'ine "update" eklenmesi**
  129
  130 - `update`: dosya zaten var, içerik tüm dosyanın yeni hali. Prompt'ta "if you receive an existing file in `rela
      ted_files`, output `operation: update` and provide the full new content; we'll diff it against the original for
       the commit."
  131 - `runner.py` write loop'unda: operation `update` ise `abs_path.exists()` zorunlu (false ise SandboxViolation).
       `delete` ise dosyayı kaldır.
  132
  133 **4. `runtime/executor/runner.py` related_files build**
  134
  135 - Worker çağrısından önce `task.module_scope` listesindeki path'lerin altındaki mevcut dosyaları (en fazla M do
      sya, ~50KB toplam) okur.
  136 - Çok dosya varsa: task description'da bahsedilen dosya isimlerini regex match et, sadece onları yükle.
  137
  138 **5. `agents/worker.md` güncellemesi**
  139
  140 - `related_files` block'unun nasıl tüketileceği, `update` operation'ının ne anlama geldiği, "do not regenerate
      unrelated lines" kuralı.
  141
  142 ### Kritik dosyalar
  143
  144 | Dosya | Değişiklik |
  145 |---|---|
  146 | `runtime/orchestrator/task_dag.py` | `module_scope` Union tipi + validator |
  147 | `runtime/executor/sandbox.py` | `check_in_scope` çoklu scope |
  148 | `runtime/executor/worker.py` | `WorkerOutput.files[i].operation` "update" + `related_files` parametresi |
  149 | `runtime/executor/runner.py` | `update` write yolu, `delete` kaldırma, related_files build |
  150 | `agents/worker.md` | Update protokolü |
  151 | `tests/test_executor.py` | Çoklu-scope sandbox test'leri |
  152 | `tests/test_worker_update.py` (yeni) | update lifecycle |
  153
  154 ### Test stratejisi
  155
  156 - Sandbox: çift-path scope (`["src/auth", "tests/auth"]`); sibling reject hâlâ çalışmalı.
  157 - Update operation: var olmayan dosyaya update → SandboxViolation.
  158 - Delete operation: dosya gerçekten silinmeli, sandbox dışına chmod yapmamalı.
  159 - WorkerOutput JSON parse: legacy `create` ve yeni `update` ikisi de geçerli.
  160
  161 ---
  162
  163 ## Faz 7c — Mobile / Desktop golden paths
  164
  165 ### Hedef
  166
  167 T0–T6 server-tier'larının yanına mobile ve desktop için yeni tier ailesi (M0–M2, D0–D1) eklemek. Tier scorer şu
       an sadece server context'inde çalışıyor; bunu app-class boyutuyla genişletmek gerek.
  168
  169 ### Mevcut durum
  170
  171 - `runtime/architecture/golden_paths.py` — `Tier` enum (T0–T6), `score_all`, `select_tier`. Mobile/desktop yok.
  172 - `docs/golden-paths/` — sadece T tier'ları.
  173
  174 ### Değişiklikler
  175
  176 **1. Yeni enum: `AppClass`**
  177
  178 - `web` (default — T0–T6 yolu)
  179 - `mobile`
  180 - `desktop`
  181
  182 **2. `GoldenPathInputs` genişletmesi**
  183
  184 - `app_class: AppClass = "web"`
  185 - `target_platforms: list[str]` (`["ios", "android"]`, `["windows", "macos", "linux"]`)
  186 - `offline_required: bool`
  187
  188 **3. Mobile tier'ları (M0–M2)**
  189
  190 - **M0 — Native (Swift / Kotlin)** — performance-critical, platform-specific UX, native SDK derinliği gerekiyor
      .
  191 - **M1 — Cross-platform (Flutter / React Native)** — tek codebase, %80 native UX, hızlı time-to-market. Default
      .
  192 - **M2 — Web + PWA wrapper (Capacitor)** — tek web codebase, native feel düşük öncelik.
  193
  194 **4. Desktop tier'ları (D0–D1)**
  195
  196 - **D0 — Native (SwiftUI/AppKit, WinUI, GTK)** — OS entegrasyonu derin, single platform.
  197 - **D1 — Cross-platform (Tauri / Electron / Qt)** — tek codebase. Default.
  198
  199 **5. Tier doc'ları**
  200
  201 - `docs/golden-paths/M0-native-mobile.md`
  202 - `docs/golden-paths/M1-flutter-rn.md` (default mobile)
  203 - `docs/golden-paths/M2-pwa-wrapper.md`
  204 - `docs/golden-paths/D0-native-desktop.md`
  205 - `docs/golden-paths/D1-cross-desktop.md`
  206
  207 İçerik: When/When NOT, stack matrisi, module layout (Flutter için: `lib/features/X/`), cross-cutting (state mgm
      t: Riverpod/Provider/Bloc; offline-first; secure storage; deep links), test stratejisi (widget + integration te
      st), CI (Fastlane/EAS), blocker durumları, migration paths (M2→M1→M0).
  208
  209 **6. Scorer**
  210
  211 - `score_all` fonksiyonu `app_class`'a göre dallanır:
  212   - `web` → mevcut T0–T6
  213   - `mobile` → M0–M2
  214   - `desktop` → D0–D1
  215 - Default M1 (Flutter), default D1 (Tauri) — never blocked, T4 paralelliği.
  216
  217 **7. Architect prompt güncellemesi**
  218
  219 - `app_class` PRD'den çıkar: `target_platforms`, "mobile app" / "desktop app" anahtar kelimeleri.
  220
  221 **8. Sandbox extension whitelist**
  222
  223 - Mobile için: `.dart`, `.swift`, `.kt`, `.kts`, `.gradle`, `.plist`, `.xcconfig`, `.pbxproj` (whitelist'e ekle
      ).
  224 - Desktop için: `.rs`, `.toml`, `.icns`, `.ico`, `.rc`.
  225
  226 ### Kritik dosyalar
  227
  228 | Dosya | Değişiklik |
  229 |---|---|
  230 | `runtime/architecture/golden_paths.py` | `AppClass` enum, M/D tier'ları, branched scorer |
  231 | `runtime/architecture/__init__.py` | Yeni exports |
  232 | `docs/golden-paths/M0..M2-*.md`, `D0..D1-*.md` | YENİ (5 dosya) |
  233 | `docs/golden-paths/index.md` | App-class bölümü |
  234 | `runtime/executor/sandbox.py` | Yeni extension whitelist'leri |
  235 | `agents/architect.md` | `app_class` çıkarımı + tier paths |
  236 | `tests/test_golden_paths.py` | M/D scorer testleri |
  237
  238 ### Test stratejisi
  239
  240 - Web brief → tier T4 seçimi (mevcut testler).
  241 - "Bir Flutter mobil uygulaması" brief → app_class=mobile, tier=M1.
  242 - "Tauri masaüstü dashboard" → app_class=desktop, tier=D1.
  243 - Mobile Worker output: `.dart` file → sandbox accept; `.exe` → reject.
  244
  245 ---
  246
  247 ## Faz 7d — Incremental project sessions (`extend`)
  248
  249 ### Hedef
  250
  251 Mevcut DONE projesine yeni feature ekleme akışı. `ai-factory extend <id> "yeni feature TR brief"` → mevcut PRD/
      RFC'ye delta üretir, yeni task'lar enqueue eder.
  252
  253 ### Mevcut durum
  254
  255 - DONE state terminal — TRANSITIONS'da çıkış yok.
  256 - TaskDAG bir kere üretilir, `task_dag.json` immutable.
  257 - `ai-factory new` her zaman INTAKE'ten başlar.
  258
  259 ### Değişiklikler
  260
  261 **1. State machine**
  262
  263 - Yeni state: `EXTENDING` (DONE'dan transition).
  264 - `DONE → EXTENDING` (extend command tetikler).
  265 - `EXTENDING → PRD_DRAFTING` (delta PRD üretiminden sonra).
  266 - PRD_AWAITING_APPROVAL ve sonrası mevcut akışı kullanır; sonunda yine DONE.
  267
  268 **2. Yeni delta agent: `runtime/agents/extender.py`**
  269
  270 - Input: mevcut PRD.md + mevcut RFC.md + mevcut task_dag.json + yeni brief (TR).
  271 - Output: PRD'ye yeni section'lar (delta), RFC'ye delta, ve yeni task'lar (mevcut DAG'a eklemeli).
  272 - Yeni task'ların ID'leri çakışmamalı (`T-001` zaten varsa `T-101` ya da `T-XXX-ext-N` formatı).
  273
  274 **3. CLI: `ai-factory extend <id> "<brief>"`**
  275
  276 ```
  277 DONE → EXTENDING (auto)
  278        runs extender → produces PRD delta, RFC delta, new tasks
  279        writes back to PRD.md (append section), RFC.md (append section),
  280        merges task_dag.json (preserves DONE tasks, adds new ones)
  281        transitions to PRD_AWAITING_APPROVAL
  282 ```
  283
  284 **4. TaskDAG merge logic**
  285
  286 - `task_dag.json` artık `version: int` taşır; her extend version'ı arttırır.
  287 - Worker/Reviewer task_status.json'da `version` field'ı görür; sadece güncel version task'ları execute edilebil
      ir.
  288 - DONE task'ları yeniden çalıştırılamaz (zaten mevcut korunma var).
  289
  290 **5. Memory'de project history**
  291
  292 - Extend sayısı, tarihleri, brief'leri audit'a `project_extended` event olarak.
  293
  294 ### Kritik dosyalar
  295
  296 | Dosya | Değişiklik |
  297 |---|---|
  298 | `runtime/orchestrator/state_machine.py` | EXTENDING state, DONE → EXTENDING transition |
  299 | `runtime/agents/extender.py` (yeni) | ExtenderAgent + delta logic |
  300 | `runtime/orchestrator/task_dag.py` | `version`, merge helper |
  301 | `runtime/main.py` | `extend` CLI command |
  302 | `agents/extender.md` (yeni) | Extender system prompt |
  303 | `tests/test_extender.py` (yeni) | Delta merge, ID çakışma kontrolü |
  304
  305 ### Test stratejisi
  306
  307 - DONE proje + yeni brief → PRD'ye section eklenir (eski section'lar değişmez).
  308 - TaskDAG merge: eski 5 task DONE; yeni 3 task PENDING; ID çakışması yok.
  309 - State transition: DONE → EXTENDING → PRD_DRAFTING → ... → DONE (yine).
  310
  311 ---
  312
  313 ## Faz 7e — Dev-loop UX
  314
  315 ### Hedef
  316
  317 Operatörün uzun süren `run-all` koşusu sırasında ne olduğunu görebilmesi + her Worker iter'inde 10 dakikalık tü
      m test suite koşmaması.
  318
  319 ### Değişiklikler
  320
  321 **1. Streaming console output**
  322
  323 - `runtime/main.py:_run_all_loop` — her task başlangıcında "▶ T-005 [worker]", LLM call sırasında spinner, hook
       çıktısı stream.
  324 - `rich.live.Live` veya `rich.progress` ile concurrent task'lar için ilerleme bar'ları.
  325
  326 **2. Akıllı test seçimi**
  327
  328 - Yeni env: `AI_FACTORY_TEST_CMD_INCREMENTAL` — tüm suite yerine değişen dosyaları etkileyen alt küme. Örnek: `
      pytest --testmon` (Python), `jest --findRelatedTests <files>` (JS).
  329 - `runtime/executor/test_runner.py:run_tests(workspace, changed_files: list[str] | None)` — `INCREMENTAL` cmd v
      arsa onu kullan, yoksa full `AI_FACTORY_TEST_CMD`.
  330 - Reviewer onayından sonra tek seferlik `AI_FACTORY_TEST_CMD` (full) koş — son güvence olarak.
  331
  332 **3. Audit'a per-step duration**
  333
  334 - Worker LLM süresi, test koşum süresi, reviewer süresi ayrı audit field. CLI `ai-factory budget` benzeri `ai-f
      actory profile <id>` komutu — task başına süre breakdown'u.
  335
  336 ### Kritik dosyalar
  337
  338 | Dosya | Değişiklik |
  339 |---|---|
  340 | `runtime/main.py` | Live progress, profile komutu |
  341 | `runtime/executor/test_runner.py` | Incremental mode |
  342 | `runtime/executor/runner.py` | changed_files compute, full-suite final pass |
  343 | `.env.example` | INCREMENTAL örneği |
  344 | `tests/test_test_runner_incremental.py` (yeni) | Incremental cmd routing |
  345
  346 ### Test stratejisi
  347
  348 - INCREMENTAL set + changed_files → INCREMENTAL cmd çağrılıyor.
  349 - INCREMENTAL unset → full TEST_CMD (mevcut davranış).
  350 - Reviewer onayından sonra full pass çağrılıyor mu — explicit assert.
  351
  352 ---
  353
  354 ## Faz 7f — TDD enforcement + cost gradient + mid-task intervention
  355
  356 ### 7f.1 — TDD iki-faz
  357
  358 Worker prompt'u iki adıma böl:
  359 1. "Önce sadece test dosyaları yaz; testler red verecek (henüz kod yok)." → Worker output sadece `tests/`.
  360 2. "Şimdi test'leri geçirecek implementasyon yaz." → Worker output `src/`.
  361 TestReviewer ilk fazda test'lerin gerçekten meaningful assert ettiğini doğrular (boş `assert True` yakalanır).
  362
  363 Opt-in: `AI_FACTORY_TDD_MODE=on` (default off — geriye uyumlu).
  364
  365 ### 7f.2 — Cost gradient
  366
  367 - Yeni env: `AI_FACTORY_BUDGET_WARN_PCT=80` (default %80).
  368 - BudgetTracker'a `is_in_warning_zone(project_id, cap)` ekle.
  369 - Run-all her batch sonunda warning eşiği aşılırsa konsola `[budget] $X / $Y (Z%)` warning bas; ayrıca audit'a
      `budget_warn` event.
  370
  371 ### 7f.3 — Mid-task user intervention
  372
  373 - CLI: `ai-factory annotate <id> <task-id> "<note>"` — task_status.json'a `user_notes: list[str]` push.
  374 - Worker'a `prior_user_notes` parametresi; `prior_review_reasons`'ın yanında prompt'a inject olur.
  375 - Kullanım: `run-all` koşarken başka terminalde `annotate T-007 "use bcrypt instead of sha256"`; bir sonraki re
      try'da Worker bu notu görür.
  376
  377 ### Kritik dosyalar
  378
  379 | Dosya | Değişiklik |
  380 |---|---|
  381 | `agents/worker.md` | TDD iki-faz protokolü |
  382 | `runtime/executor/worker.py` | `tdd_phase: Literal["test","impl"] \| None` |
  383 | `runtime/executor/runner.py` | TDD mode'da iki ayrı Worker call |
  384 | `runtime/budget/tracker.py` | warning zone helper |
  385 | `runtime/main.py` | `annotate` komutu, warning print |
  386 | `runtime/executor/status.py` | `user_notes` field |
  387 | `tests/test_tdd_mode.py`, `tests/test_budget_warn.py`, `tests/test_annotate.py` (yeni) | her özellik için |
  388
  389 ---
  390
  391 ## Faz 7g — Real deploy + drift + schema migration
  392
  393 ### 7g.1 — Real deploy verification
  394
  395 - `pre_deploy` hook chain'ine yeni built-in: `docker build` smoke (eğer `Dockerfile` workspace'te varsa).
  396 - `runtime/hooks/deploy_smoke.py` — Dockerfile bulursa `docker build --quiet` koşar; fail → DEPLOY_AWAITING_APP
      ROVAL'da kal.
  397 - Cloud-specific deploy hook'ları opsiyonel: `AI_FACTORY_DEPLOY_CMD` zaten var; `--dry-run` flag'leri için doc
      ekle.
  398
  399 ### 7g.2 — Drift detector
  400
  401 - `runtime/drift/detector.py` — periyodik (cron-tetiklenen) çalışır; mevcut RFC.md'yi taze kod taraması (codeba
      se reader Faz 7a'dan) ile karşılaştırır.
  402 - Drift sinyalleri:
  403   - RFC §7 Module Breakdown'da olmayan yeni modül.
  404   - RFC §6 API Surface'da olmayan endpoint.
  405   - RFC §4 Tech Stack'ten sapma (yeni dep eklendi).
  406 - CLI: `ai-factory drift <id>` — drift raporu basar; `--auto-rfc-update` ile Architect'i çağırır (yeni RFC delt
      a üretir, G2 onayı zorunlu).
  407
  408 ### 7g.3 — Schema migration agent
  409
  410 - `runtime/agents/migration.py` — DDL/migration task'ı çıktığında çağrılır (G3 SCHEMA_AWAITING_APPROVAL'da otom
      atik).
  411 - Output: forward migration + rollback script + iki-faz strateji notu (deploy compatible schema → deploy code →
       drop old in next release).
  412 - Reviewer chain'inde özel: SchemaReviewer (irreversible drop, FK cycle, type narrowing) → hard veto.
  413
  414 ### Kritik dosyalar
  415
  416 | Dosya | Değişiklik |
  417 |---|---|
  418 | `runtime/hooks/deploy_smoke.py` (yeni) | Docker smoke check |
  419 | `runtime/drift/detector.py` (yeni) | Drift compute + report |
  420 | `runtime/drift/__init__.py` (yeni) | exports |
  421 | `runtime/agents/migration.py` (yeni) | Schema migration agent |
  422 | `agents/migration.md` (yeni) | system prompt |
  423 | `runtime/main.py` | `drift` komutu, `migration` agent integration |
  424 | `tests/test_drift_detector.py`, `tests/test_migration_agent.py`, `tests/test_deploy_smoke.py` (yeni) | her bi
      ri için |
  425
  426 ---
  427
  428 ## Sıralama ve commit stratejisi
  429
  430 ```
  431 7a (codebase reader)
  432   └─ 7b (worker file-read + multi-scope) — 7a'ya bağımlı
  433        └─ 7d (extend) — 7a + 7b'ye bağımlı (extend mevcut kodu okumalı)
  434             └─ 7e (dev-loop UX) — bağımsız ama 7d'den sonra mantıklı
  435                  └─ 7f (TDD/cost/annotate) — bağımsız QoL
  436                       └─ 7g (deploy/drift/migration) — uzun vade
  437
  438 7c (mobile/desktop tier'ları) — 7a'ya hafif bağımlı (sandbox extension whitelist), 7b ile paralel ilerleyebilir
  439 ```
  440
  441 **Sebep:**
  442 - **7a önce** çünkü 7b ve 7d ondan veri çeker. Brownfield reader olmazsa diğerlerinin değeri yarıda kalır.
  443 - **7b ardından** çünkü Worker'ın update'i çalışmazsa 7a okuduğu kodu kullanamaz.
  444 - **7c paralel** koşabilir; mobile/desktop tier ekleme ile codebase reader birbirinden bağımsız.
  445 - **7d sonra** çünkü extend'in ana değeri brownfield context'te.
  446 - **7e–f QoL** — temel kapasite oturduktan sonra ergonomi.
  447 - **7g en sonda** — operasyonel hijyen, sistem zaten çalışırken eklenir.
  448
  449 Her faz sonunda smoke 100% geçmeli. Hedef: 134 → ~190 test, 100% pass.
  450
  451 ## Verification — uçtan uca sınama
  452
  453 **Faz 7a**
  454 - `ai-factory new --from-existing C:\Flutter\projects\ai-factory --name self-test`
  455 - Architect'in RFC çıktısında §7 Module Breakdown'da bu repo'nun gerçek modüllerinin geçtiğini gör (`runtime.ex
      ecutor`, `runtime.orchestrator`, ...).
  456
  457 **Faz 7b**
  458 - Mevcut bir `src/auth/login.py` dosyası olan workspace'te task: "JWT expiration check ekle". Worker `update` o
      peration döner; commit'te diff < 20 satır. Eski içerik kaybolmamış.
  459
  460 **Faz 7c**
  461 - Brief: "Bir Flutter todo uygulaması". Architect tier=M1, RFC `lib/features/todo/` layout'una referans veriyor
      .
  462
  463 **Faz 7d**
  464 - DONE proje + `ai-factory extend <id> "user profile sayfası ekle"`. PRD.md'ye section eklendi, eski section'la
      r bit-by-bit aynı, task_dag'da yeni T-101 var.
  465
  466 **Faz 7e**
  467 - 25-task DAG'ı `--parallel` koş; konsolda her task'ın live status'u akıyor, ortalama task süresi `INCREMENTAL`
       test mode'da %40 düşüyor.
  468
  469 **Faz 7f**
  470 - `AI_FACTORY_TDD_MODE=on` ile koş; T-005 için audit log'da `worker_phase=test` ve `worker_phase=impl` ayrı ent
      ry'ler.
  471 - `AI_FACTORY_BUDGET_CAP_USD=10 AI_FACTORY_BUDGET_WARN_PCT=80` set; 8$'a ulaşıldığında konsola warning + `budge
      t_warn` audit.
  472 - `ai-factory annotate <id> T-007 "X kullan"`; T-007 retry'da Worker prompt'unda bu not görünüyor (audit'a `wor
      ker_user_notes_count=1`).
  473
  474 **Faz 7g**
  475 - Workspace'te Dockerfile var; deploy hook çalıştığında `docker build` smoke geçiyor, audit'a `docker_build_sec
      onds`.
  476 - `ai-factory drift <id>` mevcut kodla RFC arasında 2 fark buluyor (yeni endpoint, eklenen dep).
  477 - DAG'a migration task girdiğinde MigrationAgent çağrılıyor; output forward + rollback iki dosya.
  478
  479 ## Notlar / riskler
  480
  481 - **7a — Token bütçesi:** mevcut codebase summary prompt'a inject edildiğinde, büyük repo'larda Architect input
       token'ı 50K+ olabilir. Cap: `--max-codebase-bytes 80000` flag, default 50KB; aşılırsa AST symbol özetine düş,
      full content yerine.
  482 - **7b — `update` semantik tuzağı:** LLM "diff yaz" derken aslında full file regenerate edebilir; sadece "opera
      tion: update" döndü ama içerik baştan rewrite. Reviewer chain'de Code Reviewer'a "if update, prompt-injected fi
      le ile model output line-diff oranını kontrol et — %30+ değişim varsa flag" ekle.
  483 - **7c — Sandbox patlaması:** `.swift`, `.kt`, `.dart`, `.rs` tek seferde beyaz listeye alındığında server-side
       projelerinde yanlış extension'lı dosya yazma riski artıyor. Mitigation: app_class'a göre conditional extension
       whitelist (mobile project'te `.py` sandbox dışı, web project'te `.dart` sandbox dışı).
  484 - **7d — DAG version drift:** extend'den sonra worker eski version'ın task'ını işlemeye çalışırsa workspace'te
      eski commit'leri bozar. Mitigation: status_file'da version mismatch → task otomatik AWAITING_HITL.
  485 - **7e — Live progress + ThreadPool:** rich.Live thread-safe olmayabilir; lock altında flush.
  486 - **7f.1 — TDD mode'un maliyeti:** Worker artık iki LLM call/task. Hard reviewer chain ile birlikte: 6 LLM call
  485 - **7e — Live progress + ThreadPool:** rich.Live thread-safe olmayabilir; lock altında flush.
  486 - **7f.1 — TDD mode'un maliyeti:** Worker artık iki LLM call/task. Hard reviewer chain ile birlikte: 6 LLM call
  9. Schema migration agent + drift detector — zaten iter 7'de planlı.
  10. Mid-task user intervention — ai-factory pause-task <id> <task-id> --message "şunu da yap" → bir sonraki retry'a
  inject olsun.
  11. Real deploy verification — RFC §11 deployment yazıyor ama hiçbir şey "gerçekten build oluyor mu?" diye sormuyor.
  En azından docker build smoke.
  12. Cost telemetry — bütçe yarıda kullanıldığında uyarı, sadece cap aşımı değil. Şu an "ya altında, ya üstünde" —
  gradient yok.

  Tek cümlelik karar

  Greenfield Python/TS server-side SaaS prototip için bugün kullanırım; mevcut Flutter projeme ya da herhangi bir
  mobile/desktop'a koymak için codebase reader + mobile tier'lar gelene kadar beklerim. Sıradaki yatırım belli: iter 7
  yerine "iter 6.5 = brownfield reader + Worker file-read" — bu olmadan sistem hayatta gerçek faydaya çıkamaz.

---

# Güncelleme — 2026-05-08

> Bu bölüm tespit.md'nin yazıldığı andan sonra alınan kararları, yapılan işleri ve revize edilmiş yol haritasını kayıt altına alır. Üstteki orijinal analiz (faz 7a–7g) hâlâ kanonik kapsam tanımı; aşağısı sadece **bunun ne kadarı yapıldı, nereden devam ediyoruz** sorusuna cevap.

## Karar revizyonu — son cümlenin durumu

Orijinal "Tek cümlelik karar"da **"codebase reader + mobile tier'lar gelene kadar beklerim"** denmişti. Bu blocker ortadan kalkmak üzere — M1 (Brownfield + Mobile) Gün 0–3 tamamlandı, Gün 4–5 sırada. M1 demosundan sonra "mevcut Flutter projem" use-case'i destekleniyor olacak.

Ürünleştirme tarafında: **open core + enterprise tier** modeli benimsendi (FSL-1.1-Apache-2.0 + Commercial). Sistem kişisel araç olmaktan çıkıp "agency / fintech / sağlık niş'inde audit'lı agentic dev pipeline" konumuna evriliyor.

## Mevcut durum (snapshot)

| Eksen | Durum |
|---|---|
| **Marka** | `ai-factory` → **Ortim** rename (CLI: `ortim`, alias `ai-factory` korunur). Copyright `ortim.dev`. |
| **Lisans** | Core: **FSL-1.1-Apache-2.0** (2 yıl sonra otomatik Apache-2.0). Enterprise tier: Commercial. SPDX header tüm runtime/tests/scripts dosyalarında. |
| **Audit log** | KVKK/GDPR PII redaction default ON (`AI_FACTORY_AUDIT_RAW=1` bypass). SHA-256 hash chain — tamper-evidence. 16 kategorili event taxonomy. |
| **Multi-tenant** | API yüzeyi hazır (`Project.workspace_path/load/save(tenant_id=...)`, `BudgetTracker.report(tenant_id=...)`). CLI flag enterprise/'e ertelendi. Default tenant legacy path'i korur. |
| **Brownfield reader** | `runtime/codebase/` — `scan_codebase()` (gitignore + 18 hard-skip + mtime+sha1 cache) + `read_related()` (direct match + description match + import-graph 1-hop + greedy byte fill + stale skip). |
| **Framework detection** | Flutter, FastAPI (pyproject + requirements), Pytest, Next.js, React, Vue, Svelte, Tauri, Electron. Tooling-aware `derive_app_class`. |
| **Tier ailesi** | Web T0–T6 (mevcut) + **Mobile M0/M1/M2** + **Desktop D0/D1**. `AppClass` enum; branched `score_all`; class-aware `select_tier` fallback (T4/M1/D1). |
| **Golden path docs** | 12 tier'ın hepsi belgelendi (When/When NOT, Stack matrisi, Layout, Cross-cutting, Test, CI, Risks, Migration). `index.md` 12-tier App Class tablosu içeriyor. |
| **Test suite** | **163/163 passing** (134 baseline + 11 P1+P2+P3 + 12 codebase reader + 6 mobile/desktop scorer). 0 regresyon. |
| **Yapılmadı (M1 içinde)** | Architect/Worker prompt'una codebase summary inject (Gün 4). Worker `related_files` parametresi (Gün 4). Conditional sandbox extension (Gün 4). Baseline contract + `--from-existing` CLI (Gün 5). E2E demo (Gün 5). |

**Tek satırlık özet:** M1 mimarinin omurgası ayakta — reader, tier, license, audit, tenant. Eksik olan tek şey **bunları Architect/Worker prompt'larına bağlamak** ve **CLI surface'i aşmak**.

## Sıradaki plan — M1 finali

### Gün 4 (sıradaki)
- `runtime/agents/architect.py` → `extract_inputs(prd, codebase=None)` ve `draft_rfc(..., codebase=None)` parametreleri
- `runtime/executor/worker.py` → `WorkerAgent.execute(..., related_files=None)` parametresi + prompt enrichment
- `runtime/executor/sandbox.py` → `check_extension(path, app_class="web")` conditional whitelist (web'de `.dart` reject, mobile'da `.py` izin)
- `runtime/executor/runner.py` → `read_related()` çağrısı, `related_files` build
- `agents/architect.md` ve `agents/worker.md` prompt güncellemeleri (Existing codebase summary block, related_files protokol, app_class scope)
- 7 yeni integration test: 3 architect-brownfield + 4 sandbox-conditional
- **163 → ~170 test, %100 geçer**

### Gün 5 (M1 finali)
- `runtime/codebase/baseline.py` — `TestBaseline` capture + per-task regression check + auto-detect (pubspec → flutter test, pyproject → pytest, package.json → npm test)
- `runtime/main.py` — `--from-existing <path>` flag, `link_mode={symlink,copy}` Windows fallback, Babel skip path
- Yeni CLI: `ortim baseline <id> [--recapture|--override N]`, `ortim rescan <id>`, `ortim inspect <id>`, `ortim audit-verify <id>`
- `runtime/orchestrator/state_machine.py` — `INTAKE → PRD_DRAFTING` brownfield shortcut
- 9 adımlık E2E demo script (M1-plan.md'de tanımlı): gerçek Flutter projesi → Architect M1 seçer → RFC mevcut modülleri referans verir → Worker overwrite gerçek dosya → baseline regresyon yok
- **170 → ~180 test, %100 geçer + E2E demo yeşil**

## Geliştirme yol haritası — M1 sonrası

Orijinal tespit.md'deki faz 7a–7g'yi M1–M5 milestone'larına yeniden gruplandırdım. Sebep: 7a + 7c "birlikte teslim edilmeden" ürünleşmiyor; 7b + `patch` semantik (yeni eklenen) "M2 = Worker file-update" altında konsolide edildi.

| Milestone | İçerik | Eski faz eşleniği | Hedef |
|---|---|---|---|
| **M0 (Gun 0)** | Productization: lisans + audit + tenant passthrough | (yeni) | ✅ Tamam |
| **M1 (Gun 1–5)** | Brownfield reader + Mobile/Desktop tier'lar | 7a + 7c | 🚧 Gün 3/5 — devam |
| **M2** | Worker file-update + `patch` protocol + multi-path scope | 7b + (yeni patch) | ⬜ Sırada |
| **M3** | Incremental project sessions (`ortim extend`) | 7d | ⬜ |
| **M4** | Dev-loop UX (live progress, INCREMENTAL test cmd) + cost gradient | 7e + 7f.2 | ⬜ |
| **M5** | TDD enforcement + annotate + deploy smoke + drift + schema migration + enterprise tier ilk parçaları | 7f.1 + 7f.3 + 7g | ⬜ |

### M2 — Worker file-update (Gun 6–9 tahmini)
**Hedef:** Worker `update`/`patch` operation'ı ile mevcut dosyayı bozmadan değiştirebilsin.
- `WorkerOutput.files[i].operation: Literal["create","overwrite","patch","update","delete"]`
- **`patch` operation** — output bir hunk listesi (`{file, old_block, new_block}`); server unified-diff uygular; baştan rewrite mekanik olarak imkansız
- `update` operation — full-file rewrite, structural diff-ratio guard (önceki content ile %50+ değişim → flag)
- `module_scope: list[str]` — multi-path scope (`["src/auth", "tests/auth", "alembic/versions"]`)
- Baseline regresyon contract aktif: passing test sayısı düşerse task `AWAITING_HITL`
- Demo: mevcut `lib/features/home/home_page.dart` (200 satır) → "AppBar'a search icon ekle" → patch döner, commit diff ≤25 satır

### M3 — `ortim extend` (Gun 10–12)
**Hedef:** DONE projesine yeni feature ekle.
- Yeni state: `EXTENDING`. Transition `DONE → EXTENDING → PRD_DRAFTING → ... → DONE`
- `runtime/agents/extender.py` — mevcut PRD/RFC/task_dag oku → delta üret → ID çakışma kontrolü ile merge
- TaskDAG `version: int` field'ı; status mismatch → AWAITING_HITL guard
- Demo: M1 ile DONE proje + `ortim extend <id> "favoriler sayfası ekle"` → PRD'ye section eklenir, eski task'lar DONE kalır, yeni T-101...T-105 PENDING

### M4 — Dev-loop UX + cost gradient (Gun 13–14)
**Hedef:** Uzun `run-all` koşusunda görünürlük + bütçenin %80'inde uyarı.
- `rich.Live` ile parallel batch live progress (thread-lock altında)
- `AI_FACTORY_TEST_CMD_INCREMENTAL` — `pytest --testmon`, `jest --findRelatedTests` benzeri
- Reviewer onayından sonra tek seferlik full TEST_CMD koşumu (final güvence)
- `AI_FACTORY_BUDGET_WARN_PCT=80` — cap'e değil, gradient'e uyarı
- `ortim profile <id>` — task başına süre breakdown'u

### M5 — TDD + annotate + ops hijyeni (Gun 15–20)
**Hedef:** TDD opsiyonu, mid-task insan müdahalesi, deploy/drift/migration dağıtık ekleri.
- TDD iki-faz Worker: önce `tests/`, sonra `src/`. `AI_FACTORY_TDD_MODE=on` opt-in.
- `ortim annotate <id> <task-id> "<note>"` — bir sonraki retry'da Worker prompt'una inject
- `pre_deploy` hook chain'ine `docker build` smoke (Dockerfile varsa)
- `runtime/drift/detector.py` + `ortim drift <id>` — RFC ile gerçek kod arasındaki sapma raporu
- `runtime/agents/migration.py` + SchemaReviewer (irreversible drop, FK cycle, type narrowing — hard veto)
- **Enterprise tier ilk parçası:** multi-tenant orchestrator iskelet (rate limit, tenant-aware LLM key mapping)

## Risk listesi — güncellenmiş

| Risk | Olasılık | Etki | Mitigation | Durum |
|---|---|---|---|---|
| Symlink Windows dev-mode gerektirir | Yüksek | `--from-existing` çalışmaz | Otomatik `copy` fallback | M1 Gün 5'te kodlanacak |
| Codebase summary büyük repo'da prompt budget patlatır | Orta | Architect Call 1 yavaş/pahalı | `to_prompt_text(max_bytes=2000)` truncate | ✅ Implemented |
| `read_related` import-graph regex-based, false-positive | Orta | Worker yanlış dosya görür | M1'de kabul; M2'de tree-sitter upgrade | Bilinçli kabul |
| Patch applier corner case (CRLF/LF, BOM) | Yüksek | Patch reject veya yanlış uygulanır | Strict mode + dry-run preview | M2'ye ertelendi |
| Baseline parse `flutter test` stdout formatına bağımlı | Orta | False regression alarm | Sayı bulunamazsa baseline disable + warn | M1 Gün 5'te kodlanacak |
| Mobile RFC §7'de Flutter detail seviyesi yetersiz | Orta | RFC cilasız | M1-flutter-rn.md doc kalitesi fixture-test | Kısmen — doc yazıldı, test M1 Gün 4'te |
| LLM "diff yaz" derken full file regenerate (silent rewrite) | Yüksek | Trust kırılır | M2'de structural patch operation = yapısal koruma | M2'ye ertelendi |

## Hâlâ açık olan stratejik sorular

1. **PyPI publish stratejisi** — Ne zaman? `name="ortim"` rezerv edildi mi? M1 demo sonrası mı?
2. **Enterprise tier ne zaman ürünleşir?** — M5'te iskelet, ama gerçek ödeme satışı için: SSO + audit retention + SLA → 3-4 ay sonra mı?
3. **Domain ortim.dev landing page** — açacak mıyız? Ne zaman?
4. **İlk 3 hedef müşteri segmenti** — agency, fintech, sağlık demiştik; hangisinden başlanacak?
5. **Documentation vs marketing** — README + tier docs şu an mühendis-odaklı; satışa karşı landing page ayrı mı?

Bu soruların cevabı M1 demo'sundan sonra netleşecek — demo'nun kim için "vay be" olduğunu görmeden segment seçimi körlemesine olur.

---

## 2026-05-08 — İlk uçtan-uca E2E (todo-greenfield-2) loglarından çıkan açık konular

İlk gerçek DeepSeek-eşliğinde greenfield run'ında (workspace `079fb8862112`) bir blocker çözüldü, üç madde sonraya bırakıldı.

### Çözülen
- **Sandbox `.gitkeep` reject** — Worker, RFC §7 modül layout'u için boş dizinlere `.gitkeep` placeholder yerleştirmek istedi; `_ALLOWED_BASENAMES` listesinde yoktu, hem extension hem basename match'i fail. `runtime/executor/sandbox.py` `_ALLOWED_BASENAMES`'e eklendi + `tests/test_executor.py::test_ext_accepts_known_basenames` regression test'i güncellendi. **Why:** `.gitkeep` standart Git konvansiyonu (boş dizin tracking); repo'nun kendi `.gitignore`'unda zaten `!workspaces/.gitkeep` istisna olarak vardı — sadece sandbox listesi atlamış.

### Açık (önceliğe göre)

**1. LLM transient retry — orta/yüksek öncelik.** İlk Babel çağrısı DeepSeek'te `503 Service is too busy` aldı; manuel re-run ile düzeldi (state machine `BABEL_PROCESSING`'den resume etti, bu çalışıyor ✓). Ama `runtime/llm/client.py:81` `messages.create` etrafında transient hata retry'ı yok. **Yapılacak:** Sadece `503 / 429 / overloaded_error` için exponential backoff (3 deneme, 2^n saniye). `tenacity` veya elden yazılmış küçük loop. Provider abstraction'da yapılmalı ki Anthropic + DeepSeek + ileride OpenAI hepsi kapsansın. **Neden iter konusu:** Yol B (production-ready) hedefiyle uyumsuz — özellikle DeepSeek stability'si Anthropic'ten düşük.

**2. Architect tier scoring — düşük/orta öncelik (felsefi).** "Küçük bir CLI todo yöneticisi" için **T2 (BaaS, score 100)** seçildi → 12 task: Supabase migrations, GitHub Actions CI, eslint-plugin-boundaries, integration test against Supabase test project, structured JSON logger. Bir CLI todo için T0/T1 (single binary, lokal SQLite, no network) doğal seçim. Score 100 demek girdiyle kararsız çakışma bile yok — yani weights "CLI / single-user / no-network / no-multi-tenant" sinyallerine yetersiz negatif ağırlık veriyor. **Yapılacak:** `runtime/architecture/golden_paths.py` içindeki tier scoring weights'i revize et; "CLI-only" / "single-user" / "no-server" sinyallerini negative skor olarak T2'den düşür, T0/T1'e taşı. Weights'i regression test'le donat. **Neden iter konusu:** Aşırı mühendislik = AI dev waste (orijinal kurumsal hedefin doğrudan ihlali); küçük projelerde sistem güvenilmez görünür.

**3. State machine `advance` re-run UX — düşük öncelik (niş).** `prd_approved` durumdayken tekrar `ortim advance <id> prd_approved --note "ok"` çalıştırılınca: `Cannot transition prd_approved -> prd_approved. Allowed: ['rfc_drafting']`. Mesaj teknik olarak doğru ama "already in prd_approved, next: rfc_drafting" daha net. **Yapılacak:** `runtime/orchestrator/state_machine.py` transition reject'inde "from == to" özel cümlesi. **Neden iter konusu:** Trivial, ama demo'da kafa karıştırır.

**Öneri:** Madde 1 İter 6'nın kuyruğuna (provider abstraction zaten orada), madde 2 İter 7d (tier docs ile birlikte) veya M2 başına, madde 3 herhangi bir UX cila turuna eklenebilir.

### Açık (E2E run #2'den çıkan, yeni)

**4. Mimari boşluk: root-level scaffolding ve shared resources — yüksek öncelik (blocker).** todo-greenfield-2'de **iki ayrı task** aynı sınıf hatayla reject oldu: önce T-001 (scaffold), sonra T-003 (db + migrations). Bu tek seferlik bir bug değil — DAG'ın 12 task'ından **7'si** (T-001, T-002, T-003, T-005, T-010, T-011, T-012) Worker ile icra edilemedi. Yani sistem mevcut haliyle T2 BaaS bir greenfield projesinin **%58'ini self-driving icra edemiyor** — pipeline değer önerisi büyük yara alıyor.

**Boşluğun iki yüzü:**

- **(4a) Scaffolding** (T-001 örneği): Orchestrator `module_scope: "shared"` verdiği task'ın description'ında `cli/`, `service/`, `repository/`, `auth/` klasörlerini ve kök `package.json` / `tsconfig.json` / `.gitignore` / `.env.example` yazmasını istedi. Sandbox `check_in_scope` doğru reject etti. Her T2/T3 projesinde mecburi root dosyası vardır (`Cargo.toml`, `pyproject.toml`, `pubspec.yaml`, `Gemfile` vb.).
- **(4b) Shared resources** (T-003 örneği): `shared/db.ts` + `shared/migrate.ts` scope içiydi, ama description'da `migrations/001_create_todos.sql` kökte. Bu *runtime'da artan, modüller-arası ortak bir varlık* — sadece bootstrap'ta değil, geliştirme boyunca da büyüyor. Aynı kategoride: kök `tests/` (T-010/T-011/T-012), kök `.github/workflows/` (T-005), kök `.eslintrc` (T-002).

Sandbox da Worker da hatalı değil — **sistemin "ortak resource'lar kime ait?" sorusuna cevabı yok**. Module isolation modül-içi geliştirme için tasarlandı; scaffolding + shared resources ayrı kategoride.

**Why:** Module isolation sistemin en güçlü kontratı (Worker hallucination'larını yapısal olarak engeller). Bu boşluğu "scope'u gevşet" diye doldurmak değer önerisini delik açar — doğru çözüm scaffolding'i Worker'ın görev alanından çıkarıp deterministik sistem işine çevirmek.

**Yapılacak (önerilen yol — "Seçenek A: deterministic bootstrap + shared resource konvansiyonu"):**

*Scaffolding (4a) için:*
- `runtime/architecture/bootstrap.py` (yeni) → `bootstrap_workspace_layout(workspace, modules: list[str], tier: Tier, app_class: AppClass) -> list[Path]`
- Per-tier root template'leri: `runtime/architecture/templates/{T0,T1,T2,T3}/{web,mobile,desktop}/` altında minimal `package.json` / `tsconfig.json` / `.gitignore` / `.env.example` / `Cargo.toml` / `pubspec.yaml` skeleton'ları
- `state_machine` `tasks_ready → tasks_executing` transition'ında otomatik çağrılır; idempotent (mevcut dosya üzerine yazmaz)

*Shared resources (4b) için — iki katmanlı çözüm:*
- **Konvansiyon:** "Tek modüle ait olmayan resource'lar `shared/` altında yaşar" — `shared/migrations/`, `shared/scripts/`, `shared/test-utils/`. Orchestrator system prompt'una bu kural eklenir, RFC §7 module breakdown bölümünde de bu netleştirilir.
- **İstisnalar:** `.github/workflows/`, `.gitignore`, `tsconfig.json` gibi platform/tooling tarafından kökte zorunlu olanlar bootstrap template'inde yer alır (Worker hiç dokunmaz). Test dizinleri (`tests/`) tier docs'ta tartışılmalı: T2'de modül-altı `auth/__tests__/` mi yoksa kök `tests/` mi olacağı standardize edilmeli — şu an her ikisi de gözüküyor.

*Hem scaffold hem shared resources için ortak:*
- Orchestrator system prompt'una sert kural: "**Asla** root-level path emit etme. Klasör layout'u + kök config dosyaları sistem tarafından deterministik kurulur. Her task'ın description'ı `module_scope` altında kalmalı; ortak resource'lar `shared/` altında."
- DAG validator: `module_scope` ile `description` uyumsuzluğunu yakala (heuristic: description'da scope dışındaki path patternleri — `^(migrations|tests|\.github|src|lib)/` regex — varsa reject + retry).
- Test: orchestrator'ın artık T-001 / T-003 sınıfı task emit etmediğini, bootstrap'ın 4 tier × 3 app_class kombinasyonunu doğru kurduğunu, `shared/migrations/` konvansiyonunun T2 RFC'lerinde belirdiğini.

**Geçici workaround (todo-greenfield-2'de uygulandı):**
- T-001: 5 modül klasörü + .gitkeep + minimal `package.json` / `tsconfig.json` / `.gitignore` / `.env.example` manuel yazıldı; DONE işaretlendi.
- T-003: `shared/db.ts` + `shared/migrate.ts` + `shared/migrations/001_create_todos.sql` manuel yazıldı (migration kökte değil, **`shared/migrations/` altında** — gelecekteki Seçenek A.b konvansiyonunu prefigure ediyor); DONE işaretlendi.
- T-002, T-005, T-010, T-011, T-012 atlandı — bunlar gerçek mimari fix gelene kadar çalışmaz.
- Sadece T-004 (logger), T-006 (auth), T-007 (repository), T-008 (service), T-009 (cli) gerçek Worker turlarıyla doğrulanabilir.

**How to apply:** Bu maddeyi **M2 öncesi blocker** olarak işaretle. Hem Seçenek A doğru kurulmadan hiçbir greenfield E2E demosu güvenli değil ("12 task'tan 7'si manuel" demoyu satılamaz hale getirir), hem brownfield path'inde T-001 zaten "use existing layout" diye atlanması gerekiyor (orchestrator prompt'u bunu da bilmiyor). M1'de "brownfield codebase reader" eklendiği gibi, **M1.5 / İter 7e** olarak "scaffold + shared resource layer" eklenmeli — büyük bir İter yerine küçük ama kritik bir ara adım. Tahmini efor: 1 gün (template'ler + bootstrap helper + orchestrator prompt update + DAG validator regex + 8-12 test).

**Not (felsefi):** Bu hata aslında orijinal kurumsal hedeflerin doğrulanması: "AI dev waste" tehlikelerinden biri tam olarak buydu — LLM mantıksal olarak çelişen bir task üretti, sandbox onu sessizce uygulamak yerine yapısal olarak yakaladı. Sistem tasarım açısından doğru davrandı; sadece sonraki adımı (otomatik scaffold) henüz öğrenmedi.

### Açık (T-004 başarılı turundan çıkan, yeni)

İlk gerçek Worker + Reviewer turu (T-004 logger) ilk denemede approved oldu — **pipeline değer önerisi doğrulandı** (toplam $0.0178, hash-zincirli audit log, in-scope file write, kaliteli kod). Bu sırada audit log'dan iki yeni boşluk ortaya çıktı.

**5. Provider routing role-bazlı çalışmıyor — orta öncelik.** İter 6 planının taahhüdü: "pahalı/yüksek-stake kararlar (Architect, Security Reviewer) Claude'da kalsın, ucuz/yüksek-hacim işler (Babel, Analyst) DeepSeek'e gitsin". Audit log gerçeği farklı: `babel_extract_ok`, `analyst_prd_draft`, `architect_extract_inputs`, `architect_rfc_draft`, `orchestrator_dag_ok`, `worker_output_ok`, `reviewer_verdict` — **11/11 event `provider="deepseek"`**. Yani `client_for(role)` ya henüz role-bazlı routing yapmıyor, ya bu env'de `ANTHROPIC_API_KEY` set değil ve fallback hep DeepSeek'e düşüyor. **Why:** T2 BaaS gibi düşük stake'te problem değil ama T3 (microservices) Architect kararını DeepSeek'e bırakmak production-ready'liği zedeler — yanlış tier seçimi katlanarak büyür. **Yapılacak:** `runtime/llm/router.py` (varsa) veya `client_for(role)` mapping'inin role-bazlı routing yaptığını doğrula; Anthropic key yoksa Worker/Babel için DeepSeek fallback OK ama Architect/Security/Test/Perf reviewer için **fail-loud** ("ANTHROPIC_API_KEY required for production-grade tier ≥ T2"). Audit log'a `routing_decision` event'i ekle: hangi role hangi provider'a gitti, neden (config-based vs fallback). **How to apply:** Madde 1 (LLM transient retry) ile aynı iter'a gidebilir — ikisi de `runtime/llm/` katmanında. Tahmini efor: yarım gün.

**6. Test Reviewer ve pre-commit hook sessizce skipped → yine de approve — yüksek öncelik (production hazırlık blocker'ı).** T-004 turunda audit log:
- `executor_tests`: `passed: false`, `skipped_reason: "no test command configured (set AI_FACTORY_TEST_CMD)"`, `exit_code: 0`
- `hook_event` (pre_commit): `skipped: true, skipped_reason: "no commands configured (set AI_FACTORY_LINT_CMD or AI_FACTORY_FORMAT_CHECK_CMD)"`
- `reviewer_verdict`: `approved: true, tests_passed: false, tests_skipped: "no test command configured"`

Reviewer testler atlanmış olduğunu **biliyor** ama yine de approve verdi. Bu Yol B (production-ready) hedefiyle doğrudan çelişir: kullanıcı bu sistemi gerçek bir projeye uygularsa, env vars set etmeyi unuttuğu için **silently no-test, no-lint** akışına girer ve sistem yine "approved ✓" der. Sahte güven duygusu = kurumsal hedeflerin tam zıddı. **Why:** Sistemin değer önerisinin omurgası "her task gate'lerden geçer". Gate'in bypass edilebilir olması (env eksikliğiyle) gate'i çürütür. **Yapılacak:**
- Tier-bazlı katı kural: T0 (single binary) test skip izinli warning, T1+ için **hard veto** ("test command required for tier ≥ T1; set AI_FACTORY_TEST_CMD").
- Aynı kural pre-commit hook için: T2+ projelerde lint/format-check yoksa Reviewer fail.
- M0/M1 mobile + D0/D1 desktop için varsayılan test komutu öner: Flutter → `flutter test`, Tauri → `cargo test`. Brownfield bootstrap zaten framework detect ediyor; test komutunu da auto-default olarak öner ("Detected Flutter, suggesting AI_FACTORY_TEST_CMD='flutter test'. Override or accept?").
- `reviewer_verdict` event şemasına `gate_bypass_reasons: list[str]` ekle — hangi gate'in neden atlandığı, retro audit için.

**How to apply:** İter 6b (Security/Test/Perf reviewer hard veto) zaten plana var; **bu maddeyi 6b'nin ilk işi yap**. M1.5 mimari fix'inden sonra, M2 öncesi tamamlanmalı. Tahmini efor: yarım gün (config-based veto kuralı + auto-default suggestions + 6-8 test).

**Not (felsefi):** Madde 4 sandbox'ın yapısal disiplinini kanıtladı; madde 6 ise tam zıddını gösteriyor — Reviewer "soft" disiplin uyguluyor (tests_skipped görüp yine de OK). Sandbox hard, Reviewer soft. Production-ready hedef için ikisinin de hard olması gerek. Bu, "deterministic gates first, LLM judgment second" prensibinin Reviewer kademesine henüz girmediğinin işareti.

### Açık (T-006→T-009 zincirinden çıkan, yeni)

T-006/T-007/T-008 ilk denemede approved (auth/repository/service). T-009 (CLI) reject oldu ama **doğru sebeplerle** — Reviewer cross-task interface uyumsuzluğunu (T-008 `list({all: true})` vs T-009 `list('all')`) ve L1 DI prensip ihlalini yakaladı. Bu sırada iki ayrı bug ortaya çıktı.

**7. Reviewer reject sonrası auto-retry tetiklenmiyor — yüksek öncelik (tasarım taahhüdü ihlali).** Sistemin değer önerisinin omurgasında "Worker/Reviewer agent pair with 3-retry quota" var: bir `execute` komutu, reject olursa Reviewer reasons'ı Worker prompt'una geri besler, otomatik 2. ve 3. denemeyi yapar. Self-correcting loop bu sistemin "AI dev waste" iddiasının çekirdeği. T-009'da gerçekleşen: `attempt 1/3` çıktı, reject oldu, **döngü bitti** — `task_status.json::T-009.attempts: 1`, `status: PENDING`. Kullanıcı `ortim execute T-009`'u manuel tekrar etmek zorunda. Yani şu anki davranış: bir CLI çağrısı = bir attempt, "3-retry quota" sadece counter olarak çalışıyor, **otomatik retry loop** yok.

**Why:** Self-correcting loop olmadan sistem "approval fatigue" sorununu çözmüş olmuyor — kullanıcı her reject'te manuel müdahale gerek. Memory'deki "Worker/Reviewer agent pair with 3-retry quota" mimari prensibi bu mevcut implementasyonla doğrulanmıyor. Bu, manifesto ile kod arasında en büyük uyumsuzluk.

**Yapılacak:** `runtime/executor/runner.py:execute_task` (veya muadili) içinde reject branch'inde:
- `record.last_review_reasons`'ı Worker user prompt'una "Previous attempt was rejected with these issues: ..." şeklinde gömerek tekrar Worker.run() çağır
- `attempts < MAX_RETRIES` koşulu sağlandığı sürece loop dön (Orchestrator'daki retry-on-validation-failure pattern'i gibi — orada zaten doğru implementli)
- Her retry'da audit log: `worker_retry_after_review` event'i, hangi reason'ların prompt'a iletildiği görsün
- Sadece tüm 3 attempt fail ise `status: FAILED + AWAITING_HITL`'e geç
- Test: mock Reviewer (1. çağrıda reject + 2. çağrıda approved) → record.attempts == 2, status DONE bekle

**How to apply:** Bu **M2 öncesi mutlaka** tamamlanmalı — şu hâliyle "self-driving %75" iddia edemeyiz, gerçekte "kullanıcının manuel re-trigger ettiği %75". Tahmini efor: yarım gün (loop kodu + mock-based unit test + integration test). İter 7d veya M1.5'in parçası olabilir.

**8. Windows console UnicodeEncodeError — orta öncelik (Windows-fatal CLI bug).** T-009 reject'inde Worker yazdığı kodda `[✓]` (U+2713) kullandı, Reviewer bunu `reasons[]` listesine aldı, CLI `_render_execution_result` (`runtime/main.py:929`) Rich console'a yazarken Windows PowerShell'in `cp1254` (Windows-1254 Turkish) codec'i bu karakteri encode edemediği için **`UnicodeEncodeError: 'charmap' codec can't encode character '✓'`** ile patladı. `task_status.json` doğru güncellendi (`status: PENDING, last_review_approved: false, reasons` listesinde 6 madde var) ama console output yarım kaldı + traceback ekrana boğdu. **Why:** Windows kullanıcısı (= ana hedef geliştirici kitlesinin önemli bir bölümü) **her non-ASCII içeren Reviewer reject'inde CLI crash görür**. Production demoda bu kabul edilemez. Üstelik bu sadece Reviewer'ın Worker kodunu alıntılamasıyla tetiklenmiyor — Architect/Orchestrator'ın Türkçe açıklaması, RFC'deki em-dash, herhangi bir emoji aynı sonucu verir.

**Yapılacak:**
- `runtime/main.py` entry point'inde `sys.stdout.reconfigure(encoding="utf-8", errors="replace")` ve `sys.stderr` aynısı (Python 3.7+ destekli) — process başlangıcında bir kez
- Veya CLI bootstrap'a env: `os.environ.setdefault("PYTHONIOENCODING", "utf-8")` (etkili olması için subprocess re-exec gerekebilir, bu yüzden reconfigure tercih)
- Rich console'u explicit utf-8 file ile init: `Console(file=open(sys.stdout.fileno(), "w", encoding="utf-8", buffering=1, closefd=False))` veya benzeri
- Test: Windows-only smoke test — `[✓]` içeren bir reasons listesini render etmeyi dene, exit code 0 + traceback yok bekle

**How to apply:** Bu UX cila değil, **Windows'ta blocker** — bir geliştirici sistemi ilk denemesinde reject çıktısı görür ve traceback'le karşılaşırsa terk eder. M1 demosundan **önce** halledilmeli. Tahmini efor: 1-2 saat (3 satırlık fix + Windows CI smoke test). İter 7d veya M1.5'in parçası olabilir.

**Not (felsefi):** Bu da Madde 4 ile aynı kategoride bir doğrulama: Reviewer **gerçekten** kalite gate olarak iş gördü (cross-task interface uyumsuzluğu + L1 DI ihlali yakaladı, formaliteyi değil semantiği denetledi). Yani sistem mantığı doğru çalışıyor — manuel re-trigger gereksiniminden ve Windows render bug'ından bağımsız olarak, **DeepSeek-chat ucuzluğuyla bu kaliteyi sağlayabiliyor olması Yol B hipotezinin en güçlü kanıtı**. Madde 7'yi düzelttiğimizde Reviewer'ın yakaladığı 4 hata (interface, DI, output format, error handling) Worker tarafından otomatik fix edilebilir mi — bu **gerçek self-correcting loop** testi M1 demonun en güçlü göstergesi olur.

---

## 2026-05-08 — M1.5 MVP yaması (madde 4, 7, 8 büyük ölçüde kapatıldı)

E2E run sonrası tespitten doğrudan koda geçildi. Önemli olduğu için ayrı turda (T0/T1/T3 + mobile/desktop template'leri **bilinçli olarak** sonraki tura bırakıldı — YAGNI, todo-greenfield demosu için T2/web yeterli).

### Yapılanlar

**Madde 8 — Windows console UnicodeEncodeError → KAPATILDI.** `runtime/main.py:18-26` modül load time'ında `sys.stdout` ve `sys.stderr` üzerinde `reconfigure(encoding="utf-8", errors="replace")` çağrılıyor (no-op platform/streamlerde, `OSError`/`ValueError` swallow edildi). Reviewer reasons içinde `[✓]`, em-dash, emoji vs. olsa bile CLI çakılmaz. Defensive 3 satır olduğu için ayrı unit test eklenmedi — Windows entegrasyon doğrulaması bir sonraki gerçek run'da T-009 retry ile yapılır.

**Madde 7 — Auto-retry loop → BÜYÜK ÖLÇÜDE KAPATILDI.** `runtime/main.py:execute` ve `_run_all_loop` (sequential branch) içinde `while result.status == TaskStatus.PENDING` döngüsü eklendi. `execute_task` zaten `prior_reasons`'ı 2. attempt'ten itibaren Worker user prompt'una geçiriyor (`runner.py:154`) ve attempts >= max_attempts olunca AWAITING_HITL'e otomatik eskaler ediyor — yani döngü trivial: PENDING ise tekrar çağır, başka durumda dur. Her iter'da `status_file.save` + `_render_execution_result`. **Açık kalan**: (1) `_run_all_loop` parallel branch'i — merge lock + worktree etkileşimi var, ayrı tasarım gerek; (2) loop için unit test — mock Worker/Reviewer kurulumu zaman alır, manuel doğrulama (T-009 retry) öncelikli. Bu iki kalan parça yeni bir madde 7b olarak kayda geçti.

**Madde 4 — Root scaffolding + shared resources → BÜYÜK ÖLÇÜDE KAPATILDI.** İki cepheli çözüm uygulandı:
- *Sert kısım:* `runtime/architecture/bootstrap.py` (yeni, ~130 satır) → `bootstrap_workspace_layout(workspace, modules, tier, app_class, project_name)`. T2/web için tam template (package.json, tsconfig.json, .gitignore, .env.example) + her tier/app_class için universal fallback (modül klasörleri + .gitkeep + minimal .gitignore). Idempotent (mevcut dosyalara dokunmaz). `main.py:_bootstrap_if_ready` helper'ı `tasks_ready → executing` transition'ından önce hem `execute` hem `run-all` komutlarında çağırıyor; `golden_path_inputs.json`'dan tier'i deterministik olarak `select_tier` ile yeniden hesaplıyor (yeni Project field'i gerekmedi). Audit log'da `workspace_bootstrapped` event'i. 5 unit test eklendi (`tests/test_bootstrap.py`): module folder + .gitkeep, T2/web tier files içerik, idempotency, fallback (T0/mobile = sadece klasör), ikinci çağrı no-op.
- *Yumuşak kısım:* `agents/orchestrator.md` prompt'u sertleştirildi: Hard Rule 11 (NEVER write outside `module_scope`, system bootstraps root), Hard Rule 12 (shared resources convention: migrations → `shared/migrations/`, scripts → `shared/scripts/`, etc.). "Foundational Task Examples" bölümündeki yanlış-yönlendiren T-001/T-002/T-003 scaffold örnekleri **kaldırıldı**, yerine *first-batch-feature-work* örnekleri (`shared/db.ts`, `shared/migrations/001_users.sql`, `shared/logger.ts`, `auth/index.ts`) ve "system handles before tasking" yasak listesi geldi. Anti-Patterns'e iki yeni kalem eklendi.
- **Açık kalan**: T0/T1/T3 + mobile/desktop template'leri (M2'ye/iter 7d'ye); DAG validator regex (orchestrator prompt yeterince ağır olabilir, validator gereksiz katman olabilir — bir sonraki gerçek run'da görülür); shared resources prompt kuralının tutup tutmadığını gözlem.

### Test sayımı: 178 → 183 (+5 bootstrap test)

### Sonraki run'da doğrulanacak (kullanıcı manuel)
1. **Madde 7 manuel**: aynı projede `T-009`'u `attempts: 1, status: PENDING` halinde tekrar dene → bu sefer attempts 2-3'e otomatik gitmeli, Reviewer'ın yakaladığı interface uyumsuzluğunu Worker fix ediyor mu? "Gerçek self-correcting loop" demosu.
2. **Madde 4 manuel**: yeni bir greenfield projesinde `ortim execute <yeni>` çalıştır → `_bootstrap_if_ready` çağrılmalı, modül klasörleri + tier root dosyaları otomatik oluşmalı, Orchestrator artık T-001 scaffold task'ı emit etmemeli (yeni prompt etkili mi). DAG'da kalan task'lar tamamen module-içi olmalı, manuel intervention gerekmeden tamamlanmalı.
3. **Madde 8 manuel**: bir reject mesajında Reviewer'ın yazdığı `[✓]` veya em-dash karakteri Windows PowerShell'de patlamadan render edilmeli.

### Açık kalan / yeni eklenen tespit maddeleri

**7b. Auto-retry parallel + unit test — orta öncelik.** `_run_all_loop` parallel branch'i şu an tek-pass; merge lock + worktree etkileşiminden ötürü retry loop'u yerleştirmek non-trivial. Unit test'i de yazılmadı (mock Worker + Reviewer kurulumu, integration tarzı test gerekir). M2 öncesi tamamlanmalı. Tahmini efor: 4-6 saat (parallel branch retry + 2-3 mock-based test).

**4b. Tier × app_class template matrisi tamamlanması — düşük öncelik (genişletme).** Şu an sadece T2/web template tam; T0/T1/T3 + mobile/desktop fallback (sadece modül klasörleri + .gitkeep). M2'de Flutter (mobile) brownfield demoları için pubspec.yaml template, Tauri (desktop) için Cargo.toml template gerek. Her tier × app_class kombinasyonu için ~30-50 satır JSON + 1 test. M1 demosu T2/web ile yapılacaksa bu turda gerek yok.

**4c. DAG validator regex — düşük öncelik (gözlem-bağımlı).** Orchestrator prompt sertleştirme yeterli olabilir; deterministic post-validator katmanı (description'da `^(migrations|tests|\.github)/` regex match'i = reject) ekstra savunma sağlar ama prompt yeterince ağırsa abartı olabilir. Bir sonraki gerçek run'da Orchestrator'ın yeni prompt'la T-001 scaffold task'ı emit etmediği gözlemlenmeli; emit ediyorsa validator gerek.

---

## 2026-05-08 — Vision Roadmap (M2–M5): Strategic Modules Beyond M1.5

**Note on language:** From this point forward (per user directive 2026-05-08), all new entries in this file are written in English. Pre-existing Turkish content above is left as historical record.

**Context.** The first real E2E run (todo-greenfield-2) and the T-009 retry forensic exposed a structural truth: items 1–8 above are *tactical / bug-fix-tier* problems on top of a fundamentally **monologue-shaped** pipeline (Babel → Analyst → Architect → Orchestrator → Worker → Reviewer, all one-shot). The user's product vision is **dialogue-shaped** (interactive intake, stack negotiation, conversational analyst), with per-project Skills (Claude-skill semantics), method-level granularity, knowledge layers (Obsidian/RAG), MCP tool calling, and per-query dynamic LLM routing. Closing every item 1–8 still leaves the pipeline a monologue.

**Senior architect verdict.** The vision is defensible and value-additive — modern agentic platforms (Cursor Composer, Devin, Copilot Workspace) treat conversational intake as table stakes, and Skills-style context injection is the only structural answer to model knowledge gaps observed in T-009 (Commander.js `help()` API misuse). However, the pieces are **not equally valuable** and have **hidden ordering constraints**: deploying method-level decomposition or Skills on top of a non-deterministic Reviewer multiplies the T-009 verdict-drift problem. Therefore Phase 0 (Reviewer rubric + binary acceptance criteria + test-runner auto-detect) is a hard prerequisite for everything that follows.

**Deliberate exclusion from the roadmap.** Full method-level DAG decomposition (vision pillar 4, maximalist reading: 12-task DAG → 50-task DAG, every method its own task) is **NOT** in this roadmap. Two-shot Worker (plan + execute, M4 below) is the pragmatic 80%-of-value alternative. Operational fallout of full method-DAG (parallel merge complexity, audit log inflation, retry budget per method) outweighs the marginal granularity gain unless two-shot Worker proves insufficient — and that observation is itself a Phase 4 question, not a roadmap commitment.

### 9. Phase 0 — Foundation Hardening — **STATUS: COMPLETE (2026-05-08)**, pytest 183 → 195 (+12)

**Problem this solves.** T-009 forensic showed three structural diseases that compound in any larger module: (a) Reviewer is a non-deterministic interpreter, not a deterministic referee — the same code received contradictory verdicts across attempts ("add 'Created todo' label" → next attempt "ID alone, no prefix"); (b) Worker cannot translate L1 abstract principles ("Dependency Injection always") into concrete diff edits — three attempts failed to remove `new TodoService()`; (c) acceptance criteria contain ambiguous adjectives ("readable format", "success message") that invite Reviewer reinterpretation. None of these are LLM-tier problems; all are prompt/contract/schema problems.

**Three-axis fix bundled as one phase:**

**9a. Reviewer rubric — structured per-criterion verdict.**
- `runtime/executor/reviewer.py`: extend `ReviewVerdict` schema with `criteria_verdicts: list[CriterionVerdict]` where `CriterionVerdict = {criterion: str, status: "pass"|"fail"|"partial"|"unverifiable", evidence: str, code_quote: str | None}`. Keep legacy `approved`, `reasons`, `suggestions` fields, derive them from the criteria verdicts (backward compat).
- `agents/reviewer.md` prompt sertleştirme: "You may NOT introduce new requirements not in the criteria list. You MUST quote the exact code that fails. If a criterion is ambiguous, mark `unverifiable` — do NOT silently invent a stricter version. Verdict is a function of the original criterion text + the code, not your interpretation."
- `unverifiable` count > 0 → task escalates to AWAITING_HITL with reason "criteria_design_failure" (the criterion is broken, not the Worker).
- Verify `temperature=0.0` is enforced in reviewer LLM call (currently `runtime/executor/reviewer.py`).
- Audit log: each `reviewer_verdict` event now embeds the structured criteria array.

**9b. Acceptance criteria binary-checkable enforcement (Orchestrator side).**
- `agents/orchestrator.md` Hard Rule 10 sıkılaştırması: ban-list of words that signal subjective criteria — `readable`, `user-friendly`, `good`, `proper`, `success`, `appropriate`, `intuitive`, `clean`, `nice`. Every criterion must be either: regex match on stdout/stderr, exit code assertion, JSON shape assertion, file existence assertion, or function-call signature shape. Examples in prompt.
- Optional safety net (deferred to obs): post-Orchestrator validator reads each criterion against the ban-list and rejects (force retry) if hits found. Skip for now if prompt sertleştirme alone produces clean DAGs in next run.

**9c. Test runner auto-detect — close the silent-skip loophole.**
- `runtime/architecture/bootstrap.py`: extend bootstrap layer to write `.ai-factory.env` (or update existing `.env.example`) with a tier+app_class-derived `AI_FACTORY_TEST_CMD`. T2/web → `npx vitest run`; T2/mobile (Flutter) → `flutter test`; T2/desktop (Tauri) → `cargo test`. Idempotent: never overwrite if file exists.
- `runtime/executor/test_runner.py` (or wherever the env-read happens): if `AI_FACTORY_TEST_CMD` unset, attempt to read from `.ai-factory.env` in workspace root before falling back to skip.
- Reviewer rubric (9a): if `tests_skipped` is true and tier ≥ T1, mark every test-related criterion as `unverifiable` and escalate. No more silent skip + approve.

**Effort estimate:** 4–6 hours total. Tests: 6–8 new (rubric schema, unverifiable escalation, banned-word ban-list, test-cmd auto-write, etc.). pytest count target: 183 → 191+.

**Why this must come first:** every module in M2–M5 calls Reviewer or relies on a stable Worker→Reviewer contract. Phase 0 freezes that contract.

**Implementation summary (2026-05-08, same-session completion).** Final pytest 195 (+12 new, −2 legacy: rubric tests in `tests/test_executor.py` replaced; chain tests in `tests/test_reviewer_chain.py` migrated to new schema via shared `_approved_code_verdict()` helper).

- *9a:* `runtime/executor/reviewer.py` — `CriterionVerdict { criterion, status, evidence, code_quote }` and rubric-shaped `ReviewVerdict { criteria_verdicts, l1_violations, suggestions }` with derived `approved` / `reasons` / `has_unverifiable` properties. `agents/reviewer.md` prompt fully rewritten in English with status semantics, hard rules, banned-paraphrase rule, examples. `runtime/executor/runner.py` adds `verdict.has_unverifiable` branch → escalates to AWAITING_HITL with `executor_criteria_design_failure` audit event (Worker not at fault, criterion is). `temperature=0.0` already enforced in reviewer LLM call (verified, no change).
- *9b:* `agents/orchestrator.md` Hard Rule 10 strict-binary form: required-shape list (regex/exit-code/JSON-shape/HTTP-status/file-existence/function-signature), explicit banned-words list (`readable`, `user-friendly`, `good`, `proper`, etc.), and ❌→✅ examples for the three failure modes seen in todo-greenfield-2 T-009 ("readable format", "Invalid command prints help text", "Error in command prints error message"). Post-Orchestrator regex validator deferred — observe whether prompt sertleştirme alone produces clean DAGs in the next greenfield run; fall back to validator only if prompt fails.
- *9c:* `runtime/architecture/bootstrap.py` adds `_TEST_CMD_BY_TIER_APP` map ((tier, app_class) → command) and writes `<workspace>/.ai-factory.env` with `AI_FACTORY_TEST_CMD="..."` when tier+app_class has a known runner (T1/T2/T3 web → `npx vitest run`, T1/T2 mobile → `flutter test`, T1/T2 desktop → `cargo test`). `.ai-factory.env` added to universal `.gitignore` so secrets don't leak. `runtime/executor/test_runner.py::configured_plan(workspace)` now reads `.ai-factory.env` as fallback when env var unset. Reviewer rubric (9a) does the rest: tests skipped + criterion implies runtime check → status=`unverifiable` → AWAITING_HITL.
- *Tests added:* `tests/test_executor.py` (5 rubric tests: empty-not-approved, all-pass-approved, fail-blocks, unverifiable-design-failure, l1-blocks). `tests/test_bootstrap.py` (3 tests: `.ai-factory.env` written for T2/web, skipped for unknown tier+app, `.gitignore` contains `.ai-factory.env`). `tests/test_test_runner.py` (6 tests: env wins over file, file used when env unset, none-when-both-missing, missing-key, quoted values, `AI_FACTORY_TESTS_ENABLED=false` overrides everything).
- *Tests migrated:* `tests/test_reviewer_chain.py` 4 chain tests now use `_approved_code_verdict()` returning rubric-shaped JSON aligned with `_task()`'s acceptance criteria.

**What this changes for the next E2E run.** A T-009-class failure should now manifest one of three ways: (a) Worker fixes the L1 DI violation in attempt 2 because the rubric's `[L1]` reasons are concrete (`new TodoService()` quoted in `code_quote`); (b) ambiguous criterion ("readable format") gets `unverifiable` and the task goes straight to HITL with `criteria_design_failure` instead of looping uselessly through 3 attempts; (c) Orchestrator never emits the ambiguous criterion in the first place because Hard Rule 10 banned-words list rejects them at DAG generation. All three outcomes are objectively better than the T-009 we observed today.

**Remaining Phase 0 follow-ups (deferred, low priority):** post-Orchestrator regex validator (only if next run shows banned-words still slipping through prompt); audit log redaction review for `criteria_verdicts.code_quote` (could leak secrets if Worker pasted them — defensive, low priority since L1 already forbids secrets in code).

### 15. Sandbox-violation feedback NOT injected into Worker prior_reasons — HIGH PRIORITY (auto-retry loop loses its teeth on this path)

**Discovery context.** Verification run `todo-greenfield-3` (2026-05-08, post-Phase-0). Phase 0 prompt sertleştirme worked (Orchestrator emitted 0 scaffold tasks, all 11 tasks module-scoped, tests at module scope, full DAG self-driveable in principle). T-001 approved on first attempt. T-002 (`module_scope: store`) rejected with `model/todo.go: path model/todo.go is not under module_scope store` on attempt 1, **then attempt 2 reproduced the identical error verbatim, and attempt 3 again the identical error verbatim** before escalating to AWAITING_HITL. Auto-retry loop fired correctly (madde 7 confirmed working) but the Worker never saw why it failed.

**Root cause.** `runtime/executor/runner.py:186-197`, the `WorkerOutOfScope` exception branch:
```python
except (WorkerOutOfScope, ValueError) as e:
    record.last_error = str(e)[:300]
    # ... cleanup, status assignment, return
```
Sets `record.last_error` but **never touches `record.last_review_reasons`**. Next attempt: `prior_reasons = record.last_review_reasons if record.attempts > 1 else None` (line 154) — the list is still empty from a prior Reviewer call (or never written), so `prior_reasons` is None. Worker gets the same RFC, the same task, no feedback at all → produces the same out-of-scope output → same exception → repeat 3× → AWAITING_HITL.

**Why this is structurally important.** The sandbox is the system's strongest deterministic gate, but on the sandbox-violation path the agentic feedback loop is severed. The Reviewer rubric (Phase 0 9a) is not even invoked here — Worker doesn't get past the sandbox check inside `worker.execute()` (raised at `runtime/executor/worker.py:155`). So the structured rubric reasons never enter the picture. The auto-retry loop (madde 7) cycles uselessly. This is the **third such silently-degraded path** in the system: madde 6 was silent test/hook skip, madde 7 was non-existent retry loop, this is sandbox feedback never reaching Worker. Pattern: deterministic gate wins, agentic correction never gets a turn.

**Why Worker keeps writing `model/todo.go` (the specific T-002 case).** Worker is asked to write `store/store.go` (Store interface). It needs the `Todo` type defined in `model/todo.go`. In Go, importing a type means `import "appname/model"` — purely a read-only reference. But the Worker, with no awareness that T-001 already produced `model/todo.go`, treats the dependency as a write — re-emits the file. This is also a Worker-level prompt insufficiency: Worker prompt does not explicitly instruct "if a type from another module is needed, IMPORT it; do not re-create the file". This is a secondary fix layered on top of 15a below.

**15a. Fix in `runner.py` (immediate, ~15 min).** In the `WorkerOutOfScope` / `ValueError` branch, populate `record.last_review_reasons` with a `[sandbox]`-tagged feedback string before returning. Worker's next attempt then receives concrete prior reasons, exactly as it would after a Reviewer rubric reject. Format:
```
[sandbox] Previous attempt failed before reaching review:
<original error>. Only emit files under module_scope='<scope>/'.
To consume types or symbols from other modules, import them via the
language's import mechanism; do NOT re-create files that already exist
in other modules.
```
**Tests:** add a `test_reviewer_chain.py` case where FakeLLM emits an out-of-scope FileChange on first call → verify `record.last_review_reasons` contains `[sandbox]`-tagged entry → second `execute_task` call passes those reasons into `Worker.execute` as `prior_reasons`.

**15b. Worker prompt cross-module-import guidance (deferred to M3 Skills phase).** Long-term answer: a per-language skill (`skills/go/imports.md`, `skills/typescript/module-imports.md`) injected into Worker prompt that explicitly handles this case — "if you reference a type defined in another module, write `import "<modulepath>"`, do NOT recreate the file". Skill-shaped fix is more durable than stuffing language-specific rules into a generic Worker prompt. Until M3 ships, 15a alone unblocks this run; the Worker still has to *infer* the import is the right path, but at least the feedback gives it a chance.

**Why 15a now and not in M3.** 15a is a 5-line fix in `runner.py` that closes a fundamental loop discontinuity. Deferring it means every greenfield run is one sandbox violation away from a useless 3-attempt cycle. It's not a nice-to-have, it's a **regression of the value proposition** (auto-retry loop without feedback = worse than no auto-retry, because it pretends to be self-correcting).

### Update to madde 2 — tier-stack mismatch surfaced in todo-greenfield-3

In `todo-greenfield-3`, deterministic `select_tier` returned T2 (BaaS, web tier, score 100) — same overconfident pick observed in `todo-greenfield-2`. But Architect Call 2 (RFC drafting) **independently** chose Go + Cobra CLI for the implementation. Bootstrap layer wrote a T2/web template (package.json, tsconfig.json, `.ai-factory.env` with vitest) which is now structurally incompatible with the Go RFC. `npx` is missing from PATH because it's a Go project — and would be missing on every developer machine without Node installed for unrelated reasons.

This is the same failure mode as before but with a sharper edge: the system has TWO tier-shaped opinions (deterministic scorer + Architect's free-form RFC choice) that don't communicate. M2 Conversational Stack Iteration is the structural answer — user negotiates a single locked stack before scaffolding fires. Until M2 ships, mitigations:
- Move tier scorer's output INTO the Architect Call 2 prompt as a **hard constraint** ("you MUST use the language/framework matching tier=T2/app_class=web — see tier docs"). Currently the scorer output and Architect prompt are decoupled.
- Or invert: derive bootstrap template from RFC content (parse §4 Tech Stack), not from `select_tier`. Risky parser surface but at least always consistent with what Architect actually said.

Both are interim. Real fix is M2.

### 16. `unverifiable` rubric status conflates two distinct failure modes — MEDIUM PRIORITY (UX / audit clarity)

**Discovery context.** `todo-greenfield-3` T-003 (2026-05-08, post-item-15a). Reviewer correctly marked the criterion `concurrent reads and writes do not produce corrupted JSON (tested with parallel goroutines)` as `unverifiable` because the test runner skipped (`npx not on PATH`). Audit event: `executor_criteria_design_failure`. UX message: `criterion design issue, not Worker fault`. Both technically correct but **categorically misleading** — the criterion is well-designed, the Worker wrote a correct test (`TestConcurrentReadsAndWritesNoCorruption` at `store_test.go:155-196`), and the only failure is that the runner couldn't execute. Categorizing this as "criterion design failure" sends the user looking in the wrong place.

**Two distinct failure modes hiding under one status:**

| Sub-mode | Cause | Correct user action | Currently labelled |
|---|---|---|---|
| `criterion_design_failure` | Criterion uses banned/ambiguous wording (`"readable"`, `"good UX"`) | Orchestrator must rewrite criterion as machine-checkable | `criteria_design_failure` ✅ |
| `test_infrastructure_unavailable` | Criterion is well-designed but tests were skipped because runner missing/disabled | Fix runner setup (install Node, set `AI_FACTORY_TEST_CMD`, fix tier-stack mismatch) | `criteria_design_failure` ❌ wrong category |

The Reviewer prompt already lets the model record which sub-mode applies in the `evidence` field (T-003 evidence said *"tests were SKIPPED (runner 'npx' not on PATH)"* — perfectly clear). The information is there; it's just not used downstream to choose audit event tag or UX message.

**Fix proposal (1-2 hours, deferred):**
- Reviewer prompt: when emitting `unverifiable`, also emit a structured `unverifiable_reason: "criterion_ambiguous" | "test_infrastructure_unavailable" | "runtime_data_missing"` field on `CriterionVerdict`.
- `runtime/executor/runner.py` branch on `unverifiable_reason` → choose audit event (`executor_criteria_design_failure` vs `executor_test_infrastructure_unavailable`) and corresponding error_msg.
- `runtime/main.py:_render_execution_result` UX text differentiates: criterion redesign vs runner-setup fix.
- Tests: 2-3 to cover the two reasons surfacing in the right audit tag.

**Why deferred and not done now:** non-blocking — the verdict outcome (AWAITING_HITL) is correct in both sub-modes; only the *reporting* is muddled. M2 Conversational Stack Iteration probably eliminates the `test_infrastructure_unavailable` case structurally (locked stack → bootstrap writes the right runner from the start). If M2 closes most occurrences, the disambiguation work value drops. Revisit after M2 ships.

**2026-05-09 update — confirmed dominant mode in practice.** `todo-greenfield-4` T-005 retry produced exactly the `test_infrastructure_unavailable` mode again (`go not on PATH` → 11 criteria all `unverifiable` → audit tag `criteria_design_failure`, UX message `criterion design issue, not Worker fault`). Acceptance criteria themselves were textbook item-9b binary form (regex/exit-code/substring matches, no banned words). User reaction: looking for a criterion redesign — the wrong mental model. Pattern observation: across 3 greenfield runs (`todo-greenfield-2/3/4`), the `unverifiable` cases have been **runner-unavailable**, not criterion-design — the criterion-design case has not yet appeared in the wild. Item 16 priority **upgraded from MEDIUM to MEDIUM-HIGH**: the misdirection is real and recurring. Still deferred until M2 closes most occurrences, but if M2 timeline slips beyond 2 weeks, ship the disambiguation independently (~1-2 hours).

### 17. Architect Call 2 ignores `select_tier()` output — MEDIUM PRIORITY (interim mitigation for item 2 until M2 lands)

**Discovery context.** `todo-greenfield-3`: deterministic `select_tier()` returned `T2 (BaaS, web tier, score 100)` and `bootstrap_workspace_layout` correctly wrote a Node/TypeScript template (`package.json`, `tsconfig.json`, `.ai-factory.env` with vitest). But `runtime/agents/architect.py` Call 2 (RFC drafting) chose Go + Cobra independently — the scorer's tier never made it into the Architect's prompt as a binding constraint. The two layers have **decoupled tier opinions** that don't communicate, producing the structural mismatch surfaced in items 2 and 16.

**Why this is the interim fix lane (not the structural one).** The structural fix is M2 Conversational Stack Iteration: user negotiates and locks a single stack before scaffolding fires. M2 is ~1 week. Until M2 ships, every greenfield run risks landing in this mismatch state — the scorer says one thing, Architect Call 2 says another, bootstrap follows scorer, Worker writes Architect's choice, test runner can't run, criteria become `unverifiable`, run halts. **The cheapest unblocker until M2:** thread the scorer's `(tier, app_class)` into Architect Call 2 as a hard prompt constraint — "you MUST use the language and framework family consistent with this tier". Architect can no longer pick Go for a `T2/web` project.

**Fix proposal (~30 min + 2 tests):**
- `runtime/agents/architect.py` (`draft_rfc` or equivalent): accept `tier_score: TierScore` (already computed in Call 1) as input; inject into Call 2 user prompt as: `"## Tier Constraint (HARD)\n\nThe deterministic Golden Path scorer chose tier=<tier>, app_class=<app>. Your RFC §4 (Tech Stack) MUST select a language and framework family consistent with this tier (e.g. T2/web → TypeScript+Node OR Python+FastAPI; T2/mobile → Flutter; T2/desktop → Tauri+Rust). If you believe the tier is wrong for this project, escalate via §1 'Architectural Trade-offs' but DO NOT silently switch stacks."`
- Tests: 2 — (a) given T2/web inputs, Architect prompt includes `T2/web` constraint string verbatim; (b) given T1/mobile inputs, prompt includes `T1/mobile`.
- Tier-language matrix (T0→T6 × {web, mobile, desktop}) should live alongside `_TEST_CMD_BY_TIER_APP` in `runtime/architecture/bootstrap.py` since the two need to stay aligned — same source of truth.

**Why item 17 doesn't make item 16 obsolete.** Even with item 17, the user might still hit `test_infrastructure_unavailable` (e.g. Node not installed on the dev machine, even though stack is correctly TypeScript). So 16's UX disambiguation is still useful — but rarer. 17 ships first; 16 deferred until observation.

### 18. Stack constraint matrix is dev-environment-blind — MEDIUM PRIORITY (M2 Conversational Stack covers this; interim mitigation possible)

**Discovery context.** `todo-greenfield-4` (2026-05-09). Same brief as 3, but this time the deterministic scorer returned `T0 (Static, score 100)` — a more reasonable tier for a single-user CLI todo than the earlier `T2 (BaaS)`. Item 17 fix loaded the `("T0", "web")` constraint from `_LANG_STACK_BY_TIER_APP`: *"Python single-file CLI, Bash, or Go single-binary"*. Architect (DeepSeek) picked **Go single-binary** — fully constraint-compliant. But the user's dev environment had no `go` runtime installed at the time of the run — so the Go pick was canonically right but operationally dead. The user installed Go after the fact to unblock; that should not have been the user's problem.

**Root structural issue.** Item 17 layered tier×app_class language constraints, but the matrix is **environment-blind**: it lists what's *canonical* for the tier without knowing what's *available* on the dev machine. Three failure modes follow from this:
- (a) **Wide matrix bias toward the "wrong" runtime** — `("T0", "web")` listed three options; LLM chose the one (Go) the user couldn't run. With three equiweighted choices, 2-in-3 odds of mismatch when only one runtime is installed.
- (b) **Interim brittleness** — until M2 ships, every greenfield run rolls the dice on whether Architect picks a stack the user happens to have. Tightening the matrix per item 18a (below) reduces blast radius but doesn't eliminate it.
- (c) **Inversion-of-control concern** — sound architectural reasoning ("scaffold a single-binary Go CLI for T0/web") is a *bad outcome* if the user has no Go. The system can't be trusted to optimize for "tier-canonical correctness" without also asking "is this runnable here?"

**Three interim mitigations (M2-Conversational-Stack-Iteration is the structural answer):**

**18a. Tighten T0/web matrix to user-default-likely choices.** Drop Go and Bash from `("T0", "web")`. Keep `"TypeScript + Node (single-file CLI via tsx) OR Python (single-file CLI)"`. Rationale: Node and Python are vastly more likely to already be installed on a dev machine than Go or Bash-only setups. Go stays available for T3/web (microservices) where multi-runtime Docker-based environments are normal. Effort: 1 line in `bootstrap.py`, 1 unit test, ~10 min. **Done in same session as item 18 doc — see 18a impl note below if shipped.** Not yet shipped at time of writing.

**18b. Bootstrap-time runtime detection.** Run `where.exe go`, `where.exe node`, `where.exe python` (or `which` POSIX-side) at scaffold time, intersect with the matrix entry, narrow to runtimes-that-exist. Threads `available_runtimes: list[str]` into Architect Call 2 prompt as advisory: "Runtimes confirmed available on the dev machine: {...}. Prefer these in §4 Tech Stack unless tier-canonical reasons override." Effort: ~30 min + 2 tests. Risk: bootstrap layer gains a side-effect (subprocess calls); makes tests brittle if they don't mock. Adopt only if 18a alone proves insufficient — observe next greenfield run first.

**18c. CLI flag at `ortim new`.** `ortim new "<brief>" --prefer-stack typescript` or `--prefer-stack python` injects a hint into Architect Call 2 prompt as a hard preference. Useful for power users. Effort: ~30 min + 2 tests. Best framed as a **prefiguration of M2 Stack Dialog** — same UX intent, less interactive.

**Which interim to ship first:** 18a is cheapest and addresses the observed failure directly. 18b is the "real" structural fix short of M2. 18c is the most user-transparent option. **Recommendation: ship 18a now (10 min) to stop the bleeding, defer 18b/18c until M2 timing is decided** — if M2 lands within 1–2 weeks, neither is worth the marginal complexity.

**Why this matters more than the surface log suggests.** The user's reaction in `todo-greenfield-4` ("RFC dosyası Go ısrarını sürdürüyor") points to a **trust failure**, not just a runtime gap. The system made a decision that seemed unjustified from the user's POV (why Go for a CLI todo when I'm a TypeScript developer?). The user can override but only by understanding the matrix internals — which violates the agentic-platform contract (system optimizes; user supervises). M2 closes this by making stack a negotiated artifact, not a system-imposed pick.

### 19. `_run_all_loop` had a pre-existing `NameError` (`codebase_summary`/`app_class` referenced but not declared) — FIXED 2026-05-09

**Discovery.** `todo-greenfield-4` `ortim run-all` invocation crashed at line 1380 (parallel branch path; same bug existed in sequential branch after M1.5 added auto-retry loop):
```
NameError: name 'codebase_summary' is not defined
```
Root cause: `_run_all_loop` referenced `codebase_summary` and `app_class` in both parallel and sequential branches when calling `execute_task(...)`, but the function neither declared them as parameters nor received them from the `run_all` typer command above. Pre-existing bug — parallel branch was untested in real use (no project ever ran `--parallel`), so the latent reference went unnoticed. M1.5's sequential auto-retry loop added a new `execute_task` call site that hit the same trap.

**Fix.** Added `codebase_summary=None, app_class: str = "web"` to `_run_all_loop` signature; added them to the `run_all → _run_all_loop` invocation site in `runtime/main.py`. No test added — pure pre-existing-bug-surfacing fix; integration coverage exists implicitly via every greenfield E2E run from this point on.

**Lesson for future M-modules.** The `_run_all_loop` parallel branch was *never* exercised end-to-end before today; the second auto-retry-loop addition (item 7b, deferred) will need a real integration test before it ships, not just unit tests, because stale closure references like this slip past lint and mypy.

### 18a. Stack-aware test-cmd fallback shipped 2026-05-09

**Trigger.** `todo-greenfield-4` `run-all` after item 19 fix. T-001..T-004 approved on first attempt (Phase 0 `[1×]` self-driving). T-005 (CLI integration) had **9 acceptance criteria all in strict binary form** ("exit code is 0 when running ...", "stderr contains 'Usage:' substring ..." — perfect item-9b shape) but every one returned `unverifiable` because `tests: skipped — no test command configured`. Bootstrap had silently skipped writing `.ai-factory.env` because `_TEST_CMD_BY_TIER_APP` had no `("T0", "web")` entry. Same class of problem as item 18 (matrix dev-env-blind), now on the test-cmd side: matrix was **stack-blind**.

**Fix.** Added `_LANG_TEST_CMD` ordered list and `_infer_test_cmd_from_rfc(workspace)` helper to `runtime/architecture/bootstrap.py`. When `_TEST_CMD_BY_TIER_APP[(tier, app_class)]` returns nothing, scan RFC.md for language tokens (`go `, `golang`, `cobra`, `typescript`, `node.js`, `npm`, `python`, `fastapi`, `rust`, `cargo`, `flutter`, `dart`) — first match wins. Tokens ordered specific-to-generic to avoid false positives (`"rust"` before `"flutter"`-with-rust-mention, etc.). Returns `None` when no match, leaving `.ai-factory.env` unwritten — Reviewer rubric (item 9a) correctly marks test-shaped criteria `unverifiable` as before; nothing got worse for unmappable stacks.

**Tests.** 4 new in `tests/test_bootstrap.py`: T0/web→Go, T0/web→TypeScript, T0/web with no RFC = no write, matrix entry beats RFC fallback. Pytest 199 → **203**.

**Why this matters and what's next.** Item 18 (matrix breadth → wrong stack chosen) and item 18a (matrix gap → no test runner) are **two faces of the same root issue**: deterministic config matrices that don't carry stack context. M2 Conversational Stack Iteration locks a stack as a project-level artifact; bootstrap reads from that artifact, not from heuristic matrices. Until M2, item 18a's RFC scan is the cheapest stop-gap; item 18b (env auto-detect) and 18c (`--prefer-stack` flag) remain deferred — not necessary if 18a holds.

**Open observation:** the `_LANG_TEST_CMD` token list is hand-curated. False-positive risk if RFC mentions a language as a counter-example ("considered TypeScript but chose Go"). Acceptable for now; M2 eliminates the heuristic entirely. If false positives surface, tighten by requiring the token to appear inside a `## §4 Tech Stack` heading-bounded section.

### 20. Phase 0 + items 15a + 17 + 18a value proven on `todo-greenfield-4` Batch 1 + Batch 2 — 4/5 tasks first-attempt approved

For the record. After items 15a (sandbox feedback), 17 (tier-stack constraint, partial), and 18a (stack-aware test cmd) shipped, `todo-greenfield-4` produced:

| Task | Module | Result | Notes |
|---|---|---|---|
| T-001 | `models` | ✅ first attempt | `models/todo.go` |
| T-003 | `cmd` | ✅ first attempt | `cmd/parser.go` (parallel-ish — sequential exec) |
| T-002 | `storage` | ✅ first attempt | `storage/storage.go` + `storage/storage_test.go` (Worker emitted test alongside code) |
| T-004 | `commands` | ✅ first attempt | `commands/commands.go` |
| T-005 | (integration) | ❌ AWAITING_HITL via item 18a gap (now fixed) | retry expected to pass after fix |

**Self-driving rate observed: 4/5 = 80%** with zero auto-retry triggers. This is the first run where the system delivered close-to-vision quality without a reviewer drift, sandbox loop, or runtime-tier mismatch derailing the pipeline. **Reproducibility:** still single-data-point — needs at least 2 more clean greenfield runs across different tier×app_class combos (M1/mobile Flutter, T2/web Supabase) before the rate is statistically meaningful. M2 conversational intake will likely raise the ceiling further by removing tier-stack mismatch risk entirely.

**Acceptance criteria observation worth preserving.** T-005's criteria are textbook examples of the item-9b form we wanted Orchestrator to produce: every one was a regex/exit-code/substring assertion against a concrete invocation. This is the new Orchestrator default behavior, not a hand-crafted prompt — Hard Rule 10's banned-words list and ❌→✅ examples are doing their job.

### 21. Reviewer dropped 2-of-13 criteria silently — deterministic length validator added 2026-05-09

**Discovery context.** `todo-greenfield-4` T-005 retry. DAG declared **13** acceptance criteria; Reviewer (DeepSeek-chat) emitted **11** verdicts on retry, **9** in the prior run-all attempt. Two criteria silently dropped each time — different ones each run, but always the static-file-existence and directory-creation ones (`file main.go exists in project root`, `directory ~/.todo/ is created on first run if it does not exist`). These are the only criteria that **don't** depend on test execution; the LLM appears to drop them when "tests skipped" dominates its attention.

**Why this matters.** Direct violation of `agents/reviewer.md` Hard Rule 1: "One verdict per acceptance criterion. No more, no fewer." Phase 0 9a's prompt sertleştirme alone wasn't enough — the LLM keeps slipping past it. The dropped criteria's verdicts are simply unknown — the schema can't distinguish "dropped" from "pass" from "fail". Without a structural guard, the runtime accepts an invalid rubric and acts on incomplete information.

**Same class of failure as `_run_all_loop` NameError (item 19) and `unverifiable` two-mode conflation (item 16):** prompt-only protections eventually slip in real runs. Deterministic gates outside the LLM are the only durable defense.

**Fix (shipped same session).** `runtime/executor/reviewer.py::CodeReviewerAgent.review()` rewrote as an Orchestrator-style retry loop (`MAX_RETRIES=3`):
- After parsing `ReviewVerdict`, compare `len(verdict.criteria_verdicts)` to `len(task.acceptance_criteria)`. Mismatch → `previous_error = "emitted N but task has EXACTLY M acceptance criteria"`, retry with that as a structured correction prepended to the user prompt.
- Same loop catches schema/JSON parse failures with `previous_error = "invalid JSON / schema: ..."`.
- Three strikes → `RuntimeError`. The runner already escalates exceptions on the worker path (item 15a) and the same path catches reviewer exceptions; no new wiring needed.
- Audit emits `reviewer_validation_failed` per failed attempt, with `expected_count` / `actual_count`.
- Prompt also strengthened: explicit `"EXACTLY {expected_count} entries required"` text in the criteria block AND in the closing instruction. Belt + suspenders.

**Tests (2 new, in `tests/test_reviewer_chain.py`).**
- `test_reviewer_length_mismatch_triggers_retry_then_succeeds`: TwoShotLLM emits 1-of-2 criteria first, full 2 on retry → validator triggers exactly one retry, final verdict has all 2, retry prompt contains the correction message.
- `test_reviewer_length_mismatch_three_strikes_raises`: AlwaysShortLLM never grows the list → `RuntimeError` after exactly `MAX_RETRIES` calls.

Pytest 203 → **205**.

**Side observation — prompt vs. validator division of labor.** Phase 0's contribution was the rubric *schema* + *prompt rules*. Item 21 adds a *runtime validator* outside the LLM. This is the right split: prompt asks for correct output, validator enforces it deterministically. M3 (Skills) and M4 (two-shot Worker) will likely surface similar drift problems — each layer needs a deterministic guard, not just a stronger prompt.

**What's still not enforced (deliberately deferred).** Length-match check is structural; **content-match** check (each verdict's `criterion` field must equal the corresponding original criterion verbatim) is not yet enforced. The LLM could in principle emit 13 verdicts that paraphrase the criteria — same count, different text. Defer until that drift actually appears in a run (it hasn't yet).

### 10. M2 — Conversational Intake & Stack Iteration (~1 week) — Vision pillars 1+2+3

**Goal.** Replace one-shot Babel + one-shot Analyst PRD draft + one-shot Architect tier selection with a turn-based dialog: user iterates on the project description, the system reflects what it understands, the user corrects, then the system proposes a tech stack as a separate revisable artifact, then the analyst proposes the PRD as a separate revisable artifact. No artifact is locked in until the user explicitly says "lock".

**Why this is the highest-UX-leverage phase.** Currently `ortim run --step babel` shows Türkçe round-trip ("Anladığım: ..."), but it's display-only — the user has no way to say "no, expand point 2" or "wrong, the users are admins not customers". Vision pillars 1+2+3 collapse without dialog.

**Scope (proposed).**
- New CLI command: `ortim discuss <project_id>` — turn-based REPL. Each turn: system shows current artifact (intent / stack / PRD), user types feedback ("expand X", "I disagree with Y", "lock"), agent regenerates with feedback as input.
- New state machine states: `INTAKE_DIALOG`, `STACK_DIALOG`, `PRD_DIALOG` between current `INTAKE` and `PRD_DRAFTING`. Each has a `lock` transition gating the next step.
- New agent role: split current `Analyst` into `IntentAnalyst` (refines Babel intent through dialog) + `StackAnalyst` (proposes/iterates on tier+tech stack with rationale) + `PRDAnalyst` (drafts PRD from locked intent + locked stack). All conversational.
- Architect tier selection becomes seeded by `StackAnalyst` output (which is already a refined Tier candidate), not a fresh deterministic score from `golden_path_inputs.json`.
- Every dialog turn writes an audit `dialog_turn` event with user input, agent response, locked state.

**Dependencies on Phase 0:** none directly — but rubric/binary criteria will be used by downstream Reviewer when M2 outputs feed into M3+.

**Open design questions (to discuss before implementation starts):**
- TUI library? Typer + prompt_toolkit, or a separate `ortim chat` command using a textual TUI library?
- Diff display: when user says "regenerate with this change", do we show colorized diff between old artifact and new?
- Per-turn token budget cap? (intake dialog could spiral cost-wise)

### 11. M3 — Skills System (Claude-skill semantics, ~1 week) — Vision pillar 6

**Goal.** Per-project, per-tier, per-task skill packages — a skill is a markdown file with frontmatter (`name`, `description`, `triggers: [tier, app_class, task_keywords]`, optional `references: [path]`, optional `tools: [scripts]`). At runtime the agent loader resolves which skills apply to the current task and injects them into the prompt as additional context.

**Why this directly answers T-009 sınıfı failures.** T-009 Worker called `program.help({error: true})` — invalid Commander.js API. Worker model knowledge of niche library APIs is unreliable. A `skills/t2-web/commander-cli-patterns.md` file with `triggers: [tier=T2, framework=commander]` would inject correct patterns (`exitOverride()`, `program.outputHelp()`, `unknownCommand` handler) into the Worker prompt for any task where Commander.js is in scope. Same template extends to Supabase patterns, Riverpod patterns (Flutter), Tauri patterns, OWASP top-10 (security skill), etc.

**Scope.**
- New directory: `skills/<scope>/<skill-name>.md` (e.g. `skills/t2-web/commander.md`, `skills/security-review/owasp-top10.md`).
- Skill resolver: `runtime/skills/loader.py` — given task spec (tier, app_class, module, description keywords), returns ordered list of applicable skills. Resolution rules: tier-specific skills > app-class-specific > universal.
- Skill injection: `runtime/agents/worker.py` and `runtime/executor/reviewer.py` accept resolved skills, append their content (truncated per token budget) to the system prompt section "## Active Skills".
- CLI: `ortim skill list <project_id>` (which skills resolve for this project), `ortim skill show <skill-name>`.
- Audit: each Worker/Reviewer call logs `active_skills: [name, ...]`.
- Initial skill content (~5 skills to seed M1 demo): `t2-web/commander.md`, `t2-web/supabase.md`, `t2-web/typescript-strict.md`, `security-review/owasp-top10.md`, `m1-mobile/flutter-riverpod.md`.

**Dependencies on Phase 0:** Reviewer rubric (skill-injected criteria need rubric form), binary criteria (skill-suggested patterns need to be checkable, not "follow best practices").

**Dependencies on M2:** dialog output (locked stack) tells us which skills to resolve. Without M2 we'd be guessing tier from heuristics.

### 12. M4 — Two-Shot Worker + Dynamic LLM Routing (~1 week) — Vision pillar 4 (pragmatic) + pillar 8 + extends madde 5

**Goal.**
- **Two-shot Worker:** Worker prompts split into Plan call (markdown bullet list of files + functions + their signatures) → user/system review of plan → Execute call (writes the actual code based on locked plan). The plan is itself sandbox-checked (no out-of-scope paths) and Reviewer-checked (criteria match) **before** any code is written. This catches T-009 sınıfı errors (DI violation, wrong API choice) at the planning stage where retry is cheap.
- **Dynamic LLM routing:** replace today's "all DeepSeek" reality (madde 5) with per-call routing matrix: Architect Call 2 (RFC draft) → Sonnet (high-stake), Babel TR↔EN → Haiku (high-volume cheap), Worker Plan → Sonnet (high-stake), Worker Execute → DeepSeek (high-volume), Reviewer rubric verdict → Sonnet (must be deterministic, must be smart enough to follow rubric strictly). Routing config lives in `~/.ai-factory/routing.yml` or `pyproject.toml` `[tool.ai-factory.routing]` and is overridable per-project.

**Why these two together.** Two-shot Worker is the place where dynamic routing pays off most: plan call is high-stake (errors here multiply downstream), execute call is high-volume (most token budget lives here). Without dynamic routing both shots run on DeepSeek and we lose the kalite/cost asymmetry. Without two-shot Worker, dynamic routing is just a config refactor with no observable quality lift.

**Scope.**
- `runtime/agents/worker.py`: split `execute()` into `plan()` + `execute_from_plan()`. Plan output schema: list of `{path, summary, signatures: [str], depends_on_files: [str]}`.
- `runtime/llm/router.py` (extends madde 5): config-driven routing table; `client_for(role, stage)` where stage ∈ {plan, execute, draft, refine, verdict, ...}.
- `agents/worker.md` updated with two-shot prompt structure.
- New audit events: `worker_plan_ok`, `worker_plan_rejected`, `worker_execute_ok`, plus per-event `routing_decision: {role, stage, provider, model, reason}`.
- CLI: `ortim run --plan-only <task>` to inspect plan without executing (M1 demo affordance).

**Dependencies on Phase 0:** rubric for Reviewer reviewing the plan (not just the code).

**Dependencies on M3:** Skills inject into both plan and execute prompts; without skills, plan call still hallucinates wrong APIs.

### 13. M5 — Knowledge Layer: RAG (Obsidian) + MCP (~2–3 weeks) — Vision pillars 5+7

**13a. RAG (Obsidian-style knowledge base).**
- Local-first vector DB (Qdrant or Chroma; Qdrant has better durability story for the workspace persistence pattern we already have).
- Embedding provider: OpenAI text-embedding-3-small or local (instructor-large) — config-driven. Cost note: embedding is one-time per artifact, so paid-API embedding is acceptable.
- Indexed corpus per project: locked PRD, RFC, all completed task outputs, audit log decisions, skill files (so skills are also retrievable, not just rule-injected). Per-project namespace; no cross-project contamination.
- Retrieval call from Worker/Reviewer: top-k passages prepended to system prompt under "## Project Memory".
- "Anti-amnesia" goal from original plan: when Worker is on T-007, it sees the locked T-006 contract from RAG, not just the raw `auth/index.ts` source — including the rationale recorded in the audit log.

**13b. MCP integration.**
- Reference servers initially: `filesystem` (read-only project files for read_related), `git` (commit history, blame for brownfield), and a project-specific server template (Supabase MCP, GitHub MCP) loaded via `ortim mcp add <server>`.
- Worker tool calling: `runtime/agents/worker.py` advertises MCP tools to the LLM; Worker can choose to invoke (e.g. "verify the schema before generating migrate.ts").
- Sandbox: MCP write-actions are gated through the same `module_scope` check; read-actions are unrestricted.
- Audit: every `mcp_tool_call` event with arguments and result hash.

**Why M5 is last.** Heavy: 2–3 weeks combined. Without it the system still demos well (M2+M3+M4 already shows dialog + skills + two-shot quality). With it, the system becomes "AI Software Factory" in the full sense the original plan envisioned. Enterprise positioning hinges on M5.

**Dependencies on M2+M3+M4:** all three feed RAG (dialog turns → context, skills → retrievable, two-shot plans → indexed). MCP tools are useful only when Worker is good enough to use them correctly (M3 skills, M4 two-shot).

### Cross-cutting items 1–8 status against this roadmap

- **Item 1 (LLM transient retry)**: subsumed under M4 routing layer (retry config per provider).
- **Item 2 (tier scoring)**: partially addressed by M2 StackAnalyst — user can override the deterministic tier via dialog.
- **Item 3 (advance UX)**: deferred — non-blocking, fix when polishing M1 demo.
- **Item 4 (root scaffolding/shared resources)**: M1.5 MVP shipped; remaining 4b (template matrix), 4c (DAG validator regex) deferred.
- **Item 5 (provider routing)**: superseded by M4.
- **Item 6 (test/hook gate veto)**: addressed by Phase 0 (9c) test-runner auto-detect.
- **Item 7 (auto-retry loop)**: M1.5 MVP shipped; remaining 7b (parallel branch + unit tests) tied into Phase 0 work since rubric tests cover the same ground.
- **Item 8 (Windows console)**: M1.5 MVP shipped, closed.

### Roadmap summary table

| Phase | Module | Effort | Pillars covered | Hard prerequisites |
|-------|--------|--------|-----------------|--------------------|
| 0 | Foundation Hardening (rubric + binary criteria + test cmd) | ~½ day | — | none |
| 1 | M2 Conversational Intake & Stack Iteration | ~1 week | 1, 2, 3 | Phase 0 |
| 2 | M3 Skills System | ~1 week | 6 | Phase 0, M2 (locked stack feeds skill resolution) |
| 3 | M4 Two-Shot Worker + Dynamic Routing | ~1 week | 4 (pragmatic), 8 | Phase 0, M3 |
| 4 | M5 RAG (Obsidian) + MCP | ~2–3 weeks | 5, 7 | M2, M3, M4 |

**Total runway from today to full vision: ~6–7 weeks of focused work**, with M1 demo viable at end of Phase 3 (M2+M3+M4 shipped).

**Immediate next action:** start Phase 0 implementation (rubric + binary criteria + test-cmd auto-detect). Targeted output of this turn: ~6–8 new tests, pytest count 183 → 191+, no regression.
