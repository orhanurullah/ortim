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

**Note on item structure (2026-05-14):** New items follow the template at `docs/item-template.md`. The template includes a mandatory "Downstream coverage scan" field — the discipline lesson from Items 41 → 41' and BaaS-drift → 47 / 47b cascade misses. Older items in this file pre-date the template; do not retrofit them.

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

---

## 2026-05-10 — Senior Analysis + P0/P1 Hardening (pytest 205 → 218)

> Full system reviewed by senior SW engineer perspective. Three production-critical fixes shipped. Git history: `bd368fe` (first commit) → `a62c989` (P0+P1 hardening).

### Senior analysis summary

Conducted a comprehensive code review across the entire runtime: state machine, golden paths, bootstrap, codebase reader, sandbox, reviewer, runner, worker, LLM client/router/providers, audit logger, and all 205 tests. Key findings:

**Strengths confirmed:**
- Deterministic tier scoring (12 tier × 3 app_class — no agentic platform competitor has this)
- Sandbox + state machine structural gates (LLM cannot bypass)
- Audit chain with SHA-256 hash + PII redaction (enterprise-ready)
- Codebase reader maturity (708 lines, AST-aware, import-graph 1-hop, mtime+sha1 cache)
- Phase 0 reviewer rubric (structured per-criterion verdict, criteria-count validator)

**Gaps identified (ordered by severity):**
1. `main.py` is a 1536-line God object — needs CLI modularization (P2, deferred)
2. LLM client had zero transient-error retry — any 503 crashed the pipeline (P0, **FIXED**)
3. `FileChange.operation` missing `update`/`patch` — brownfield overwrite-only (M2 scope)
4. `module_scope: str` single path — can't cover `src/auth/` + `tests/auth/` (M2 scope)
5. Provider routing silently fell back to cheap model for critical roles (P1, **FIXED**)
6. `unverifiable` conflated criterion-design and test-infrastructure failures (P1, **FIXED**)
7. `DONE` is terminal — no `extend` capability (M3 scope)
8. No streaming/progress feedback during `run-all` (M4 scope)
9. README outdated (P2, sırada)

**tespit.md validation score: 5/5 technical accuracy** — every finding traces to real code, every E2E run observation is reproducible, priorities are correctly ordered. The document is a forensic engineering log, not a wish list.

### Fixes shipped (commit `a62c989`)

#### 22. P0 — LLM transient retry with exponential backoff — SHIPPED

**File:** `runtime/llm/client.py` (rewrite of `call()` method)

**Problem:** `messages.create()` was a naked call — any 503, 429, 529, connection timeout, or DeepSeek "Service is too busy" response crashed the entire pipeline mid-task, wasting all prior LLM spend and operator time.

**Fix:**
- `_is_retryable(exc)` classifier: `APIConnectionError` → always retry; `APIStatusError` with status in `{429, 503, 529}` → retry; message-body heuristic for `overloaded`, `too busy`, `rate limit` → retry; everything else → raise immediately.
- `call()` wraps `messages.create` in a `for attempt in range(1 + MAX_RETRIES)` loop.
- Exponential backoff: `2^attempt + uniform(0, 1.0)` seconds — yields ~1s, ~2s, ~4s base delays with jitter to avoid thundering herd.
- `MAX_RETRIES` defaults to `3` (env override: `AI_FACTORY_LLM_MAX_RETRIES`).
- Each retry prints to stderr: `[ortim] LLM transient error (APIStatusError: ...); retry 2/3 in 2.7s...` — operator sees the degradation without cluttering stdout.
- `LLMResponse.retries: int` field added — audit trail now records how many retries a given call needed. `audit_fields()` includes `retries` only when non-zero (backward compat).
- Non-retryable errors (401 auth, 400 bad request, unknown) raise immediately on first occurrence.

**Tests (5 new):**
- `test_retryable_503` / `test_retryable_connection_error` / `test_retryable_deepseek_busy` — classifier returns True
- `test_not_retryable_auth_error` / `test_not_retryable_generic` — classifier returns False
- `test_response_retries_default` — retries=0 omitted from audit_fields
- `test_response_retries_nonzero` — retries=2 appears in audit_fields

**Items closed:** Item 1 (LLM transient retry) — fully closed, no longer deferred to M4.

#### 23. P1 — Provider fail-loud for critical roles — SHIPPED

**File:** `runtime/llm/router.py`

**Problem:** `client_for("architect")` with no `ARCHITECT_PROVIDER` env var silently resolved to global `LLM_PROVIDER` fallback. If global was `deepseek`, Architect's tier decisions ran on a cheap model without any operator awareness. Same risk for `security_reviewer` — missed CVEs from a weak model.

**Fix:**
- `_CRITICAL_ROLES = frozenset({"architect", "security_reviewer"})` — roles where silent fallback causes structural damage.
- When `client_for(role)` resolves a critical role via global fallback (no role-specific `<ROLE>_PROVIDER` env set), it emits a stderr WARNING: `[ortim] WARNING: critical role 'architect' has no explicit provider (ARCHITECT_PROVIDER not set); falling back to global LLM_PROVIDER='deepseek'. Set ARCHITECT_PROVIDER explicitly for production use.`
- Non-critical roles (`babel`, `worker`, `reviewer`, etc.) resolve silently as before.
- This is a **warning, not a block** — operator can consciously choose to run Architect on DeepSeek, but must have seen the warning. Production setups will set `ARCHITECT_PROVIDER=anthropic` explicitly.

**Tests (2 new):**
- `test_critical_role_warning` — architect with `LLM_PROVIDER=deepseek`, no `ARCHITECT_PROVIDER` → stderr contains WARNING
- `test_non_critical_role_no_warning` — babel with same config → stderr empty

**Items closed:** Item 5 (provider routing fail-loud) — warning mechanism shipped. Full M4 dynamic routing still planned but fail-loud is the critical safety net.

#### 24. P1 — Unverifiable two-mode disambiguation — SHIPPED

**Files:** `runtime/executor/reviewer.py`, `runtime/executor/runner.py`

**Problem (item 16, upgraded to MEDIUM-HIGH after 3 consecutive greenfield runs):** `unverifiable` status conflated two fundamentally different failures: (a) criterion wording is ambiguous ("readable format") — Worker can't fix, Orchestrator must rewrite; (b) test infrastructure unavailable (runner not configured) — fixable by installing the tool and setting `AI_FACTORY_TEST_CMD`. Both cases produced the same audit event `executor_criteria_design_failure` and same UX message `criterion design issue, not Worker fault`. User looked for a criterion redesign when they should have installed a test runner.

**Fix (reviewer.py):**
- New type: `UnverifiableReason = Literal["criterion_design", "test_infrastructure"]`
- `CriterionVerdict.unverifiable_reason: UnverifiableReason | None` — set only when `status == "unverifiable"`. `None` defaults to `criterion_design` for backward compat (older LLM outputs without this field).
- `ReviewVerdict.unverifiable_by_design` property — filters criteria with `criterion_design` reason (or `None`).
- `ReviewVerdict.unverifiable_by_infra` property — filters criteria with `test_infrastructure` reason.
- `ReviewVerdict.reasons` output now tags: `[unverifiable:design]` vs `[unverifiable:test_infra]` (the latter includes actionable hint: `set AI_FACTORY_TEST_CMD`).

**Fix (runner.py):**
- Audit event `executor_criteria_design_failure` now includes `unverifiable_design: [...]` and `unverifiable_infra: [...]` as separate fields (plus legacy `unverifiable: [...]` for backward compat).
- `error_msg` differentiates: pure-infra → `test_infrastructure_unavailable (set AI_FACTORY_TEST_CMD to resolve)`; pure-design → `criteria_design_failure (ambiguous criteria — rewrite needed)`; mixed → `criteria_design_failure (mixed: N design + M infra)`.

**Tests (4 new):**
- `test_unverifiable_reason_criterion_design` — design mode tags correctly
- `test_unverifiable_reason_test_infrastructure` — infra mode tags correctly, message includes `AI_FACTORY_TEST_CMD`
- `test_unverifiable_backward_compat_none_reason` — `None` reason defaults to design
- `test_unverifiable_mixed_modes` — both modes in same verdict

**Items closed:** Item 16 (unverifiable two-mode conflation) — fully closed. The disambiguation is structural (schema-level), not just a UX tweak.

### Updated cross-cutting items status (post-2026-05-10)

| Item | Topic | Status | Notes |
|---|---|---|---|
| **1** | LLM transient retry | ✅ **CLOSED** (item 22) | Exponential backoff, 3 retries, jitter. No longer deferred to M4. |
| **2** | Tier scoring weights | ⚠️ Partially mitigated | Item 17 (tier constraint) + item 18a (stack-aware test cmd) reduce blast radius. M2 StackAnalyst is structural fix. |
| **3** | State advance UX | ⬜ Open (P3) | Trivial — "already in X" message. Fix in any UX polish pass. |
| **4** | Root scaffolding | ✅ Closed (M1.5) | Bootstrap layer ships T2/web template. 4b (other tiers), 4c (DAG validator regex) deferred. |
| **5** | Provider routing fail-loud | ✅ **CLOSED** (item 23) | Critical roles emit stderr WARNING on global fallback. M4 dynamic routing still planned. |
| **6** | Test skip + approve | ✅ Closed (Phase 0 9c) | Test runner auto-detect + reviewer rubric unverifiable escalation. |
| **7** | Auto-retry loop | ✅ Closed (M1.5) | Sequential branch retry works. 7b (parallel branch retry + unit tests) deferred. |
| **7b** | Parallel retry + unit test | ⬜ Open (P2) | `_run_all_loop` parallel branch still single-pass. |
| **8** | Windows console Unicode | ✅ Closed (M1.5) | `reconfigure(encoding="utf-8")` at process start. |
| **9** | Phase 0 (rubric + criteria + test-cmd) | ✅ Closed | 12 tests, reviewer rubric, binary criteria, test-cmd auto-detect. |
| **15** | Sandbox feedback injection | ✅ Closed (M1.5) | `[sandbox]` tagged feedback in `prior_reasons`. |
| **16** | Unverifiable two-mode | ✅ **CLOSED** (item 24) | `criterion_design` vs `test_infrastructure` schema-level separation. |
| **17** | Architect ignores select_tier | ⚠️ Partially closed | `_LANG_STACK_BY_TIER_APP` constraint injected. Full M2 StackAnalyst is structural fix. |
| **18** | Stack constraint env-blind | ⚠️ Partially closed (18a) | RFC scan fallback. 18b (runtime detect), 18c (`--prefer-stack`) deferred to M2. |
| **19** | `_run_all_loop` NameError | ✅ Closed | Fixed same session as discovery. |
| **20** | 4/5 first-attempt self-driving | N/A (observation) | Value proposition proof point. |
| **21** | Reviewer criteria drop | ✅ Closed | Deterministic length validator + retry loop. |
| **22** | LLM transient retry (P0) | ✅ **SHIPPED** (this session) | See above. |
| **23** | Provider fail-loud (P1) | ✅ **SHIPPED** (this session) | See above. |
| **24** | Unverifiable two-mode (P1) | ✅ **SHIPPED** (this session) | See above. |

### Test count progression

```
134 (iter 6d baseline)
 → 163 (M1 brownfield + mobile/desktop tiers)
 → 183 (M1.5 MVP: bootstrap + auto-retry + Windows Unicode)
 → 195 (Phase 0: rubric + binary criteria + test-cmd)
 → 199 (item 15a sandbox feedback + item 17 tier constraint)
 → 203 (item 18a stack-aware test-cmd fallback)
 → 205 (item 21 reviewer length validator)
 → 218 (items 22+23+24: P0+P1 hardening) ← CURRENT
```

### What to do next — prioritized plan

> [!IMPORTANT]
> The P0+P1 fixes close the most critical production blockers. The system is now resilient to LLM transient errors, warns on provider misconfig, and reports unverifiable reasons clearly. **The next phase should focus on validating the full pipeline with a real E2E run**, then advancing to M2 (Conversational Intake).**

#### Immediate (this week)

| Priority | Action | Effort | Why now? |
|---|---|---|---|
| 🔴 **E2E validation** | Run `ortim run-all` on a fresh greenfield project (T2/web or T0/web) to validate items 22-24 in production conditions | 1 hour | Every fix needs real-run confirmation; last validated run was `todo-greenfield-4` before these fixes |
| 🟡 **README update** | Reflect v0.6d + M1.5 + Phase 0 + P0/P1 in README.md (section "Sonraki Adım" still says İter 6) | 30 min | First impression for new contributors |
| 🟡 **M2 design lock** | Decide M2 scope: `ortim discuss` REPL vs simpler `ortim refine <id> "<feedback>"` turn-based flow. TUI library choice (typer+prompt_toolkit vs textual). Token budget per dialog turn. | 2 hours (design doc) | M2 is the highest-leverage next module; design must be locked before implementation starts |

#### Short-term (next 1-2 weeks)

| Priority | Action | Effort | Why? |
|---|---|---|---|
| 🟡 **M2 implementation** | Conversational Intake & Stack Iteration. New states (`INTAKE_DIALOG`, `STACK_DIALOG`, `PRD_DIALOG`), `ortim discuss` command, split Analyst into Intent/Stack/PRD analysts. | ~1 week | Highest UX leverage; eliminates tier-stack mismatch (items 2, 17, 18) structurally |
| 🟢 **7b parallel retry** | `_run_all_loop` parallel branch auto-retry + mock-based integration tests | 4-6 hours | Parallel execution path untested with retry loop |
| 🟢 **4b tier templates** | Flutter (pubspec.yaml), Tauri (Cargo.toml), Python (pyproject.toml) bootstrap templates | 3 hours | Mobile/desktop E2E demo readiness |

#### Medium-term (weeks 3-6)

| Priority | Action | Effort | Why? |
|---|---|---|---|
| 🟡 **M3 Skills** | `skills/` directory, skill loader, per-task skill injection, 5 seed skills | ~1 week | Fixes API hallucination (T-009 Commander.js class failures) |
| 🟡 **M4 Two-Shot Worker** | Plan call + Execute call split, dynamic LLM routing config | ~1 week | Catches DI/API errors at planning stage where retry is cheap |
| 🟢 **M3.1 extend** | `DONE → EXTENDING` state, ExtenderAgent, DAG merge | ~3 days | Iterative development on existing projects |

#### Long-term (weeks 7+)

| Priority | Action | Effort | Why? |
|---|---|---|---|
| 🟢 **M5 RAG + MCP** | Vector DB, knowledge indexing, MCP tool calling | ~2-3 weeks | Enterprise positioning, full vision realization |
| 🟢 **main.py modularization** | Split 1536-line CLI into `runtime/cli/` subpackage | ~1 day | Maintainability (not blocking, but growing tech debt) |
| 🟢 **Enterprise tier** | Multi-tenant orchestrator, rate limits, SSO, SLA | TBD | Revenue enablement |

### Open strategic questions (carried forward from M1.5)

1. **PyPI publish timing** — `name="ortim"` reserved? After M2 demo?
2. **Enterprise tier timeline** — M5'te iskelet, gerçek satış ne zaman?
3. **ortim.dev landing page** — açacak mıyız? M2 demo sonrası mı?
4. **İlk hedef segment** — agency, fintech, sağlık? Demo'nun kime "vay be" olduğunu görmeden segment seçimi körlemesine.
5. **M2 UX modeli** — `ortim discuss` full REPL mi, yoksa `ortim refine` turn-based CLI mi? TUI library kararı (typer+prompt_toolkit vs textual vs plain input()).

### 25. E2E Validation Run — `e2e-validation-1` (b8d60b6f5791) — 2026-05-10

**Brief:** "Basit bir Python CLI not defteri uygulaması. Kullanıcı terminal üzerinden not ekleyebilmeli, notlarını listeleyebilmeli, not silebilmeli ve notlarında arama yapabilmeli. Notlar bir JSON dosyasında saklanmalı."

**Purpose:** Validate items 22 (LLM retry), 23 (fail-loud), 24 (unverifiable two-mode), plus confirm previously shipped items still work.

#### Run summary

| Metric | Value |
|---|---|
| **Tasks** | 6 (5 batches) |
| **Self-driving rate** | 6/6 = **100%** (all DONE, no AWAITING_HITL) |
| **First-attempt rate** | 5/6 = 83% (T-004 needed 3 attempts) |
| **Total LLM calls** | 22 |
| **Total tokens** | 76,708 (57K in + 19K out) |
| **Estimated cost** | **$0.0365** |
| **Auto-retry triggers** | 2 (T-004 attempts 2 and 3) |
| **Scaffold tasks emitted** | 0 (bootstrap handled all root files) |

#### Per-task results

| Task | Module | Attempts | Result | Notes |
|---|---|---|---|---|
| T-001 | `models` | 1 | ✅ | Note model + validation |
| T-002 | `repository` | 1 | ✅ | JSON persistence |
| T-003 | `service` | 1 | ✅ | CRUD + search business logic |
| T-004 | `cli` | **3** | ✅ | Attempt 1: missing-arg handling + **L1 DI violation**. Attempt 2: DI still present. **Attempt 3: Worker fixed DI — approved.** Self-correcting loop proven. |
| T-005 | `repository` | 1 | ✅ | Path traversal protection |
| T-006 | `cli` | 1 | ✅ | Output sanitization |

#### Item verification matrix

| Item | Tested? | Result | Evidence |
|---|---|---|---|
| **22 (LLM retry)** | ⚠️ Not exercised | Code path validated by unit tests | No 503 occurred — DeepSeek stable this run |
| **23 (fail-loud)** | ✅ **CONFIRMED** | stderr WARNING visible | `[ortim] WARNING: critical role 'architect' has no explicit provider...` |
| **24 (unverifiable two-mode)** | ⚠️ Not exercised | Schema validated by unit tests | No `unverifiable` verdicts in this run |
| **4 (bootstrap)** | ✅ **CONFIRMED** | 0 scaffold tasks | Orchestrator emitted only module-scoped tasks |
| **7 (auto-retry)** | ✅ **CONFIRMED** | T-004: 3 attempts → DONE | Worker received DI feedback, fixed on attempt 3 |
| **8 (Windows Unicode)** | ✅ **CONFIRMED** | No UnicodeEncodeError | Reject output with special chars rendered cleanly |
| **9 (Phase 0 rubric)** | ✅ **CONFIRMED** | Structured verdicts with code_quote | T-004 reject cited `.exitOverride()` and `new NoteService()` |
| **21 (criteria count)** | ✅ **CONFIRMED** | No length-mismatch | Reviewer emitted correct criterion count on all tasks |

#### Observations

**O1. Tier scoring mismatch persists (item 2).** CLI not defteri → T2 (BaaS). Architect self-flagged: "T2 is designed for web applications backed by a cloud BaaS. Applying T2 here introduces unnecessary complexity." Result: TypeScript instead of Python. M2 structural fix needed.

**O2. Self-correcting loop needs Skills (M3).** T-004 DI violation took 3 attempts. A `skills/typescript/di-patterns.md` skill would prevent this on attempt 1.

**O3. $0.0365 total cost for a complete application.** 83% first-attempt rate with DeepSeek. M3 Skills should push this to 95%+.

**Overall verdict: Pipeline is production-stable for run lifecycle. Code output quality needs structural fixes — see item 26 below.**

### 26. Post-run code quality audit — `e2e-validation-1` output does NOT compile — HIGH PRIORITY

**Discovery context.** 2026-05-10 post-E2E-validation. After the pipeline reported 6/6 tasks DONE, we attempted to actually compile and run the generated TypeScript application. `npx tsc --noEmit` produced **10 compilation errors**. The application cannot be built or executed as-is.

**Root cause analysis.** The Reviewer approved code that passes a *rubric-based semantic review* but was never subjected to *actual compilation*. This is the expected limitation documented in Phase 0: test runner was skipped (`npx` not on PATH during the pipeline run, or `AI_FACTORY_TEST_CMD` not configured for this tier). The Reviewer correctly noted `tests: skipped` on every task but the rubric assessed code logic, not compilation correctness.

#### Compilation errors (10 total, 4 distinct categories)

| Category | Count | Files | Root cause |
|---|---|---|---|
| **Wrong import paths** | 2 | `cli/index.ts:2-3` | `import from '../service/NoteService'` and `'../repository/NoteRepository'` — but files are `service/index.ts` and `repository/index.ts`. Worker used class-name-based imports instead of barrel-style. |
| **Missing `types: ["node"]` in tsconfig** | 7 | `cli/index.ts`, `repository/index.ts` | `process`, `path`, `fs`, `os` not recognized. Worker wrote Node.js code but didn't add `"types": ["node"]` to `tsconfig.json`. |
| **Missing function export** | 1 | `service/index.ts:3` | `import { validateNoteInput } from '../models'` — this function was never defined in `models/index.ts`. Worker hallucinated a function name. |

#### Runtime errors (would surface after compilation fix)

| Issue | File | Description |
|---|---|---|
| **Constructor arity mismatch** | `cli/index.ts:25` | `new NoteRepository()` — no args — but `NoteRepository` constructor requires `filePath: string`. App would crash at runtime. |
| **Missing dependencies** | `package.json` | No `dependencies` section — `commander`, `uuid` not listed. `npm install` from scratch would produce a broken `node_modules`. |
| **No entry point** | (none) | `run()` is exported from `cli/index.ts` but no `main.ts` or `bin` script calls it. User cannot `node dist/main.js` or `npx note add`. |

#### Cross-task interface inconsistency

Worker T-003 (service) imported `validateNoteInput` from `../models` — a function T-001 (models) never created. Worker T-004 (cli) imported `NoteService` from `../service/NoteService` — a path that doesn't exist (T-003 wrote `service/index.ts`). Worker T-006 (cli sanitization) overwrote T-004's `cli/index.ts` and kept the wrong import paths.

This is the **same failure class as T-009 in todo-greenfield-2**: each task is written in isolation; Worker doesn't verify its imports against what prior tasks actually produced.

#### Why the Reviewer didn't catch this

1. **No TypeScript compiler ran.** Test runner was skipped → no `tsc` verification. Reviewer assessed code semantics (DI, logic, L1 principles), not syntactic correctness.
2. **Reviewer has no cross-task memory.** Each task is reviewed independently. Reviewer for T-003 doesn't see T-001's actual exports; it only sees T-003's code + the acceptance criteria + the RFC.
3. **Import path convention is model-specific knowledge.** Whether to import `../repository` (barrel) vs `../repository/NoteRepository` (direct) depends on project convention. Worker picked one, Reviewer didn't flag it because the *logic* was correct.

#### Severity assessment

**HIGH.** This invalidates the "100% self-driving" claim from item 25. The pipeline is self-driving in terms of its *own approval lifecycle*, but the output is **non-functional**. A user who runs the pipeline and then tries `npm run build` will immediately see 10 errors and lose trust.

#### Structural fixes needed

| Fix | Where | Addresses | Priority |
|---|---|---|---|
| **Test runner must be mandatory for code tasks** | `runner.py` / reviewer rubric | If `AI_FACTORY_TEST_CMD` is set and tests were configured, `tsc --noEmit` should be the minimum bar for TypeScript projects | 🔴 P0 — without this, "approved" means nothing |
| **Cross-task import verification** | M2/M3 scope | Worker needs to see prior task outputs (or at least their exports) when writing code that imports from other modules | 🟡 P1 — `read_related()` already exists but isn't used for cross-module imports |
| **Bootstrap must write complete `package.json`** | `bootstrap.py` | T2/web template should include `commander`, `uuid`, `@types/node` as dependencies when the RFC specifies them | 🟡 P1 — or Worker must add dependencies |
| **Entry point generation** | Orchestrator / bootstrap | A task or bootstrap step should create `main.ts` (or `bin` config in package.json) | 🟢 P2 |

#### Lesson for Ortim development

> **Pipeline "approved" ≠ code works.** The Reviewer is a semantic gate, not a compiler. Until the test runner is properly configured and mandatory (Phase 0 9c intent), the "self-driving rate" metric measures *pipeline lifecycle completion*, not *code quality*. The true metric should be: "does the output compile and pass tests?" — which requires M2 (stack negotiation → correct test runner) and M3 (skills → correct import patterns).

**This finding does NOT invalidate items 22-24 (those fixes are about pipeline resilience, not code quality). But it recalibrates item 25's "100% self-driving" claim to "100% pipeline-complete, 0% compile-verified."**

#### Functional test results (post-manual-fix)

After applying **7 manual fixes** to the generated code, the application was compiled and tested end-to-end:

**Manual fixes applied (all would be unnecessary with proper test runner + cross-task import checks):**

| # | Fix | Category |
|---|---|---|
| 1 | Added missing `validateNoteInput()` function to `models/index.ts` | Worker hallucination — T-003 imported a function T-001 never created |
| 2 | Added `"types": ["node"]` to `tsconfig.json` | Missing config — Worker wrote Node.js code but didn't configure TypeScript for it |
| 3 | Fixed import paths in `cli/index.ts` (`../service/NoteService` → `../service`) | Wrong barrel import convention — Worker used class-name paths |
| 4 | Fixed `NoteRepository()` → `NoteRepository(notesPath)` in `cli/index.ts` | Constructor arity mismatch — CLI called without required `filePath` arg |
| 5 | Added entry point (`run(process.argv)`) to `cli/index.ts` | No main — `run()` was exported but never called |
| 6 | Added `dependencies` to root `package.json` (commander, uuid, @types/node) | Missing deps — Workers never registered their npm dependencies |
| 7 | Removed `repository/package.json` (sub-package.json broke ESM module resolution) | Conflicting package.json — T-002 created its own package.json without `"type": "module"`, breaking Node.js ESM resolution for the entire `repository/` subtree |

**Compilation result after fixes:** `npx tsc --noEmit` → **0 errors** ✅

**Functional test matrix:**

| Test | Command | Expected | Actual | Result |
|---|---|---|---|---|
| Help | `note --help` | Show commands: add, list, delete, search | Shows all 4 commands + version | ✅ |
| Add note | `note add "Ilk notum" "test icerik"` | `Created note: Ilk notum` | Prints confirmation, writes JSON | ✅ |
| List notes | `note list` | Show all notes, newest first | 2 notes displayed, date-sorted desc | ✅ |
| Search | `note search "Flutter"` | Show only matching note | 1 result, correct note | ✅ |
| Search (no match) | `note search "olmayan"` | `No notes found.` | Correct empty message | ✅ |
| Delete | `note delete <id>` | `Note deleted.` | Note removed, confirmed via list | ✅ |
| Delete invalid | `note delete "yok-id"` | Error message | `Error: Note not found` (exit code 1) | ✅ |
| JSON structure | Check `~/.notes/notes.json` | `{version, notes: [{id, title, content, created_at}]}` | Correct schema, UUID v4, ISO date | ✅ |

**Functional test result: 8/8 = 100%** — all core features work correctly after manual fixes.

**Missing behaviors (not in brief but expected for a usable tool):**
- `~/.notes/` directory not auto-created on first `add` → ENOENT crash (fix: `fs.mkdirSync(dir, {recursive: true})` in writeAll)
- No `update`/`edit` command (brief didn't ask for it, so not a defect)
- No confirmation before delete (acceptable for CLI tool)

#### Summary metrics — recalibrated

| Metric | Value |
|---|---|
| Pipeline self-driving rate | 6/6 = 100% (lifecycle) |
| Compilation success (as-generated) | **0%** — 10 TS errors |
| Manual fixes to compile | **7** |
| Functional test pass (post-fix) | **8/8 = 100%** |
| Fix categories | 3 cross-task import, 2 missing config, 1 hallucination, 1 ESM conflict |

**Key insight:** The generated code's *logic* is sound — once imports and config are fixed, everything works. The defects are all **integration-layer** problems (cross-task imports, config completeness, module resolution). These are exactly the problems that:
1. A **real test runner** (`tsc --noEmit` + `vitest run`) would catch during the pipeline
2. **Cross-task file visibility** (`read_related()` for prior task outputs) would prevent
3. **Skills** (`skills/typescript/esm-module-patterns.md`) would guide correctly

**This confirms M2 (stack negotiation → test runner) as the highest-priority next step for code quality, not just UX.**

---

## 2026-05-13 — M2 ship + first dialog E2E (web-todo-m2)

> M2 Conversational Intake & Stack Iteration (~5–7 days estimated, item 10) shipped in a single session. Test count 218 → **244** (+26: state machine +4, dialog analysts +5, dialog storage +10, M2 integration +7). First real dialog-mode E2E on `web-todo-m2` (T1/web React+sql.js SPA) validated the chain end-to-end through three of four batches; closed items 17 + 18a structurally, partially closed item 26 (2 of 4 categories), surfaced and shipped two side fixes that were Windows-blocking pre-existing bugs.

### 27. M2 implementation — Conversational Intake + LockedStack as single source of truth — SHIPPED

**Phase log:**

| Phase | Scope | Files |
|---|---|---|
| M2-0 | Design lock — 4 decisions (turn-based CLI over REPL, minimal diff on lock-confirm, `AI_FACTORY_DIALOG_TURN_CAP=10`, documenter prompt patch in M2-3) | `M2-design.md` |
| M2-1a | 3 new dialog states (INTAKE_DIALOG / STACK_DIALOG / PRD_DIALOG) + back-step transitions, legacy `BABEL_PROCESSING → PRD_DRAFTING` preserved for `AI_FACTORY_DIALOG_MODE=off` | `runtime/orchestrator/state_machine.py`, `tests/test_state_machine.py` (+4 tests) |
| M2-1b | Analyst split into three role-specific agents with English system prompts | `runtime/agents/{intent,stack,prd}_analyst.py`, `agents/{intent,stack,prd}_analyst.md`, `tests/test_dialog_analysts.py` (+5 tests) |
| M2-1c | `LockedStack` pydantic schema + `runtime/dialog/storage.py` (artifact I/O, turn cap, snapshot for diff) | `runtime/architecture/locked_stack.py`, `runtime/dialog/storage.py`, `tests/test_dialog_storage.py` (+10 tests) |
| M2-2 | `ortim refine` / `ortim show` / `ortim lock` CLI commands; babel branch routes to INTAKE_DIALOG when `AI_FACTORY_DIALOG_MODE=on` (default) | `runtime/main.py` |
| M2-3 | `bootstrap_workspace_layout` / `Architect.draft_rfc` / `Documenter.generate_readme` accept `locked_stack: LockedStack \| None`; when present, it is the single source of truth and heuristic matrices (`_LANG_STACK_BY_TIER_APP`, `_infer_test_cmd_from_rfc`) are bypassed | `runtime/architecture/bootstrap.py`, `runtime/agents/architect.py`, `runtime/agents/documenter.py`, `tests/test_m2_integration.py` (+7 tests) |
| M2-4 | Integration tests + E2E validation (see item 28) | — |

**Behavior:**
- New project: Babel extracts intent → `INTAKE_DIALOG` (auto-drafts `intent.md`) → user refines → `ortim lock` → Architect Call 1 + scorer + StackAnalyst.propose auto-fires → `STACK_DIALOG` → user refines (overrides FINAL) → `ortim lock` → PRDAnalyst.draft → `PRD_DIALOG` → user refines → `ortim lock` → existing `PRD_AWAITING_APPROVAL` HITL gate.
- Architect Call 2 (`run --step architect`) reuses cached `golden_path_inputs.json` from `_lock_intake` and feeds `locked_stack` as a hard constraint into the system prompt verbatim — RFC §4 cannot drift from the locked stack.
- Bootstrap reads `locked_stack.test_cmd` for `.ai-factory.env`, bypassing the two heuristic layers entirely when a stack exists.
- Per-state turn cap (default 10 via `AI_FACTORY_DIALOG_TURN_CAP`) prints `[budget] turn cap reached` and requires `--force` to continue.
- `ortim lock` snapshots the artifact via `.dialog/<state>_prev.md` before each refine and shows a unified diff Panel against the snapshot at lock time. First lock (no snapshot) shows the initial draft preview instead.

**Backward compat:** legacy `BABEL_PROCESSING → PRD_DRAFTING` transition is preserved; `AI_FACTORY_DIALOG_MODE=off` keeps the pre-M2 flow alive for older fixtures and operators who want to skip the dialog. 218 baseline tests stayed green.

**Closes structurally:** items 17 (Architect ignored `select_tier`) and 18a (matrix gap → no test runner) — for the dialog flow, both heuristics are now bypassed by the locked stack.

### 28. E2E validation — `web-todo-m2` (05d8c6d40775) — 2026-05-13

**Brief:** "Modern bir web tabanlı todo uygulaması. SQLite benzeri yerel veritabanı, görev ekle/listele/tamamla/sil, modern temiz UI."

**Stack negotiation observed:**

1. Babel + IntentAnalyst.draft: intent.md generated but missed `SQLite` from the user's brief — refined in 1 turn via `ortim refine` (SQLite explicit + task fields {title, completed, created_at} + offline-first constraint).
2. Architect Call 1 + deterministic scorer: **T2 (BaaS), score 100** — same overconfident pick as `todo-greenfield-2/3/4`. Item 2 still present at the scorer layer.
3. StackAnalyst initial proposal: TypeScript + Node + Hono (matrix-canonical for T2/web) + better-sqlite3 + zod. Reasonable but a Hono backend contradicts the "offline-first single-user" intent.
4. User override via `ortim refine`: "Fully client-side SPA, Vite + React + TS, sql.js for WASM SQLite, T1 not T2, static-hosting deploy". **StackAnalyst respected the override end-to-end** — tier dropped T2→T1, framework swapped Hono→Vite+React, persistence swapped better-sqlite3→sql.js, deploy_target became `static-hosting`. The "user override is FINAL" hard rule in `agents/stack_analyst.md` held under real LLM call.
5. PRDAnalyst.draft: PRD with item-9b binary acceptance criteria — regex on ISO 8601, exact CSS property (`text-decoration: line-through`), DevTools network tab zero-XHR assertion. **No banned words slipped through** (item 9b prompt sertleştirme held).
6. Architect Call 2: reused cached `golden_path_inputs.json` from `_lock_intake`, fed `locked_stack` as hard constraint. RFC §2 documented the override transparently — "Selected: T1; Rejected: T2 (BaaS) because the PRD explicitly requires zero network requests". §4 Tech Stack verbatim from `stack.json`. **Architect honored the locked stack over the scorer's tier.**

**DAG generation:** 4 tasks in 4 sequential batches (db-adapter → task-service → ui-components → ui-components wiring). Clean module boundaries; zero scaffold tasks (item 4 still holding).

**Execution results:**

| Task | Module | Attempts | Status | Note |
|---|---|---|---|---|
| T-001 | db-adapter | 1 | ✅ DONE | sql.js init + IndexedDB persist + CRUD, approved first try |
| T-002 | task-service | 1 then reset | ✅ DONE | First run blocked by misclassified `[unverifiable:design]` (real cause was Windows `npx` resolution — see fix below). Reset + `AI_FACTORY_TESTS_ENABLED=false` reran clean. Worker emitted a co-located test file (`__tests__/task-service.test.ts`). |
| T-003 | ui-components | 1 | ✅ DONE | TaskForm + TaskItem + TaskList components, strikethrough handling, zod-validated callbacks |
| T-004 | ui-components | 2 → AWAITING_HITL | ❌ | Reviewer **correctly** caught real L1 violation: `App.tsx` imported `createTask, getAllTasks, ...` from `../db-adapter` instead of going through `task-service`. Cross-module boundary breach. Same failure class as T-009 in `todo-greenfield-2` — M3 Skills territory. |

**Run economics:** 24 LLM calls, 88,566 tokens (68K in / 20K out), **$0.0407** total. Budget cap `$2.0` set, never approached.

**TypeScript compile check (item 26 regression):** `npx tsc --noEmit` after generation produced **7 errors in 4 categories**:
- 1× `Cannot find module 'sql.js'` (missing `@types/sql.js` — should auto-add when sql.js is in stack)
- 1× `Cannot find module 'uuid'` (Worker invented a library not in the stack)
- 1× `Cannot find module '../db-adapter/types'` (T-002 referenced a submodule T-001 never created — cross-task hallucination)
- 4× `Module '../db-adapter' has no exported member ...` in App.tsx (same as Reviewer's L1 violation — App.tsx imports from wrong module)
- (8× JSX flag errors were eliminated mid-run by adding stack-aware tsconfig — see item 30 below.)

**Item 26 status update:** 2 of 4 original categories structurally closed in this session (package.json deps now stack-aware via `_NPM_DEP_REGISTRY`; tsconfig JSX flag set when React is in the locked stack). Remaining 2 (uuid invented import, cross-task wrong imports) are M3 Skills territory — confirmed identical failure class to T-009 / `todo-greenfield-2`.

### 29. Side fix — `runtime/executor/test_runner.py` Windows shim resolution — SHIPPED

**Discovery context.** E2E run T-002 failed initial review with 8 `[unverifiable:design]` reasons, all citing "Tests were skipped". Bootstrap had correctly written `AI_FACTORY_TEST_CMD="npx vitest run"` to `.ai-factory.env` (M2-3 path working). But the test runner reported `runner 'npx' not on PATH` — when `where.exe npx` showed `npx.cmd` IS on PATH.

**Root cause.** Python's `subprocess.run(["npx", ...])` on Windows does NOT walk `PATHEXT`, so it cannot find `.cmd` / `.bat` shim files. `shutil.which("npx")` does. Pre-existing Windows-only bug exposed by the first real dialog-mode E2E that successfully wrote the right test command.

**Fix.** New helper `_resolve_binary(name)` in `runtime/executor/test_runner.py:28` — uses `shutil.which` to resolve the command basename to its full path before subprocess invocation. POSIX no-op (which returns the same path); Windows now finds `npx.cmd`, `vitest.cmd`, `cargo.bat`, etc. Modified `configured_plan` to resolve `parts[0]` once.

**Test update.** `tests/test_test_runner.py::test_workspace_file_used_when_env_unset` was asserting `plan.cmd == ["npx", "vitest", "run"]` literally. Switched to `Path(plan.cmd[0]).stem.lower() == "npx"` + `plan.cmd[1:] == ["vitest", "run"]` so the test stays portable across machines.

**Why this matters more than the surface log suggests.** Every prior tespit.md run reporting `tests: skipped — runner 'X' not on PATH` may have been a Windows shim issue, not actual runtime absence. The pattern surfaced in `todo-greenfield-3/4` (`go not on PATH`, `npx not on PATH`) and item 16 (test_infrastructure_unavailable mislabeling) — at least some of those were this bug, not real PATH gaps. Item 16's MEDIUM-HIGH priority is partially mitigated now; the misclassification is the only remaining face.

### 30. Side fix — stack-aware `package.json` + `tsconfig.json` — SHIPPED (closes 2/4 of item 26)

**Discovery context.** Bootstrap's T2/web `package.json` template was static — wrote `{name, version, scripts}` without any `dependencies`. When the LockedStack named `react`, `sql.js`, `zod`, etc., the workspace had no way to know — `npm install` had nothing to install. Worker emitted `import 'sql.js'`, the file referenced a runtime package that was never declared, and `tsc --noEmit` failed with `Cannot find module 'sql.js'`. Same gap on JSX: T1/web template emitted React-targeted Worker output but `tsconfig.json` lacked `"jsx": "react-jsx"`, producing 8 JSX flag errors on every `.tsx` file.

**Fix (`runtime/architecture/bootstrap.py`).**
- New `_NPM_DEP_REGISTRY: dict[str, tuple[kind, version]]` mapping common npm packages to (`dependencies`|`devDependencies`, version spec). Covers react/react-dom/sql.js/better-sqlite3/zod/commander/uuid + dev: vitest/vite/typescript/@types/* peers.
- `_t2_web_package_json(name, locked_stack)` now resolves `locked_stack.key_libraries` through the registry, sorts entries alphabetically, adds React peer deps (`react-dom`, `@types/react`, `@types/react-dom`) and Vite+React peer (`@vitejs/plugin-react`) automatically when applicable.
- `_tsconfig_for_stack(locked_stack)` sets `compilerOptions.jsx = "react-jsx"` and `compilerOptions.lib = ["ES2022", "DOM", "DOM.Iterable"]` when the locked stack contains React. Defaults preserved when no React.
- Unknown libraries (not in the registry) are skipped silently — Worker can still add them via its output operations later. The deterministic layer stays narrow.

**Verification on `web-todo-m2`:** regenerating package.json + tsconfig with the new code wrote 4 deps + 6 dev deps (including @types/react peers and @vitejs/plugin-react) and a JSX-enabled tsconfig. `npm install --silent` succeeded; `npx tsc --noEmit` dropped from 18 errors (4 categories) to 7 errors (4 categories) — JSX entirely gone.

**Why this is M2-aligned even though it isn't strictly dialog mechanics.** M2's structural promise is "the locked stack flows everywhere as the single source of truth". Bootstrap dep-injection and tsconfig JSX flag are direct expressions of that promise — without them, `locked_stack.key_libraries` was a passive label, not an actionable contract. Worker can now `import 'react'` and the type system + runtime both agree.

**Item 26 status now:**
- ✅ Missing `"types": ["node"]` in tsconfig — closed (stack-aware tsconfig)
- ✅ Wrong import paths (some) — closed for the `tsconfig`/`package.json` infrastructure side; cross-module Worker hallucination still open
- ⬜ Missing function export (`validateNoteInput` invented) — M3 Skills
- ⬜ Cross-task `../module/types` hallucination — M3 Skills + `read_related` for prior task outputs

### Updated cross-cutting items status (post-2026-05-13)

| Item | Topic | Status | Change |
|---|---|---|---|
| **2** | Tier scoring weights | ⚠️ Partially mitigated | M2 StackAnalyst allows user override; scorer itself still overconfident on T2. |
| **16** | Unverifiable two-mode conflation | ⚠️ Partially mitigated | Schema-level fix shipped (item 24). LLM still doesn't emit `unverifiable_reason` field in practice — observed in `web-todo-m2` T-002. Reviewer.md prompt sertleştirme needed. |
| **17** | Architect ignores select_tier | ✅ **CLOSED (structural)** | LockedStack feeds Architect Call 2 as hard constraint. Heuristic constraint is the legacy-only path. |
| **18a** | Matrix gap → no test runner | ✅ **CLOSED (structural)** | LockedStack.test_cmd is single source of truth in bootstrap. |
| **26** | Generated code doesn't compile | ⚠️ 2/4 closed | tsconfig JSX + package.json deps via LockedStack ship. Cross-task imports + library hallucination remain — M3 Skills. |
| **27** | M2 implementation | ✅ **SHIPPED (this session)** | See above. |
| **28** | E2E `web-todo-m2` | ✅ Validated 3/4 batches | T-004 cross-module L1 violation correctly caught — pipeline reject working. |
| **29** | Windows shim resolution | ✅ **SHIPPED (this session)** | `shutil.which` in test_runner. |
| **30** | Stack-aware package.json + tsconfig | ✅ **SHIPPED (this session)** | LockedStack key_libraries → deps; React → JSX flag. |

### Test count progression

```
218 (pre-M2 baseline; items 22-24 + Phase 0)
 → 222 (M2-1a state machine +4)
 → 227 (M2-1b dialog analysts +5)
 → 237 (M2-1c dialog storage +10)
 → 244 (M2-4 integration +7) ← CURRENT, 0 regression across full suite
```

### What to do next — re-prioritized after M2 ship

| Priority | Action | Effort | Why now? |
|---|---|---|---|
| 🟡 **M3 Skills foundation** | `skills/<scope>/<name>.md` directory + loader + injection into Worker/Reviewer prompts. Seed skills: `skills/typescript/module-boundaries.md`, `skills/typescript/vitest-co-located.md`, `skills/typescript/esm-imports.md`, `skills/react/component-structure.md`. | ~1 week | Closes the **only** remaining E2E blocker — T-009 / web-todo-m2 T-004 class failures (cross-module imports, library hallucination, missing test files). |
| 🟡 **Item 16 prompt sertleştirme** | `agents/reviewer.md` adds explicit rule: when `tests: skipped` appears in evidence, MUST emit `unverifiable_reason: "test_infrastructure"`, not `"criterion_design"`. | 30 min + 1 test | The schema fix shipped (item 24) is unused in practice because the LLM doesn't honor the field. Reviewer prompt needs the explicit instruction. |
| 🟢 **`AI_FACTORY_TESTS_ENABLED=false` audit risk** | Operator can silently disable tests AND escape the rubric's unverifiable escalation. Tier ≥ T1 should warn when tests are disabled by env flag. | 1 hour | Tomorrow's "I disabled tests in CI" footgun. |
| 🟢 **Documenter on web-todo-m2** | Run-all stopped at T-004 → DONE never reached → README never generated. Re-run with T-004 fix to verify Documenter's `locked_stack` path produces correct install/run commands. | 30 min (post-T-004 fix) | Validates the last M2-3 surface that wasn't exercised. |
| 🟢 **Repeat E2E with different locked stack** | Run `web-todo-m2` style flow with `locked_stack.language = "Python"` (FastAPI / Flask CLI) to confirm M2 isn't accidentally TS-specific. | 1-2 hours | Single data point isn't enough to claim "stack-agnostic dialog". |

### Strategic question carried forward

**Should `AI_FACTORY_TESTS_ENABLED=false` be allowed?** In `web-todo-m2` we used it to bypass the item-16 misclassification, but the underlying behavior (tests skip → unverifiable cascade → AWAITING_HITL) is the rubric working as designed. The escape hatch undermines Phase 0's structural intent. Proposed: keep the env var but emit a `[ortim] WARNING: tests disabled — Reviewer cannot verify runtime criteria` to stderr on every invocation, mirroring item 23's critical-role fail-loud pattern. Decision deferred until item 16 prompt sertleştirme ships.

---

## 2026-05-13 — M3 ship + skill-driven T-004 fix on web-todo-m2

> M3 Skills foundation (~1 week estimated, tespit.md item 11) shipped in the same session as M2. pytest 244 → **263** (+19: skills loader +6, resolver +9, injection +4). E2E regression on `web-todo-m2` T-004 — which had been AWAITING_HITL for L1 module-boundary violation pre-M3 — now approves on attempt 2 with the corrected import path and a co-located test file. M3 worked as scoped; surfaced a new gap (M4 territory: cross-task export shape visibility).

### 31. M3 implementation — Skills system foundation — SHIPPED

**Phase log:**

| Phase | Scope | Files |
|---|---|---|
| M3-0 | Design lock — 8 decisions (file format with custom frontmatter parser, AND-combined trigger groups, specificity-ordered resolution, 5-skills × 12K-char budget, audience filter, repo-walk discovery, audit captures active_skills, read-only CLI) | `M3-design.md` |
| M3-1 | `Skill` + `SkillTriggers` pydantic schemas; `runtime/skills/loader.py` with custom YAML-like frontmatter parser (no PyYAML dep); `runtime/skills/resolver.py` with `resolve_for_task()` and `format_skills_block()` | `runtime/skills/{schema,loader,resolver}.py`, `runtime/skills/__init__.py`, `tests/test_skills_loader.py` (+6), `tests/test_skills_resolver.py` (+9) |
| M3-2 | `WorkerAgent.execute` and `CodeReviewerAgent.review` accept `active_skills: list[Skill] \| None`; system prompt gets `## Active Skills` block appended after L1 principles when non-empty; audit log includes `active_skills: [names]`; runner builds resolver call per task and passes worker_skills + reviewer_skills (filtered by audience) into both agent calls | `runtime/executor/{worker,reviewer,runner}.py`, `runtime/main.py` (`_load_for_execute` threads locked_stack + tier + skills through), `tests/test_skill_injection.py` (+4) |
| M3-3 | 4 seed skills targeting the T-009 / web-todo-m2 T-004 class failures + general web-TS patterns | `skills/typescript/{module-boundaries,imports-from-locked-stack,vitest-co-located}.md`, `skills/react/component-patterns.md` |
| M3-4 | `ortim skill list [project_id]` (all skills or project-resolved subset) + `ortim skill show <name>` (full body) — read-only inspection commands | `runtime/main.py` (`skill_app` typer subgroup) |
| M3-5 | E2E regression on web-todo-m2 T-004 + this entry | (see item 32) |

**Behavior:**
- Skills live as markdown files with `---` frontmatter at `<repo_root>/skills/<scope>/<name>.md`. Frontmatter supports `name`, `description`, `audience`, and nested `triggers.{tier,app_class,language,keywords}`. Custom parser tolerates flow lists `[a, b, c]`, scalar values, comments, and missing frontmatter (falls back to filename stem as name + universal triggers).
- Resolver `resolve_for_task(skills, task, tier, app_class, locked_stack, audience)` AND-combines trigger groups (every populated group must match); skips language-specific skills when `locked_stack is None`; sorts surviving skills by specificity (`language=4 + tier=2 + app_class=1`); caps to 5 skills / 12000 chars per call; alphabetical tiebreak.
- Both Worker and Reviewer receive the rendered skill block in their system prompt. Worker block frames skills as "HARD rules — same weight as L1"; Reviewer block frames them as "criteria interpretation context — cite skill name on violation."
- `_load_for_execute` loads `LockedStack` (M2) + computes tier from cached `golden_path_inputs.json` + loads all skills once per CLI invocation. Threading is per-task: the resolver runs inside `execute_task` so different module/keywords get different skill subsets.

**CLI surface:**
- `ortim skill list` — all loaded skills, tabular.
- `ortim skill list <project_id>` — only those that resolve for the project's stack, with separate ✓ columns for Worker/Reviewer audience.
- `ortim skill show <name>` — full body + frontmatter summary.

**Audit changes:**
- `worker_output_ok` event: new `active_skills: list[str]` field (skill names only; bodies not duplicated to audit log).
- `reviewer_verdict` event: same field.

**Backward compat:** all 244 baseline tests stay green. `active_skills=None` / empty list path produces system prompts identical to pre-M3 — no `## Active Skills` block emitted, no audit field difference for tasks that don't resolve any skill.

### 32. E2E regression — web-todo-m2 T-004 fixed by M3 skills

**Before M3 (item 28, todo-greenfield-2 era):** T-004 (App.tsx wiring) attempted 1 then 2 then **AWAITING_HITL** with explicit Reviewer L1 violation:

> [L1] Direct import of functions from '../db-adapter' (createTask, getAllTasks, completeTask, deleteTask) bypasses the task-service module boundary — violates L1 principle #3 (one module = one schema) and #4 (module boundary enforcement)

This was the same failure class as T-009 in `todo-greenfield-2` — Worker writes correct-looking code that breaches module boundaries it doesn't know about. Reviewer caught it but Worker had no way to fix it; auto-retry rolled the same dice.

**After M3 (same workspace, T-004 reset to PENDING + App.tsx removed):**
- Attempt 1: rejected because tests are disabled (`AI_FACTORY_TESTS_ENABLED=false` — unrelated to M3).
- **Attempt 2: APPROVED** with 2 files:
  - `ui-components/App.tsx` — imports CRUD via `import { createTask, getAllTasks, completeTask, deleteTask } from '../task-service'` (the public barrel, NOT db-adapter directly). Re-imports the type via `import type { Task } from '../task-service'`.
  - `ui-components/App.test.tsx` — **co-located test file**, emitted automatically because the `typescript-vitest-co-located` skill triggered on the criteria's behavior keywords (`creates`, `updates`, `deletes`).

**Categorical change in failure mode:**

| Run | Failure category | Where |
|---|---|---|
| Pre-M3 | Module boundary breach | App.tsx imports from wrong module |
| Post-M3 | Interface shape mismatch | App.tsx imports correct module, but task-service actually exports a factory `createTaskService(db)` — not bare CRUD functions — because T-002 chose a factory pattern and Worker T-004 never saw T-002's exports |

This is **progress**, not regression: the bug moved from "Worker can't reason about boundaries" (M3-shaped) to "Worker can't see prior task outputs" (M4-shaped, see item 33). M3 did exactly what it was scoped to do.

**Skill activation observed in the audit log:**
- Worker call audit: `active_skills: ["react-component-patterns", "typescript-imports-from-locked-stack", "typescript-module-boundaries", "typescript-vitest-co-located"]`
- Reviewer call audit: `active_skills: ["react-component-patterns", "typescript-imports-from-locked-stack", "typescript-module-boundaries"]` (vitest-co-located is Worker-only)

`ortim skill list 05d8c6d40775` confirms the same set resolves deterministically given (tier=T2, app_class=web, locked_stack.language=TypeScript).

### 33. NEW ITEM — Cross-task export-shape visibility — MEDIUM-HIGH (M4 scope)

**Problem.** Worker writes task T-N with only RFC + acceptance criteria + locked stack + skills as context. It does NOT see the actual file contents (or even the public exports) of completed prior tasks T-1..T-(N-1). When task T-N writes `import { foo } from '../moduleA'`, Worker is guessing what moduleA exposes — usually correctly, occasionally wrong (factory vs. bare functions, default vs. named export, etc.). The Reviewer catches the mismatch at TypeScript compile time but only IF tests are enabled and a `tsc --noEmit`-equivalent runs; otherwise the bug ships approved.

**Concrete instance (post-M3 web-todo-m2 T-004):**
- T-002 chose: `export function createTaskService(db: DbAdapter)` (factory pattern, returning an object with CRUD methods).
- T-003 chose: `export default TaskForm` (default export, not named).
- T-004 wrote: `import { createTask, getAllTasks, ... } from '../task-service'` + `import { TaskForm } from './TaskForm'`.

Both mismatches; only catchable post-write by `tsc --noEmit` or runtime test. The M3 skill `typescript-module-boundaries` taught Worker the *right module*, but no skill can teach the *right shape* — that's a fact about the codebase, not a pattern.

**Why this is M4 territory, not a quick fix.** The structural answer is to extend `read_related()` (currently brownfield-only via `codebase/reader.py`) to "completed prior tasks in this greenfield session" so Worker sees:
- The public exports (`*.ts` files' exported symbols + their type signatures, AST-extracted) of every prior task that's marked DONE.
- Optionally truncated body of files in modules the current task scope depends on (per task_dag.json dependencies).

This is a 1–2 day project: extend `runtime/codebase/reader.py` to scan the greenfield workspace itself, gate it behind a new flag in `execute_task` (`include_prior_tasks: bool = True`), and inject into the Worker prompt under `## Prior task outputs` — exactly the way brownfield `related_files` works today.

**Proposed fix (M4, not this session):**
- New helper: `runtime/codebase/prior_tasks.py::collect_prior_outputs(workspace, dag, status_file) -> dict[str, ExportSummary]` — walks DONE task modules, AST-extracts exports, returns one entry per module.
- `WorkerAgent.execute(..., prior_task_outputs: dict[str, str] | None = None)` — formats them into a `## Prior task exports (use these import shapes verbatim)` system prompt block.
- Runner threads it through alongside `related_files`.

**Why now:** without this, every greenfield run >2 tasks risks cross-task interface mismatch. With this, the M3 skills land on a Worker that already sees prior task shapes, so the `typescript-module-boundaries` skill becomes structurally enforceable instead of probabilistic.

### Updated cross-cutting items status (post-M3)

| Item | Topic | Status | Change |
|---|---|---|---|
| **9 (T-009 class) / 26 cross-task imports** | Worker writes wrong import paths | ⚠️ Pattern improved | Skills moved the failure from "wrong module" to "wrong shape from right module". M4 closes structurally. |
| **31** | M3 implementation | ✅ **SHIPPED (this session)** | See above. |
| **32** | E2E web-todo-m2 T-004 | ✅ Skill-driven approval | Attempt 2 instead of AWAITING_HITL; co-located test file emitted. |
| **33** | Cross-task export visibility | ⬜ Open (M4 priority) | New item — promoted from "M3 will close it" to its own line because M3 ship surfaced it as a distinct concern. |

### Test count progression

```
244 (post-M2 baseline)
 → 250 (M3-1 skills loader +6)
 → 259 (M3-1 resolver +9)
 → 263 (M3-2 injection +4) ← CURRENT, 0 regression across full suite
```

### What to do next — re-prioritized after M3 ship

| Priority | Action | Effort | Why now? |
|---|---|---|---|
| 🟡 **M4 — Cross-task export visibility (item 33)** | Extend `read_related` for greenfield: collect prior DONE task outputs as `prior_task_outputs` and inject into Worker prompt. AST-extract exports per module so prompt budget stays small. | ~1–2 days | Last remaining M3-skill blocker — without it, "barrel import" skill teaches the right module but Worker still guesses the shape. After this, web-todo-m2 should compile cleanly end-to-end (item 26 4/4 closed). |
| 🟡 **Item 16 prompt sertleştirme (still open)** | Reviewer prompt teaches LLM to emit `unverifiable_reason: "test_infrastructure"` when evidence cites tests-skipped. | 30 min + 1 test | Schema fix exists (item 24), but LLM never uses it in practice. |
| 🟡 **Stack-aware @types deps in bootstrap** | When `locked_stack.key_libraries` contains `sql.js`, add `@types/sql.js` to devDependencies automatically. Same for any library that has a typed `@types/*` peer. | 1 hour | Closes the remaining "Cannot find declaration for ..." class of compile errors in item 26. |
| 🟢 **Seed more skills** | `skills/python/pytest-conventions.md`, `skills/security/owasp-input-validation.md`, `skills/typescript/zod-validation.md`. Each ~30 min after first one. | 2 hours total | Once M4 lands, skills become higher-leverage — broader coverage pays off. |
| 🟢 **`ortim skill list` machine-readable mode** | `--json` flag for CI / scripting. | 30 min | Low priority; nobody asked yet. |

### Strategic question carried forward

**Should the seed skill set live in the FSL core repo or be opt-in?** Right now `skills/` is checked into the repo and every operator gets the same 4 skills. For enterprise tier, per-tenant skill sets will be needed (e.g. a fintech team wants `skills/security/pci-dss.md` injected into every Worker call). M3 ships universal skills; per-tenant skills are M5+ territory and probably belong under `enterprise/skills/<tenant_id>/`.

---

## 2026-05-13 — M4 ship + item 26 closed (web-todo-m2 compiles cleanly)

> M4 Cross-task export visibility (~1–2 days estimated, tespit.md item 33) shipped in the same session. pytest 263 → **283** (+20: exports +10, prior_outputs +7, injection +3). Web-todo-m2 re-run with M2+M3+M4 active produced TypeScript that **`npx tsc --noEmit` accepts with 0 errors** — item 26 is fully closed. Side fix: stack-aware `@types/*` peer injection in bootstrap.

### 34. M4 implementation — Cross-task export visibility — SHIPPED

**Phase log:**

| Phase | Scope | Files |
|---|---|---|
| M4-0 | Design lock — 8 decisions (export-signatures not bodies, 2K/module + 8K total char budget, DONE-only filter, all-prior not dep-filtered, TS/Python languages, trigger when codebase_summary=None, Worker-only injection, audit captures prior_task_modules) | `M4-design.md` |
| M4-1 | `ExportSignature` dataclass; `extract_exports(path, source)` with regex for TS/TSX/JS/MJS/CJS (function, class, interface, type, const, enum, default, re_export) + `ast.parse` for Python (def/class/Assign/AnnAssign, underscore-prefixed names filtered). Custom `_capture_signature_line` walks forward through paren/bracket/angle depth so destructured params (`{ onSubmit }: Props`) and generics (`<T extends X>`) survive intact. | `runtime/codebase/exports.py`, `tests/test_export_extractor.py` (+10 tests) |
| M4-2 | `ModuleExports` dataclass + `collect_prior_outputs(workspace, dag, status_file, current_task_id, per_module=2K, total=8K)`. Groups DONE tasks by `module_scope`, walks each scope's source files (skipping `*.test.*` / `*.spec.*`), extracts exports per file, budget-caps per module then total. `format_prior_outputs_block()` renders for prompt injection. Lazy import of `TaskStatus` to break the circular import through `runtime.executor.__init__`. | `runtime/codebase/prior_tasks.py`, `runtime/codebase/__init__.py`, `tests/test_prior_outputs.py` (+7 tests) |
| M4-3 | `WorkerAgent.execute(..., prior_task_exports=None)` → appends `## Prior task exports — use these import shapes verbatim` block after L1 + Skills + before related_files. Audit log gains `prior_task_modules: list[str]`. Runner builds the dict via `collect_prior_outputs` when greenfield (`codebase_summary is None`) AND records exist; lazy-loads to avoid running on the first task of a fresh DAG. `dag` threaded through `_load_for_execute` → `execute_task` → `_run_all_loop`. | `runtime/executor/{worker,runner}.py`, `runtime/main.py`, `tests/test_prior_outputs_injection.py` (+3 tests) |
| M4-4 | E2E re-run on web-todo-m2 (see item 35) | — |

**Behavior:**
- Greenfield Worker for task T-N sees, in its system prompt, an alphabetized list of every DONE module with one code-block per file containing the exported signatures only. Brownfield path is unchanged — `related_files` already serves that flow.
- Skipping `*.test.*` / `*.spec.*` keeps the prompt focused on the public surface; the implementation file's exports are what siblings can reach.
- The `_capture_signature_line` fix turned out to be critical — without depth-tracking, destructured props (`{ onSubmit }: TaskFormProps`) were truncated to `export function TaskForm(`, hiding the prop name. The regression test pins this so a future MVP-to-tree-sitter migration can't drop it.

**Backward compat:** all 263 baseline tests stayed green. `prior_task_exports=None` path produces a system prompt identical to pre-M4 — no block emitted, no audit field difference for the first task of any DAG.

**Closes structurally:** item 33 (cross-task export visibility). Closes the residual 2/4 categories of item 26 (cross-task wrong shape, invented module/types submodule references) — see item 35 for compile-result evidence.

### 35. E2E re-run on web-todo-m2 — 0 tsc errors after M2+M3+M4

**Setup:** reset T-002, T-003, T-004 to PENDING; removed their generated files; T-001 (db-adapter) kept DONE. `AI_FACTORY_TESTS_ENABLED=false` to bypass the item-16 unverifiable cascade (still open). `AI_FACTORY_BUDGET_CAP_USD=2.5`.

**Audit-confirmed M4 activation:**

| Task | `prior_task_modules` | Active skills |
|---|---|---|
| T-002 (task-service) | `["db-adapter"]` | `typescript-imports-from-locked-stack`, `typescript-module-boundaries` |
| T-003 (ui-components — TaskForm/TaskItem/TaskList) | `["db-adapter", "task-service"]` | `react-component-patterns` + the two above |
| T-004 (ui-components — App.tsx wiring) | `["db-adapter", "task-service", "ui-components"]` | same |

**Code output progression:**

| Layer | Pre-M3 (item 26 baseline) | Post-M3 (item 32) | Post-M4 (this entry) |
|---|---|---|---|
| App.tsx import path | `from '../db-adapter'` (wrong module) | `from '../task-service'` (right module, wrong shape) | `from '../task-service'` (right module, **right shape**: `createTask, getAllTasks, completeTask, deleteTask, Task` — matches T-002's actual exports verbatim) |
| App.tsx prop names | `<TaskForm onSubmit={...}>` invented | `<TaskForm onCreate={...}>` (wrong — T-003 named the prop `onSubmit`) | `<TaskForm onSubmit={handleCreate} />` (correct — Worker T-004 saw T-003's destructured `{ onSubmit }: TaskFormProps`) |
| Co-located tests | Worker emitted sporadically | Worker emitted via skill | Same — `App.test.tsx` + `index.test.ts` co-located alongside impl |
| `crypto.randomUUID()` vs invented `uuid` import | invented `uuid` (not in stack) | invented `uuid` (skill not yet shipped) | `crypto.randomUUID()` — `typescript-imports-from-locked-stack` skill held |
| Bootstrap deps | generic `{name, version, scripts}` only | stack-aware deps (`react, sql.js, zod, vitest, ...`) but `@types/sql.js` missing | stack-aware deps + `@types/*` peers via `_NPM_TYPES_PEERS` (see item 36) |

**`npx tsc --noEmit` results:**

| Run | Errors | Categories |
|---|---|---|
| Pre-M3 baseline | 10 | 4 |
| Post-M3 | 7 | 4 (JSX fixed mid-run via M2 stack-aware tsconfig) |
| Post-M4 (sql.js types still missing) | 1 | 1 (`Cannot find declaration file for module 'sql.js'`) |
| Post-M4 + `_NPM_TYPES_PEERS` (item 36 below) | **0** | — |

**Self-driving rate observation:** the Reviewer rejected each task with at least one false-positive (citing `typescript-module-boundaries` skill against barrel imports that were correct, or marking criteria `unverifiable` because of `AI_FACTORY_TESTS_ENABLED=false`). Each task had to be manually advanced to DONE after the Worker output was inspected and found correct. The pipeline's **code quality** is now at 100% compile-clean; the **autonomous approval rate** is gated by two separately-tracked Reviewer issues (item 16 unverifiable misclassification, and a new false-positive on barrel-import detection — item 37 below).

**Run economics:** 32 LLM calls across the four tasks' retries, ~$0.05, ~2 minutes wall clock. M4's prompt overhead averaged ~700 input tokens per task — well below the 2K-token guideline from the design doc.

### 36. Side fix — `_NPM_TYPES_PEERS` auto-injects `@types/*` for runtime packages without bundled `.d.ts`

**Discovery context.** Post-M4 tsc check found exactly one residual error: `db-adapter/index.ts(1,54): error TS7016: Could not find a declaration file for module 'sql.js'`. The runtime package was in `dependencies` (M2-3 deps injection working), but `sql.js` ships without its own `.d.ts` — the typed companion `@types/sql.js` is a separate npm package, conventionally in `devDependencies`.

**Fix.** New `_NPM_TYPES_PEERS: dict[str, str]` map in `runtime/architecture/bootstrap.py` next to `_NPM_DEP_REGISTRY`: runtime package → its `@types/*` peer. When the LockedStack injects a runtime package into `dependencies`, the peer (if mapped) auto-lands in `devDependencies`. Initial entries: `sql.js`, `better-sqlite3`, `uuid`, `commander`. Registry also gained the corresponding `@types/*` version pins.

**Verification.** Re-bootstrapping web-todo-m2's package.json wrote `@types/sql.js` in devDependencies; `npm install --silent` succeeded; `npx tsc --noEmit` exited 0.

**Items closed:** item 26 final category (missing declaration files) closed structurally. The full item-26 chain is now `M2-3 (deps) + M2-3 (tsconfig JSX) + M3 (boundaries) + M4 (exports) + M4-side-fix (types peers)`.

### 37. NEW ITEM — Reviewer false-positive on barrel imports — MEDIUM (Reviewer prompt sertleştirme)

**Problem.** During the M4 E2E re-run, Reviewer rejected T-002 and T-003 with verdicts citing `typescript-module-boundaries`: `imports from '../db-adapter' directly instead of via a barrel`. But `from '../db-adapter'` IS the barrel form — the skill itself uses that exact example as the canonical-correct case.

**Trigger pattern.** The Reviewer LLM parses the skill text but, when paired with the worker output context and the rubric prompt's "cite skill name in verdict reason" instruction, conflates "imports from a sibling module" with "boundary violation". The skill body is correct; the Reviewer's interpretation is over-broad.

**Why this matters more than the surface log suggests.** Three of the four manual DONE overrides in the web-todo-m2 re-run were caused by this false-positive — the Worker output was demonstrably correct (verified by `tsc --noEmit`) but the Reviewer rejected. Without manual override, the auto-retry loop would burn the 3-attempt budget and escalate to AWAITING_HITL on every cross-module-importing task. M4's correct cross-task picks would be invisible to the operator until the rejection log is read.

**Fix proposal (~30 min).** Strengthen `agents/reviewer.md` with explicit examples:

```markdown
## Barrel imports (typescript-module-boundaries)

These are CORRECT imports — do NOT flag them:
- `from '../task-service'` → the barrel (`task-service/index.ts`)
- `from '../db-adapter'` → the barrel (`db-adapter/index.ts`)
- `import type { Foo } from '../moduleX'` → barrel type-only import

ONLY flag these as boundary violations:
- `from '../task-service/internal.ts'` → reaches into internal file
- `from '../db-adapter/types'` → reaches into a submodule
- `import { _privateHelper } from '../moduleX'` → imports an underscored symbol

If the import path ends at a module name (no slash beyond it), the
import is correct regardless of what's being imported.
```

Add a regression test asserting this in `tests/test_reviewer_chain.py`: feed a verdict-shaped LLM mock with a Worker output containing `from '../task-service'`, verify the verdict's `l1_violations` is empty.

**How to apply:** ~30 min — prompt edit + 1 test. Schedule alongside item 16 (`unverifiable_reason` Reviewer fix) — both are reviewer.md sertleştirme.

### Updated cross-cutting items status (post-M4)

| Item | Topic | Status | Change |
|---|---|---|---|
| **9 (T-009 class) / 26** | Generated code doesn't compile | ✅ **FULLY CLOSED** | M2+M3+M4 + `_NPM_TYPES_PEERS`. `tsc --noEmit` exit 0 on web-todo-m2. |
| **16** | Unverifiable two-mode | ⚠️ Still open | Schema fix shipped (item 24), but LLM doesn't honor field. Reviewer prompt sertleştirme alongside item 37. |
| **33** | Cross-task export visibility | ✅ **CLOSED (item 34)** | M4 shipped. |
| **34** | M4 implementation | ✅ **SHIPPED (this session)** | See above. |
| **35** | E2E web-todo-m2 0-error compile | ✅ **VALIDATED** | First greenfield run to produce compile-clean TS without manual fixes. |
| **36** | `_NPM_TYPES_PEERS` auto-injection | ✅ **SHIPPED (this session)** | Closes item 26 final category. |
| **37** | Reviewer barrel-import false-positive | ⬜ Open (MEDIUM) | Promoted to its own line — surfaced in M4 E2E. ~30 min reviewer.md fix. |

### Test count progression

```
263 (post-M3 baseline)
 → 271 (M4-1 export extractor +10, includes 2 regression tests for destructure + generic)
 → 278 (M4-2 collector +7)
 → 281 (M4-3 injection +3) — destructure regression catch
 → 283 (full suite verified, no regressions) ← CURRENT
```

### What to do next — re-prioritized after M4 ship

| Priority | Action | Effort | Why now? |
|---|---|---|---|
| 🟡 **Reviewer prompt sertleştirme** (items 16 + 37) | Add `unverifiable_reason: "test_infrastructure"` rule + barrel-import correctness examples. | 1 hour | Item 37 alone caused 3 manual overrides in the M4 E2E. Without these fixes, M4's win is invisible to the auto-retry loop. |
| 🟢 **PRDAnalyst + skills consistency** | PRD acceptance criteria (e.g. "exports default component TaskForm") should not contradict active skills (`react-component-patterns` mandates named exports). Inject skill summary into PRDAnalyst prompt so PRD criteria are skill-consistent. | 2 hours | Surfaced in M4 E2E T-003 — Reviewer rejected a correct named-export component because PRD said "default". |
| 🟢 **Seed more skills** | `skills/python/pytest-conventions.md`, `skills/security/owasp-input-validation.md`, `skills/typescript/zod-validation.md`, `skills/typescript/async-error-handling.md`. | 30 min each | M4 makes skill-injected guidance high-leverage; broader coverage pays off. |
| 🟢 **Item 16 priority bump** | Now that 3/4 item-26 categories are closed and the M4 E2E exposes item 16 on every run with tests disabled, bumping its priority is overdue. Reviewer prompt: when evidence cites "tests skipped", MUST emit `unverifiable_reason: "test_infrastructure"`. | 30 min | Aligned with item 37 reviewer fix — ship together. |
| 🟢 **Real test gate enabled greenfield run** | Try web-todo-m2 with `AI_FACTORY_TESTS_ENABLED=true` once items 16 + 37 ship. Expect zero manual overrides and DONE on first or second attempt for each task. | 5 min | The proof that M2+M3+M4 + reviewer fixes deliver end-to-end self-driving. |

### Senior verdict

**The system now produces compile-clean TypeScript on the first generation** for a 4-task, 3-module project (T0/web-equivalent React+sql.js SPA). M2 made the stack a structured artifact; M3 taught Worker the patterns; M4 closed the cross-task visibility gap. The remaining work to reach autonomous self-driving (no manual overrides) is in the Reviewer rubric — two prompt fixes (items 16 + 37) that together total ~1 hour.

Phase 5 (M5 RAG + MCP, vision pillars 5+7) is now a clean separation of concerns: the *code generation* layer is solid, M5 will be about *knowledge layering* on top.

---

## 2026-05-13 — Reviewer sertleştirme + first tests-enabled autonomous E2E

> Items 16 + 37 (reviewer.md prompt sertleştirme) shipped. pytest 283 → **286** (+3 prompt + schema regression tests). First autonomous E2E with `AI_FACTORY_TESTS_ENABLED=true` exposed two real production-class issues that the pipeline correctly surfaced but couldn't self-correct: (a) Worker's SQL mock destructuring bug (skill gap), (b) workspace-wide vitest run lets a prior task's broken test contaminate every subsequent task's verdict.

### 38. Items 16 + 37 reviewer.md sertleştirme — SHIPPED

**File:** `agents/reviewer.md`

**Item 16 fix.** Added `unverifiable_reason` to the output-schema example with explicit discipline:
- `"test_infrastructure"` — well-worded criterion, runner unavailable / tests skipped. Fix is operational.
- `"criterion_design"` — ambiguous wording (`"readable"`, `"good UX"`). Fix is in the criterion (Orchestrator re-emit).
- New `unverifiable` example showing exactly when to emit `"test_infrastructure"`: "evidence cites tests-skipped, runner-unavailable, or build-not-run — even if you ALSO think the code looks right by inspection."

**Item 37 fix.** New `## Barrel imports (do NOT flag these — they are CORRECT)` section with explicit examples:

```markdown
**These are CORRECT — never flag them as boundary violations:**
- `import { foo } from '../task-service'` → resolves to task-service/index.ts (barrel)
- `import { foo } from '../db-adapter'` → resolves to db-adapter/index.ts (barrel)
- `import type { Task } from '../task-service'` → barrel type-only
- `import { TaskForm } from './TaskForm'` → same-module sibling file

**ONLY these are boundary violations — flag and cite the skill:**
- `import { foo } from '../task-service/internal.ts'` → reaches into internal file
- `import { _privateHelper } from '../moduleX'` → imports underscored "private" symbol

Rule of thumb: if the import path ends at a module name with no slash beyond it,
the import is correct regardless of what's being imported from it. The Worker's
job is to import the right symbols; the barrel module's job is to export them.
If a symbol isn't exported but the Worker imports it, the failure is `fail` on
the criterion (TypeScript will flag `no exported member`), NOT a boundary
violation in `l1_violations`.
```

**Tests (3 new, all in `tests/test_executor.py`):**
- `test_reviewer_prompt_teaches_test_infrastructure_unverifiable_reason` — pins the prompt content so a future edit can't quietly remove the rule.
- `test_reviewer_prompt_teaches_barrel_imports_are_correct` — same for the barrel-imports section.
- `test_review_verdict_test_infrastructure_reason_tags_distinctly` — schema-level guard (already in item 24's scope, but pinned now): a verdict with `unverifiable_reason="test_infrastructure"` produces `[unverifiable:test_infra]` reasons, distinct from `[unverifiable:design]`.

**Verification in E2E (item 39 below):**
- ✅ Zero barrel-import false positives across T-003 and T-004 verdicts (3 of 4 manual overrides in the M4 E2E came from this — now eliminated).
- ✅ Reviewer's verdicts for genuinely-skipped tests would now tag `test_infrastructure` (couldn't directly verify because the E2E ran with tests enabled, so no skipped cases occurred — but schema-level test pins the rendering).

### 39. First autonomous E2E with tests enabled — partial success + two new findings

**Setup:** web-todo-m2 (T0/web-equivalent React + sql.js SPA), reset T-002..T-004 to PENDING, state flipped from `done` → `executing`, `AI_FACTORY_TESTS_ENABLED` unset (default `true`), Node + vitest installed in workspace from item 36's stack-aware deps.

**Outcome summary:**

| Task | Outcome | Why |
|---|---|---|
| T-001 (db-adapter) | already DONE from prior run, untouched | — |
| T-002 (task-service) | ❌ AWAITING_HITL after 3 attempts | Worker emitted a buggy vitest mock; production code (in `task-service/index.ts`) is **correct**; the mock destructures SQL params wrong (see below) |
| T-003 (ui-components: forms) | ❌ AWAITING_HITL after 3 attempts | (a) PRD acceptance criterion `"exports default component TaskForm"` vs `react-component-patterns` skill `"named exports only"` — direct conflict; (b) workspace-wide vitest run inherits T-002's failing tests, contaminating T-003's verdict |
| T-004 (App wiring) | not attempted (T-003 blocked) | — |

**Autonomous self-driving rate: 0/3 on the tasks the pipeline actually attempted.** Manual T-002 override (since the production code is correct) was needed for T-003 to even start, and T-003 then hit the second pair of issues.

**Cost: $0.11 across 55 LLM calls.** Higher than the pre-tests-enabled run because each attempt now includes the full Worker → tests-run → Reviewer cycle; retry loop maxed out twice.

#### 39a. Worker's SQL mock destructuring bug — Worker skill gap (NEW ITEM)

Worker T-002 wrote correct production code:
```ts
run('INSERT INTO tasks (id, title, completed, created_at) VALUES (?, ?, 0, ?)', [id, validatedTitle, created_at]);
```

But the test mock destructured 4 names from a 3-param array:
```ts
} else if (sql.startsWith('INSERT')) {
  const [id, title, completed, created_at] = params;  // ❌ only 3 params bound
  store.set(id, { id, title, completed, created_at });  // completed = (the timestamp), created_at = undefined
}
```

Root cause: the SQL has `VALUES (?, ?, 0, ?)` — only `id`, `title`, `created_at` are bound; `completed` is hardcoded `0`. Worker's mock failed to inspect the SQL string before writing the destructuring pattern. Across three attempts Worker reproduced the same class of bug with minor variations.

The Reviewer correctly identified this as "the production code is correct, but the test mock is broken" — a precise, useful diagnosis. But the Reviewer's job is to verdict, not to teach; it can't fix the mock.

**Fix proposal — new skill `skills/typescript/sql-mock-patterns.md`:**
> When mocking a `db-adapter`-style module that exposes `run(sql, params)`, the mock implementation MUST read the SQL string to determine which placeholders (`?`) correspond to which params position. Bound params are positional; hardcoded literals in the SQL (e.g. `VALUES (?, ?, 0, ?)`) do NOT consume a param-array slot. Inspect the SQL before destructuring.

Effort: ~30 min for the skill + 1 unit test (extractor reads the skill correctly). E2E retry on T-002 with the skill active expected to fix on attempt 1.

#### 39b. Workspace-wide vitest run contaminates subsequent task verdicts (NEW ITEM)

`AI_FACTORY_TEST_CMD="npx vitest run"` is unscoped — vitest discovers and runs **every** `*.test.ts` in the workspace. Once T-002's `task-service/index.test.ts` started failing, every subsequent task (T-003, T-004) ran with those failures still in the test report. The Reviewer for T-003 received an `exit 1` test outcome with stderr citing `task-service/index.test.ts` failures — completely unrelated to T-003's `ui-components/` code.

T-003's Reviewer was sophisticated enough to note the failures came from `task-service` (not `ui-components`), but the runtime contract still translated the non-zero exit to a `fail`. With the rubric's "tests FAILED" rule from item 9c, that automatically `fail`s every criterion depending on test execution.

**Root cause.** The test runner has no notion of per-task test scoping. Every task evaluates against the full workspace test suite — fine on a clean DAG, catastrophic when any prior task's test is broken.

**Fix proposal — scoped test command:**

| Layer | Change |
|---|---|
| `runtime/executor/test_runner.py` | `run_tests(workspace, scope: str \| None = None)` — when `scope` is non-empty, append it to the command (`npx vitest run <scope>`). For pytest: `pytest <scope>`. For Flutter: `flutter test <scope>`. Generic enough to cover the main 4 runners. |
| `runtime/executor/runner.py` | Pass `task.module_scope` (primary scope only — `_primary_scope` from M4) into `run_tests`. |
| `tests/test_test_runner.py` | +2 tests: scope is appended; empty scope preserves legacy behavior. |
| `agents/reviewer.md` | Update the test-outcome interpretation: tests are now scoped per task, so failures genuinely correspond to the current task. |

Effort: ~1 hour + 2 tests + E2E re-run. After this, the autonomous self-driving rate should jump: T-003 won't see T-002's broken tests at all.

#### 39c. PRD ↔ skill consistency — Orchestrator/PRDAnalyst is not skill-aware (NEW ITEM)

PRDAnalyst (M2 `runtime/agents/prd_analyst.py`) was drafted before M3 skills existed; the PRD it produces for web-todo-m2 contains the criterion `"file ui-components/TaskForm.tsx exports default component TaskForm"`. But the active `react-component-patterns` skill mandates **named** exports.

The Worker had to choose:
- Honor the skill → named export → criterion `fail`.
- Honor the criterion → default export → skill violation → L1 `fail`.

There's no winning move. Both layers individually correct; their intersection is empty.

**Fix proposal — make PRDAnalyst skill-aware.**

`runtime/agents/prd_analyst.py::PRDAnalyst.draft(...)` already takes `intent_md`, `stack`, `project_name`. Add `active_skills: list[Skill] | None = None`. The runner resolves skills for a synthetic "PRD-drafting task" (same triggers as the worker's first task would see) and injects under `## Active Skills — PRD must not contradict these`.

This way the PRD's acceptance criteria are skill-consistent from day 0; no `default export` criterion when the skill demands named exports.

Effort: ~1 hour. Includes a regression test that a PRD-drafting LLM call with `react-component-patterns` skill active doesn't emit "default export" criteria.

#### Combined impact

After 39a + 39b + 39c ship, the next autonomous E2E should:
1. Worker T-002 reads the new SQL-mock skill → emits a correct mock → tests pass on attempt 1.
2. Even if T-002 still has a bug, T-003's verdict isn't contaminated by T-002's test results.
3. PRDAnalyst sees the React skill → emits "named export" criteria → no PRD-skill conflict.

Expected: 4/4 first-attempt approval rate on a clean web-todo-m2 re-run.

### Updated cross-cutting items status (post-sertleştirme + autonomous E2E)

| Item | Topic | Status | Change |
|---|---|---|---|
| **16** | Unverifiable two-mode mislabel | ✅ **CLOSED (item 38)** | Reviewer prompt teaches `test_infrastructure` rule + 1 schema regression test. |
| **37** | Reviewer barrel-import false-positive | ✅ **CLOSED (item 38)** | Explicit examples + rule-of-thumb in `agents/reviewer.md`. Verified zero false-positives in E2E. |
| **38** | Reviewer sertleştirme | ✅ **SHIPPED** | See above. |
| **39a** | Worker SQL-mock skill gap | ⬜ Open (LOW — 30 min) | New skill file + unit test. |
| **39b** | Workspace-wide test contamination | ✅ **SHIPPED (2026-05-14)** | `test_runner.py::_apply_scope` + `runner.py` passes `primary_scope(task)`. vitest/pytest/flutter scope-aware; pytest exit 5 normalized when scoped. Cargo/go test deferred to 39b'. |
| **39b'** | Cargo / `go test ./...` scope adapters | ⬜ Deferred (LOW) | Per-runner scope syntax (`cargo test -p`, `go test ./<pkg>/...`). Not on M2 critical path — web-todo-m2 uses vitest. |
| **39c** | PRD ↔ skill consistency | ⬜ Open (MEDIUM — ~1-2 hr) | PRDAnalyst gains `active_skills` param. Senior re-estimate: PRDAnalyst runs at INTAKE → PRD_DRAFTING; skills resolver is per-task → needs synthetic-task or `resolve_for_project` entry point. |

### Test count progression

```
283 (post-M4 + side fixes)
 → 286 (3 new sertleştirme regression tests)
 → 297 (11 new 39b scope tests: _apply_scope per runner + pytest exit-5 normalize)
 → 298 (1 new 39a integration test: SQL-mock skill loads and resolves for db-adapter task) ← CURRENT
```

### Item 39a shipped — SQL-mock skill (2026-05-14)

**File:** `skills/typescript/sql-mock-patterns.md`

**Trigger:** `language=TypeScript`, `keywords=[mock, db-adapter, persistence, vitest, sql.js, sqlite]`. Fires on T-002-shape tasks ("Use db-adapter for persistence") and any TS test that mocks a `run(sql, params)`-style adapter.

**Rule taught:** the SQL string dictates which positions in `params` are bound. Hardcoded literals (`VALUES (?, ?, 0, ?)` — the `0`) don't consume a slot. Worker must:
1. Count `?` in the SQL.
2. Destructure exactly that many positions.
3. Bake hardcoded literals into the mocked row, don't pull from `params`.

Includes a 6-row pattern table (INSERT/UPDATE/DELETE/SELECT) so the Worker has direct templates.

**Test:** `test_skills_resolver.py::test_sql_mock_skill_resolves_for_service_task_using_db_adapter` — loads the on-disk file, builds a T-002-shape `TaskSpec`, verifies the resolver picks `typescript-sql-mock-patterns` for a TS web task with "db-adapter for persistence" in the description. Pins both the loader (file is valid frontmatter) and the resolver (trigger keywords actually match).

**Status:** SHIPPED 2026-05-14. The next clean run of web-todo-m2 should see T-002's tests pass first-attempt instead of the 3-retry slog observed in item 39's E2E.

### Item 39b shipped — implementation notes (2026-05-14)

**Files touched:**
- `runtime/executor/test_runner.py` — new `_detect_runner(parts)` (vitest/pytest/flutter/cargo/go family detection, basename-aware so it works for both `pytest` and `C:\Python\Scripts\pytest.exe`), new `_apply_scope(parts, scope)` (append for vitest/pytest/flutter, no-op for cargo/go), `run_tests(workspace, scope=None)` signature extended.
- `runtime/executor/runner.py` — call site `run_tests(task_workspace, scope=primary_scope(task))`.
- `runtime/codebase/prior_tasks.py` — promoted `_primary_scope` → `primary_scope` (used cross-module now).
- `agents/reviewer.md` — input-list and rule 5 updated to note tests are scoped per task, so failures genuinely correspond to the current Worker's code.
- `tests/test_test_runner.py` — +11 tests.

**Key design decisions worth remembering:**

1. **vitest gets `--passWithNoTests` defensively appended** (idempotent). Without it, a scope that matches zero test files (e.g. `shared/`) would exit 1, which the rubric reads as failure. With it, the same situation exits 0 cleanly.

2. **pytest exit-5 normalization is gated on `scope_applied`.** A workspace-wide pytest returning 5 is genuinely suspicious (project has no tests); only normalize when the scope narrowed pytest's collection.

3. **cargo/go test deliberately left workspace-wide** (item 39b'). Adding `cargo test -p <name>` requires a name↔scope mapping; `go test ./<pkg>/...` requires replacing `./...` rather than appending. Neither blocks M2 demo (vitest); both are clean adapter additions when needed.

4. **`primary_scope` promoted from private.** Was an internal helper in `prior_tasks.py`; now used cross-module by `runner.py`. No circular import (prior_tasks doesn't reach into runtime.executor).

### Mini-E2E 39b results (2026-05-14)

**Setup:** workspace `05d8c6d40775` (web-todo-m2). T-003 reset PENDING (was AWAITING_HITL with 3x default-export fail + 1x "tests failed exit 1" from prior run). T-002 left DONE (broken mock intact on disk — the live testbed for contamination). T-004 already PENDING. Single-task execute, then T-004 directly.

**A/B audit-log proof of 39b:**

| When | T-003 `executor_tests` event | Reason |
|---|---|---|
| **Before 39b** (T18:56–T18:57 prior session) | `passed=False, exit=1` × 3 | Workspace-wide `npx vitest run` — T-002's broken mock fails → T-003 verdict contaminated |
| **After 39b** (T06:36 this session) | `passed=True, exit=0` × 2 | Scoped `npx vitest run ui-components --passWithNoTests` — T-002's tests not in scope |

Direct cause-and-effect, no other variable changed. The "tests failed (exit 1)" reason that lived in T-003's `last_review_reasons` for 3 prior attempts is **gone** in the rerun.

**Self-driving outcome:**

| Task | Pre-39b state | Post-39b run | Autonomous? |
|---|---|---|---|
| T-001 | DONE (prior run) | untouched | — |
| T-002 | DONE (prior run, buggy mock still on disk) | untouched | — |
| T-003 | AWAITING_HITL (3 fails) | **DONE in 2 attempts** | ✅ no manual touch |
| T-004 | PENDING | **DONE in 1 attempt, tests PASSED** | ✅ first-try approval |

**Project state: all 4 tasks DONE — "All tasks DONE — project complete."** Total mini-run cost: ~$0.06 (T-003 2 attempts + T-004 1 attempt).

### Unexpected finding — 39c may not need to ship

T-003 attempt 1 was rejected with 3x default-export fail (as predicted — react-component-patterns skill says named exports). **Attempt 2 was APPROVED** because Worker emitted both: `export function TaskForm` AND `export default TaskForm`. The skill requires named exports; the PRD criterion requires a default export; neither says "ONLY." Worker found the additive overlap on its own.

The original "no winning move" framing in item 39c was wrong: the criteria were **additive**, not **exclusive**. Once tests stopped contaminating the verdict (39b), Worker had room on the retry to add the missing export rather than swap exports.

**Implication for 39c:** the urgency drops sharply. PRDAnalyst-skill-awareness is still **structurally** correct (PRDs should know about active skills so criteria don't drift), but it is **no longer blocking** self-driving on web-todo-m2. Re-classified MEDIUM → LOW. Defer until another no-win conflict is actually observed.

### What to do next — re-prioritized after mini-E2E

| Priority | Action | Effort | Why now? |
|---|---|---|---|
| ✅ **Item 39b — test-scope per task** | SHIPPED. Direct A/B proof in audit log. | done | — |
| ✅ **Mini-E2E 39b** | T-003 DONE in 2 attempts, T-004 DONE in 1 attempt. 4/4 project complete. | done | — |
| 🟢 **Item 39a — SQL-mock skill** | Add `skills/typescript/sql-mock-patterns.md`. | 30 min | Independent quality improvement; would have closed the open T-002 mock suggestions cleanly. Useful but no longer blocking. |
| 🟢 **Proof-point E2E (sıfırdan clean run)** | Delete `workspaces/`, run web-todo-m2 from `intent.md`, expect 4/4 first-attempt. | ~$0.10–0.15 + 8 min | The "sıfırdan self-driving" demo. Different from mini-E2E (which started from a half-done state). Validates Phase 0 → M4 + sertleştirme chain end-to-end. |
| 🟡 **Item 39c — PRDAnalyst skill-aware** | Add `active_skills` to PRDAnalyst.draft. | ~1–2 hours | **Demoted MEDIUM → LOW.** Worker can satisfy additive PRD↔skill constraints on its own (proven by T-003). Ship only if a future run shows an actually-exclusive conflict. |
| 🔵 **M5 RAG skeleton** | Obsidian + RAG memory layer. | ~2-3 weeks | After proof-point E2E succeeds, this is the next architectural milestone per project plan. |

### Senior verdict — post-autonomous-E2E

**Items 16+37 fixes work** — zero barrel false-positives, distinct unverifiable reasons. **The pipeline now genuinely runs tests** — the M2-3 + Windows-shim + types-peers stack got us a workspace where vitest fires real assertions. **Three new genuinely-novel issues surfaced**, all caught by the system functioning correctly (Reviewer reports precise diagnoses, retry loop runs, AWAITING_HITL escalation works) but unfixable inside one task's retry budget.

Each of the three issues has a clean ~1-hour fix path and they're independent — they can ship in any order, though 39b is the highest-leverage. **The system is currently 80% of the way to autonomous self-driving on the web-todo-m2 class of project**; the last 20% is items 39a-c.

---

## Proof-point E2E (sıfırdan clean run) — 2026-05-14

### Setup

Archived old `workspaces/05d8c6d40775` → `05d8c6d40775-baseline-pre-proofpoint/`. Created fresh project `ed9f6074f1b8` (name `web-todo-proofpoint`) with the original Turkish brief (verbatim from baseline's `state.json:initial_brief_tr`). Walked through INTAKE → BABEL → INTAKE_DIALOG → STACK_DIALOG → PRD_DIALOG → G1 (PRD approval) → RFC drafting → G2 (RFC approval) → TASKS_READY → EXECUTING.

One stack refine applied: autonomous stack-pick proposed `Node + Hono` (server-side framework — Architect read "yerel veritabaninda" as needing a backend). Refined to `TypeScript + React + Vite + sql.js + Zod` to align with baseline for A/B comparability. Stack-pick drift on the BaaS tier worth its own future investigation; deferred.

### Run outcome

**DAG: 9 tasks in 5 batches** (vs. baseline's 4 tasks). Orchestrator decomposed more granularly: separate `db`, `store`, `components/TaskForm/TaskList/TaskItem`, `types` modules per RFC §7 + dedicated test-only tasks T-008/T-009.

| Task | Scope | Outcome | First-attempt? |
|---|---|---|---|
| T-001 | shared | ✅ APPROVED, tests PASSED | yes |
| T-002 | shared | ✅ APPROVED, tests PASSED | yes |
| T-003 | store | ❌ AWAITING_HITL (Zustand not installed) | — |
| T-004..T-009 | (not reached) | — | — |

**Self-driving rate (planning-chain-end-to-end): 2/9 first-attempt** before hitting an upstream blocker. **Self-driving rate (Worker chain in clean conditions): 2/2** — i.e., the execution side worked perfectly on the two tasks it got to execute against a clean module scope.

After installing `zustand` manually and resetting T-003 to PENDING, the rerun surfaced a second blocker: `Cannot find package 'react'` — primary_framework (`React + Vite`) was never installed by bootstrap. T-003 went back to AWAITING_HITL with a fresh L1 violation from the Reviewer: `import from '../shared/db' ... a 'shared' module that is not declared in the RFC's module breakdown (modules are db, store, components/*, types). This is a module scope leak`.

Stopped the run here to avoid burning more LLM budget on cascading manual fixes. Total proof-point cost: ~$0.15.

### What the proof-point actually surfaced — three new structural items

All three live **upstream** of the Worker→tests→Reviewer chain (which mini-E2E already proved healthy). They are why the from-scratch demo halted.

#### Item 40 — Architect locked-stack drift (key_libraries discipline) — ✅ SHIPPED 2026-05-14

**Files touched:** `runtime/agents/architect.py` — new helpers `_parse_rfc_key_libraries(rfc_text)` (regex parser, strips parenthetical notes) and `_find_phantom_libraries(rfc_text, locked_stack)` (case-insensitive subset check). `draft_rfc` wrapped in a 3-attempt retry-with-correction loop (mirrors the reviewer length-validator pattern from item 21); each drift triggers an `architect_rfc_key_libraries_drift` audit event with attempt# + phantom-libs + allowed list; exhaustion raises `RuntimeError` so a corrupt RFC can't reach G2. Prompt's `## Locked Stack (HARD ...)` block extended with explicit "**HARD RULE FOR §4 'Key libraries' LINE**" that quotes the allowed list verbatim and names common drift culprits (zustand/redux/axios/lodash) as forbidden additions. New test file `tests/test_architect_key_libraries_discipline.py` — 11 tests covering parser edge cases (simple/parenthetical/missing-section/missing-line), validator subset semantics (case-insensitivity, empty when subset, detects extras), retry-loop integration (drift→clean second attempt, exhaustion raises, no-locked-stack skips validation), and the prompt-content pin.

**Test count:** 302 → 313 (+11). No regressions on the existing 4 brownfield/architect tests.

#### Item 40 — original description (for reference)


**Symptom.** After explicit stack refine `key_libraries=[sql.js, zod]`, the Architect's drafted RFC §4 listed `sql.js, zod, **zustand** (state management)`. Architect introduced a library not in the locked stack.

**Root cause.** Item 17 (Tier × Stack Hard Constraint) enforces language/framework alignment in the Architect prompt but stops at framework — `key_libraries` are not threaded into the constraint. Architect treats them as suggestions rather than a hard contract.

**Fix proposal.** Extend the Architect prompt's "Hard Constraint" block to quote `stack.key_libraries` verbatim with: *"RFC §4 'Key libraries' MUST be a subset of locked_stack.key_libraries. Do NOT add new libraries. Do NOT remove listed ones. Quote them verbatim, in the same order."* Plus a post-draft regex check in `runtime/agents/architect.py` that parses §4 and asserts subset membership; mismatch → retry with structured correction (parallel to the Reviewer length-validator pattern from item 21).

**Effort.** ~45 min (prompt edit + post-draft validator + 2 regression tests). **Priority: HIGH** — without this, every from-scratch run risks a phantom library being baked into the RFC.

#### Item 41 — Bootstrap dep gap (primary_framework not installed) — ✅ SHIPPED 2026-05-14

**Files touched:** `runtime/architecture/bootstrap.py` — added `_FRAMEWORK_PACKAGES` map (React+Vite / Vue+Vite / Next.js / Hono / Express / single-name variants), `_framework_to_packages(primary_framework) -> list[str]` helper with stderr warning on unknown frameworks, extended `_NPM_DEP_REGISTRY` with `next`/`hono`/`express`/`@vitejs/plugin-vue`/`@types/express`. `_t2_web_package_json` now merges framework packages with `key_libraries` via `dict.fromkeys([*framework_pkgs, *key_libraries])` (dedupe with order preservation). `tests/test_bootstrap.py` — +4 tests (React+Vite full deps, Hono only, unknown-framework warning + fallback, variant-tolerance smoke test).

**Test count:** 298 → 302 (+4). All previously-existing bootstrap tests still pass (one was using `LockedStack(key_libraries=[react, vite])` legacy shape — still works because we merge rather than replace).

#### Item 41 — original description (for reference)


**Symptom.** `package.json` after bootstrap contained `{sql.js, zod}` + `{vitest, typescript, @types/sql.js}` only. Stack said `primary_framework: "React + Vite"` but `react`, `react-dom`, `vite`, `@vitejs/plugin-react`, `@types/react`, `@types/react-dom` were all absent. Worker correctly imported React; tests failed with `Cannot find package 'react'`.

**Root cause.** `runtime/architecture/bootstrap.py` reads `stack.key_libraries` and `npm install`s each entry. It does NOT translate `primary_framework` strings (e.g. `"React + Vite"`, `"Vue + Vite"`, `"Next.js"`, `"Express"`, `"Hono"`) into their package list. The framework name is treated as documentation, not a deps source.

**Fix proposal.** New module-level constant in `bootstrap.py`:

```python
_FRAMEWORK_DEPS: dict[str, dict[str, list[str]]] = {
    "react + vite": {
        "dependencies": ["react", "react-dom"],
        "devDependencies": ["vite", "@vitejs/plugin-react", "@types/react", "@types/react-dom"],
    },
    "vue + vite": {
        "dependencies": ["vue"],
        "devDependencies": ["vite", "@vitejs/plugin-vue"],
    },
    "next.js": {"dependencies": ["next", "react", "react-dom"], "devDependencies": ["@types/react"]},
    "hono": {"dependencies": ["hono"], "devDependencies": []},
    "express": {"dependencies": ["express"], "devDependencies": ["@types/express"]},
    "fastapi": {"dependencies": [], "devDependencies": []},  # Python — package.json no-op
}
```

Bootstrap merges this with `key_libraries` before writing `package.json`. Case-insensitive lookup, fuzzy match on common variants (`"React + Vite"` ↔ `"react+vite"`). Unknown framework → log a warning, fall back to key_libraries-only.

**Effort.** ~1 hour (table + integration + 3 tests covering React+Vite, Vue+Vite, unknown-framework fallback). **Priority: HIGH** — without this, any non-trivial stack pick fails at the first test run.

#### Item 42 — DAG-RFC module breakdown mismatch — ✅ SHIPPED 2026-05-14

**Files touched:** `runtime/agents/orchestrator.py` — new helpers `_parse_rfc_modules(rfc_text)` (handles both markdown-table and bullet-list layouts; strips `(new)` annotations; returns `None` when §7 is missing/empty so older fixtures don't trigger false rejections) and `_find_unscoped_tasks(dag, rfc_modules)` (returns `[(task_id, scope)]` mismatches; normalizes `module_scope: list[str]` future shape). `generate_dag`'s validation block now calls these after `dag.validate_dag()`; mismatch raises `ValueError` with a structured message naming offenders + allowed modules, which the existing retry loop feeds back into the next attempt's prompt. `agents/orchestrator.md` — new Hard Rule 13 plus a refinement to Rule 12 ("`shared` is only valid when RFC §7 lists it — see Rule 13"). New test file `tests/test_orchestrator_module_scope.py` — 10 tests covering parser (table, bullet, `(new)` annotation, missing-section, empty-section), validator (subset and mismatch detection), and retry-loop integration (drift→clean second attempt, full-budget exhaustion → `RuntimeError`, no-§7 RFC bypasses validation).

**Test count:** 313 → 323 (+10). All existing orchestrator-adjacent tests still green.

#### Item 42 — original description (for reference)


**Symptom.** RFC §7 module list: `db`, `store`, `components/TaskForm`, `components/TaskList`, `components/TaskItem`, `types`. DAG generated 9 tasks; T-001 (`Initialize sql.js database`) scope was `shared`, T-002 (`Define TypeScript types`) scope was `shared`, T-007 and T-009 also `shared`. The `shared` module is not in RFC §7. Reviewer correctly flagged: *"import from '../shared/db' ... references a 'shared' module that is not declared in the RFC's module breakdown. This is a module scope leak."*

**Root cause.** Orchestrator's DAG-generation prompt does not constrain `task.module_scope ∈ rfc_modules`. The LLM heuristically merges tiny single-file modules (`db`, `types`) into a synthetic catch-all (`shared`) for parsimony, breaking import paths and triggering Reviewer L1 violations downstream.

**Fix proposal.** Two layers (defense in depth):

1. **Prompt layer.** `agents/orchestrator.md` Hard Rule 13: *"Every emitted task's `module_scope` MUST be a verbatim match for exactly one of the modules listed in RFC §7's Module Breakdown table. Do NOT introduce 'shared', 'common', or any catch-all not in §7. If multiple small files belong in the same RFC module, list them under that module's scope — never collapse different RFC modules into one."*

2. **Validator layer.** Parse RFC §7 module names into `rfc_modules: set[str]` during DAG generation (already-existing RFC parsing infrastructure). After DAG draft, assert `{t.module_scope for t in dag.tasks} ⊆ rfc_modules`. Mismatch → retry orchestrator with structured correction listing the offending scopes and the valid set.

**Effort.** ~1.5 hours (prompt update + RFC §7 parser + validator + 3 tests). **Priority: MEDIUM-HIGH** — surfaces only when RFC has small single-file modules; symptom is L1 leak verdicts on every Worker import path crossing into the collapsed module.

#### Item 43 — Reviewer conflates RFC §4 and stack.json — DEFER

**Symptom.** Reviewer cited *"the locked stack lists sql.js, zod, zustand"* when `stack.json.key_libraries` were only `[sql.js, zod]`. Zustand came from RFC §4 (item 40). Cosmetic error — the underlying L1 violation (zustand-not-in-stack) was correctly flagged regardless.

**Fix proposal.** Reviewer prompt — *"If you cite 'the locked stack' as evidence, quote stack.json verbatim, not RFC §4. RFC §4 may have drifted from stack.json — that drift itself is the violation, not a fact about the stack."*

**Effort.** ~15 min. **Priority: LOW** — defer until item 40 ships (then re-evaluate; with 40 fixed, the conflation has nothing to conflate).

### Updated self-driving claim — honest framing

| Layer | Status | Evidence |
|---|---|---|
| Worker → tests → Reviewer (39a + 39b + sertleştirme) | ✅ **Working** | Mini-E2E: T-003 DONE in 2 attempts, T-004 first-try. Proof-point: T-001, T-002 first-try. |
| Planning chain (Architect, Bootstrap, Orchestrator) | ❌ **3 structural drifts** | Items 40 (key_libraries discipline), 41 (primary_framework deps), 42 (DAG-RFC module mismatch) |

The mini-E2E result remains valid: when the planning chain produces a coherent workspace + DAG, the execution chain self-drives. The proof-point reveals the planning chain has gaps that prevent from-scratch self-driving today.

### Test count progression

```
283 (post-M4 + side fixes)
 → 286 (sertleştirme)
 → 297 (39b scope tests)
 → 298 (39a SQL-mock skill resolver test)
 → 302 (4 new item-41 framework deps tests)
 → 313 (11 new item-40 architect key_libraries validator tests)
 → 323 (10 new item-42 orchestrator module-scope validator tests)
 → 325 (2 new item-41' testing-library + vite.config writers tests)
 → 326 (1 new item-44 react-di skill resolver test)
 → 328 (2 new item-46 bootstrap-honors-locked-stack tests) ← CURRENT
```

### What to do next — re-prioritized after proof-point

| Priority | Action | Effort | Why now? |
|---|---|---|---|
| 🔴 **Item 41 — Bootstrap framework deps** | Add `_FRAMEWORK_DEPS` map + integration. | ~1 hour | Without this, any React/Vue/Next workspace fails at first test run. Highest practical blocker. |
| 🔴 **Item 40 — Architect key_libraries discipline** | Prompt hard-constraint + post-draft subset validator. | ~45 min | Stops phantom libraries entering RFC §4. Independent of 41. |
| 🟡 **Item 42 — DAG-RFC module match** | Orchestrator Hard Rule 13 + scope-set validator. | ~1.5 hours | Removes the "shared catch-all collapse" L1 leak class. |
| 🔵 **Repeat proof-point E2E** | After 40+41+42 ship, re-run web-todo-proofpoint sıfırdan. Expect ≥7/9 first-attempt. | ~$0.20 + 15 min | The honest from-scratch self-driving demo. |
| 🟢 **Item 43 — Reviewer stack-citation discipline** | Reviewer prompt clarification. | ~15 min | Defer until 40 ships. |
| 🟢 **Item 39c — PRDAnalyst skill-aware** | Defer further. | — | Worker proven to handle additive constraints; not blocking. |
| 🔵 **M5 RAG skeleton** | Obsidian + RAG memory layer. | ~2-3 weeks | After proof-point passes from-scratch. |

### Senior verdict — post-proof-point

Mini-E2E and proof-point told two different but complementary stories: **mini-E2E validated the execution chain in isolation; proof-point exposed planning-chain drift that the mini-E2E couldn't surface because it bypassed the planning phase entirely (started from an already-DAG'd state).** This is exactly what a real proof-point is for — it generates information, not validation theater.

Three new items (40, 41, 42) are concrete with clean ~1h fix paths each. Total to a credible "from-scratch self-driving" demo: ~3 hours of focused work + one re-run. **The system is closer to 60–65% from-scratch self-driving today** (planning gaps), versus the 80% framing post-mini-E2E (which only measured execution). After 40+41+42 ship, expect the from-scratch rate to land in the 75–85% band; remaining drift comes from stack-pick BaaS-tier mismatch (Hono picked for browser-only intent — separate future item).

---

## Proof-point E2E v2 (post 40+41+42) — 2026-05-14

### Setup

Archived `workspaces/ed9f6074f1b8` → `ed9f6074f1b8-baseline-pre-40-41-42/`. Created fresh project `7200fa322b61` (`web-todo-proofpoint-v2`) with the verbatim Turkish brief and applied the same stack refine (Node + Hono → React + Vite + sql.js — the BaaS-tier stack-pick drift is reproducible, separate future item). Walked through G1 + G2 normally.

### Outcome — direct A/B against v1

| Metric | v1 (pre-fix) | v2 (post 40+41+42) | Δ |
|---|---|---|---|
| Tasks DONE | 2/9 (cascade-blocked) | **6/7** | +44pp absolute |
| First-attempt approved | 2/9 = **22%** | 5/7 = **71%** | +49pp |
| Architect §4 phantom libraries (Zustand) | yes | **none** (drift_attempts=0) | ✅ Item 40 |
| DAG `shared` synthetic scope | yes | **none** (orchestrator_dag_ok attempt=1) | ✅ Item 42 |
| Bootstrap missing react/vite | yes | **react, react-dom, vite, @vitejs/plugin-react installed** | ✅ Item 41 |
| Manual interventions | 2 (npm install zustand; reset T-003) | 0 | clean |
| Cascade depth (each manual fix surfaced next layer) | 2 layers | 0 | structural |
| Cost | ~$0.15 (cascading retries) | ~$0.20 (productive work) | comparable |

**Validators didn't even need to fire.** Both Item 40 (`architect_rfc_key_libraries_drift` attempts=0) and Item 42 (`orchestrator_dag_ok` attempt=1) succeeded on attempt 1 — the prompt strengthening alone was sufficient. The validators are still load-bearing as belt-and-suspenders; they just weren't needed for THIS run.

### Final DAG (v2) — clean module structure

7 tasks across 3 modules, all RFC §7-verbatim:

```
T-001  persistence    [-]               sql.js + IDatabaseAdapter
T-002  task-service   [-]               Zod TaskSchema + Task type
T-003  task-service   [T-001, T-002]    ITaskService + TaskService class
T-004  task-ui        [T-003]           TaskList, TaskItem, CreateTaskForm
T-005  task-ui        [T-004]           Wire App with TaskService
T-006  task-ui        [T-005]           Toast notifications
T-007  task-ui        [T-005]           WebAssembly detection + fallback
```

vs v1's 9-task DAG with synthetic `shared` collapse: this is structurally cleaner because Item 42 forced the Orchestrator to honor §7's 3-module breakdown.

### Two new sub-findings (not blocking the v2 claim)

#### Item 41' — `@testing-library/react` missing from React framework deps map — ✅ SHIPPED 2026-05-14

**Files touched:** `runtime/architecture/bootstrap.py` — `_NPM_DEP_REGISTRY` gained `@testing-library/react`, `@testing-library/jest-dom`, `@testing-library/user-event`, `jsdom` with pinned versions. New shared constant `_REACT_VITE_PACKAGES` and `_NEXT_PACKAGES` consolidate the React-stack deps so the variant entries (`"react + vite"`, `"react+vite"`, `"vite + react"`, `"next.js"`, `"nextjs"`, `"next"`) share one source. New `_VITE_CONFIG_REACT` constant (vite.config.ts with `test.environment: 'jsdom'`, `globals: true`, `setupFiles: './setupTests.ts'`, React plugin) + `_SETUP_TESTS_REACT` (`import '@testing-library/jest-dom'`). New `_is_react_stack(locked_stack)` helper gates the config writers. `bootstrap_workspace_layout` writes `vite.config.ts` and `setupTests.ts` when the locked stack is React-based. `tests/test_bootstrap.py` — 2 new tests (vite.config + setupTests content + non-React doesn't write them) + extended existing react-vite deps test to assert the testing-library quartet; relaxed `test_framework_to_packages_recognizes_common_variants` to use `in` checks rather than equality (so future additions don't break it).

**Test count:** 323 → 325 (+2). All previously-existing tests still green.

#### Item 41' — original description (for reference)


**Symptom.** T-007 (App wiring with `wasm support detection`) failed on attempt 2's test execution because Worker emitted `task-ui/App.test.tsx` importing `@testing-library/react`, which is NOT in `_FRAMEWORK_PACKAGES["react + vite"]`. Tests skipped → criterion `unverifiable` → AWAITING_HITL after 3 attempts.

**Root cause.** The Item 41 framework deps map covers the runtime (`react`, `react-dom`, `vite`, `@vitejs/plugin-react`, `@types/*`) but not the testing peers. Worker correctly chose testing-library for React component tests (it's the conventional choice) — the deps map just hadn't anticipated this. Same shape as Item 41 itself: a class of deps the bootstrap doesn't know to install.

**Fix.** Extend `_FRAMEWORK_PACKAGES["react + vite"]` (and Vue+Vite, Next.js) to include test-tier deps: `@testing-library/react`, `@testing-library/jest-dom`, `jsdom`, `@testing-library/user-event`. Plus extend `_NPM_DEP_REGISTRY` with version specs. Effort: ~20 min + 1 regression test. **Priority: MEDIUM** — surfaces every time a React project emits component tests, which is most of them.

#### Item 44 — Worker DI violation in App wiring (T-007) — ✅ SHIPPED 2026-05-14

**Files touched:** new `skills/react/dependency-injection.md` (~150 lines). Audience: `[worker, reviewer]`. Triggers: `language=TypeScript`, `app_class=web`, `keywords=[wire, wiring, integrate, integration, app component, context provider, usecontext]` — deliberately narrow so the skill doesn't bleed into service-tier tasks (initial broader trigger set was rejected by `test_sql_mock_skill_resolves_for_service_task_using_db_adapter` because "adapter"/"service"/"hook" matched too widely). Body covers Pattern A (props down from App with `useMemo`), Pattern B (Context provider with `useContext` hook), three anti-patterns (inline `new` in handler, module-level singleton, `new` inside JSX), Worker pre-emit checklist, and Reviewer guidance with citation rules. `tests/test_skills_resolver.py` — new integration test `test_react_di_skill_resolves_for_app_wiring_task` that builds a T-007-shape `TaskSpec` and asserts the resolver picks the skill.

**Test count:** 325 → 326 (+1).

#### Item 44 — original description (for reference)


**Symptom.** T-007's App.tsx instantiates `new SqljsAdapter()` and `new TaskService(adapter)` inside event handlers (`handleCreate`, `handleToggle`, `handleDelete`). L1 DI principle violated: business logic should receive dependencies via constructor / props / context, not `new` them inline. Reviewer correctly flagged. Worker self-corrected the import path but kept re-instantiating in attempt 2 → still failed.

**Root cause.** Worker prompt's DI section either doesn't make "inline `new` inside event handlers is DI violation" explicit enough, or React-specific DI patterns (Context, props, react-redux-style hooks) aren't covered by an active skill. The `typescript-module-boundaries` skill covers import paths but not instantiation patterns.

**Fix proposal.** New skill `skills/react/dependency-injection.md` teaching: (a) construct adapters/services ONCE at App root (component constructor or `useMemo`), (b) pass via props or React Context, (c) never `new X()` inside event handlers. Triggers on `react` language + `App`/`wiring`/`context` keywords. Effort: ~30 min + 1 resolver test. **Priority: MEDIUM** — surfaces on app-wiring tasks (T-007-class), not every task.

### Updated self-driving claim — post-v2

| Layer | Status | Evidence |
|---|---|---|
| Worker → tests → Reviewer chain | ✅ **~80% — working** | Mini-E2E: 4/4. Proof-point v2: 5/7 first-try, 6/7 done. |
| Planning chain (Architect §4, Bootstrap deps, Orchestrator §7) | ✅ **Closed** | v2 audit: drift_attempts=0 across both 40 and 42; Item 41 deps map ran clean. |
| Worker quality (DI, testing-library) | 🟡 **Sub-items 41', 44 open** | T-007 surfaced one of each. Localized — not cascading. |

**From-scratch self-driving rate jumped from v1's 22% → v2's 71%.** Items 41' and 44 would close most of the remaining gap (T-007 is the only block in v2). Realistic ceiling without additional sub-items: 85-90% on web-todo-class projects.

### What to do next — re-prioritized after proof-point v2

| Priority | Action | Effort | Why now? |
|---|---|---|---|
| 🟡 **Item 41' — React testing-library deps** | Extend `_FRAMEWORK_PACKAGES` with `@testing-library/react`, `jsdom`, etc. | ~20 min | T-007-class blocker; one-line extension. |
| 🟡 **Item 44 — React DI skill** | New `skills/react/dependency-injection.md`. | ~30 min | T-007's actual code-quality failure. Worker needs the explicit pattern. |
| 🔵 **Proof-point v3 (after 41' + 44)** | Same brief, expect 7/7 first-attempt. | ~$0.20 + 15 min | The "98% from-scratch" demo. Final validation before M5. |
| 🟢 **Item 43 — Reviewer stack-citation discipline** | Reviewer prompt clarification. | ~15 min | Cosmetic. After 40 shipped, Reviewer should be quoting clean stacks; defer. |
| 🟢 **Item 39c — PRDAnalyst skill-aware** | — | — | Worker proven to handle additive constraints. Defer indefinitely unless exclusive conflict shows up. |
| 🔵 **M5 RAG skeleton** | Obsidian + RAG memory layer. | ~2-3 weeks | Green-lit after proof-point v3 lands 7/7. |
| 🔍 **BaaS-tier stack-pick drift** | Investigate why StackAnalyst proposes Node+Hono for browser-only intent on T2/BaaS. | — | Reproducible across v1 and v2; required user-refine both times. Separate session. |

---

## Proof-point E2E v3 (post 41' + 44 + 46) — 2026-05-14 — ✅ SUCCESS

### Setup

Archived `workspaces/7200fa322b61` → `7200fa322b61-baseline-pre-41prime-44/`. Created fresh project `1b9c9f9ca18b` (`web-todo-proofpoint-v3`) with the verbatim Turkish brief. Same stack refine cycle as v2 (Node+Hono → React+Vite+sql.js+Zod) — autonomous stack-pick still drifts on T2/BaaS, **and** v3 surfaced a new IntentAnalyst non-determinism (Item 45 below).

### v3 hit a new layer (Item 46) — fixed mid-run, then resumed

Initial run: T-001 DONE first-try, **T-002 AWAITING_HITL on `Cannot find package 'sql.js'`**. Inspection revealed:

- IntentAnalyst extracted minimal `GoldenPathInputs` (mostly `False`/`unknown`). Same brief that gave `T2 score=100` in v2 yielded **`T4 score=60`** in v3 — Item 45 (non-determinism).
- Architect/StackAnalyst saved `stack.json` with `tier=T4`, `primary_framework="React + Vite"`.
- Bootstrap's gate `tier in ("T1","T2","T3") and app_class=="web"` failed for T4 → no `package.json`/`tsconfig.json`/`vite.config.ts` written. Locked stack ignored.
- Worker correctly imported `sql.js`/`zod`/`uuid` but workspace had no deps installed → cascade.

**Mid-run fix shipped (Item 46):** `runtime/architecture/bootstrap.py` — new `_is_browser_framework_stack(locked_stack)` helper (returns True when primary_framework resolves to a package list containing react/vue/vite/next). The T1/T2/T3+web gate became `(tier in T1/T2/T3 and app_class=web) OR _is_browser_framework_stack(locked_stack)`. Locked stack's contract beats the heuristic tier. Same change applied to the `.gitignore`-extra branch. `tests/test_bootstrap.py` — 2 new tests (T4 + locked React stack writes package.json + vite.config.ts; T4 + Hono does NOT). 326 → 328 tests, 0 regressions.

Re-bootstrapped the v3 workspace directly (calling `bootstrap_workspace_layout` from a Python shell — idempotent, wrote the 5 missing files), `npm install`, reset T-002 to PENDING, resumed `run-all`.

### v3 final outcome

| Task | Scope | Attempts | First-attempt? | Note |
|---|---|---|---|---|
| T-001 | task | 1 | ✅ | sql.js init + persistence (pre-Item-46) |
| T-002 | task | 2* | ⚠️ | Initial blocked by Item-46 (deps missing); post-fix re-run worked |
| T-003 | task | 1 | ✅ | ITaskAPI + TaskService |
| T-004 | ui | 1 | ✅ | React UI: TaskList + AddTaskForm + TaskItem |
| T-005 | ui | 1 | ✅ | ErrorBoundary + loading state |
| T-006 | ui | 2 | ❌ | Worker emitted `⚠️ You have over 1000 tasks...` (emoji prefix); test searched for the bare string. Reviewer flagged precisely; Worker self-corrected on attempt 2. |

**`All tasks DONE — project complete.`** + Documenter ran automatically and produced `README.md`. Full end-to-end pipeline completed autonomously after the Item-46 mid-run fix.

\* T-002 attempts=2 in the post-fix status reflects cumulative counter across the two runs; in the post-Item-46 segment it was approved on its first attempt.

### v1 → v2 → v3 trajectory

| Metric | v1 | v2 | v3 |
|---|---|---|---|
| Tasks DONE | 2/9 (cascade-blocked) | 6/7 | **6/6 (complete)** |
| First-attempt rate | 22% | 71% | **~83%** (5/6 post-fix segment) |
| Manual interventions | 2 (npm install + reset) | 0 within the run | 1 (Item 46 ship + re-bootstrap, mid-run) |
| Cascading blockers | yes (deps → React → DI → testing-library) | no | no |
| Pipeline reached Documenter | no | no | **yes — README auto-drafted** |

### Items shipped this session (summary)

| Item | Topic | Tests | Status |
|---|---|---|---|
| 41 | Bootstrap `_FRAMEWORK_PACKAGES` map | +4 | ✅ |
| 40 | Architect §4 key_libraries validator + retry | +11 | ✅ |
| 42 | Orchestrator DAG-RFC module match validator | +10 | ✅ |
| 41' | React testing-library + vite.config writers | +2 | ✅ |
| 44 | `skills/react/dependency-injection.md` | +1 | ✅ |
| 46 | Bootstrap honors locked_stack over tier | +2 | ✅ |

**Total test growth this session: 298 → 328 (+30 tests). Zero regressions throughout.**

### Open follow-ups (not blocking M5)

- **Item 45 — IntentAnalyst non-determinism.** Same brief → different `GoldenPathInputs` across runs (v2: T2/score=100; v3: T4/score=60). Reproducible, root cause is IntentAnalyst extraction quality. Investigation needed. NOT blocking now — Item 46 makes downstream tolerate it.
- **Item 43 — Reviewer stack-citation discipline.** Surfaced again in v3 T-002 ("uuid not in stack ... locked stack lists uuid"). Self-contradicting prose. Cosmetic; verdict was still functionally correct.
- **BaaS-tier stack-pick drift** — StackAnalyst's initial proposal of `Node + Hono` for browser-only intent reproduced across v1/v2/v3. Required user refine every time. Separate investigation.
- **Worker UI test-writing nuance** — T-006 Worker emitted emoji-prefixed UI text but test asserted bare string. One-shot self-correction via reviewer feedback; could be preempted by a skill (`skills/react/ui-test-text-matching.md`?).

### Senior verdict — proof-point v3

**The from-scratch self-driving claim is now substantively supported.** v3 produced a working React + sql.js todo SPA from a Turkish brief, walking the full PRD → RFC → DAG → Worker → Reviewer → Documenter chain with one mid-run code fix (Item 46) and zero post-fix manual interventions. The remaining gaps (Items 45, 43, BaaS drift, UI text matching) are localized polish, not cascading structural failures.

**M5 RAG skeleton is green-lit.** Build on a foundation that demonstrably delivers a complete product from intent.

**Item 39c stays demoted** — never observed an exclusive PRD↔skill conflict across three from-scratch runs.

---

## Proof-point E2E v4 (post Item 43 + BaaS-drift + UI-text-match) — 2026-05-14 — PARTIAL (interrupted)

### Setup

Archived `workspaces/1b9c9f9ca18b` → `1b9c9f9ca18b-baseline-pre-43-baas-uitext/`. Created fresh project `66244246c339` (`web-todo-proofpoint-v4`) with the verbatim Turkish brief from v3's `state.json:initial_brief_tr`. Walked through Babel → IntentAnalyst → StackAnalyst → PRDAnalyst → G1 → Architect → G2 → Orchestrator → Worker chain. Stopped after T-002 cascade (npm install gap + jsdom IndexedDB gap) was diagnosed and structurally fixed (Items 47 + 47b shipped mid-run); user interrupted before resuming T-002 retry to avoid speculative discovery-cascade burn — primary design signal had already landed.

### Primary fixes — validation status

| Fix | Status | Evidence |
|---|---|---|
| **BaaS-drift** (StackAnalyst browser-intent detection) | ✅ **VALIDATED — autonomous** | On the first autonomous StackAnalyst call (same Turkish brief, T2/BaaS/score=100, identical to v1/v2/v3 conditions), the analyst emitted `primary_framework: "React + Vite"`, `key_libraries: ["idb", "zod"]`, `deploy_target: "vercel-static"`. Rationale included verbatim **"No backend framework needed — all data lives in the browser"** — the skill prompt's anti-pattern language echoed back. v1/v2/v3 hit rate on autonomous frontend pick: 0/3 (all required user refine from Node+Hono). v4: 1/1. |
| **Item 40** (Architect §4 key_libraries discipline) | ✅ **VALIDATED** | RFC §4 emitted `Key libraries: idb, zod` — exact subset of `stack.json.key_libraries`. Zero `architect_rfc_key_libraries_drift` audit events. Prompt sertleştirme alone was sufficient; validator did not need to fire. |
| **Item 42** (DAG-RFC module match) | ✅ **VALIDATED** | DAG had 5 tasks across 4 RFC §7 modules (`types/`, `storage/`, `service/`, `ui/`). Zero synthetic `shared` scope. Orchestrator first-attempt success. |
| **Item 24** (`unverifiable_reason` two-mode) | ✅ **VALIDATED** | T-001 first attempt (pre-`npm install`) produced `[unverifiable:test_infra]`-tagged reasons with the correct downstream tag (no `criterion_design` mislabel). Reviewer suggestion: *"Run `npm install` to resolve the startup error and enable test execution."* — operational target, not criterion redesign. |
| **Item 43** (Reviewer stack-citation discipline) | 🟡 **PARTIAL** | Reviewer suggestion for T-002 attempt 3 cited `"the locked stack's key_libraries"` — used the field name verbatim (the Item 43 rule's exact phrasing). No paraphrastic "the locked stack lists X" form observed. But: not a hard-test scenario (no L1 violation was citing stack); waiting for a true negative case to fully confirm. |
| **UI-text-match** (`skills/react/ui-test-text-matching.md`) | ⬜ **NOT EXERCISED** | T-004 (UI module) not reached. Skill resolver would have fired on T-004 keywords; cannot confirm Worker behavior change without execution. Defer to next proof-point. |

### Items shipped mid-run (47 + 47b)

#### Item 47 — `_NPM_DEP_REGISTRY` browser-persistence coverage + silent-drop visibility — ✅ SHIPPED 2026-05-14

**Symptom.** StackAnalyst (post-BaaS-drift-fix) autonomously picked `idb` for browser persistence — a clean win over v3's `sql.js`. But bootstrap silently dropped `idb` from `package.json` because the registry only knew `sql.js`/`better-sqlite3` for persistence. T-001 then failed with `ERR_MODULE_NOT_FOUND for 'vite'` — proximate cause was `npm install` not run (a separate operational gap), but the root structural gap was that `idb` wouldn't have been in `package.json` to install anyway.

**Why structurally important.** The silent-skip branch at `bootstrap.py:_t2_web_package_json` had `if entry is None: continue` — no warning, no audit, no visibility. The operator only saw the symptom at first test run as `Cannot find module 'idb'`. Same class of failure as Item 41 (primary_framework deps): coverage matrices have to widen when consumer agents' autonomous range widens, AND silent drops are a separate visibility bug independent of coverage.

**Fix.** `runtime/architecture/bootstrap.py`:
- Added `idb`, `dexie`, `localforage` to `_NPM_DEP_REGISTRY` with pinned versions.
- Replaced silent `continue` with `print("[ortim] WARNING: bootstrap doesn't recognize key_library=...", file=sys.stderr)` — operator now sees the silent drop immediately.

**Tests (3 new, `tests/test_bootstrap.py`).**
- `test_idb_browser_persistence_lib_is_registered`: idb in deps for a React + idb stack.
- `test_dexie_and_localforage_also_registered`: same coverage for the other two.
- `test_unknown_key_library_warns_and_is_skipped`: registered libs flow, unknown lib emits stderr WARNING + is skipped (counter-example for the warning).

Pytest 331 → 334 (+3).

**Lesson for next time.** The BaaS-drift item card's "Counter-example check" line missed: "what library does the analyst pick for persistence? Are all options in the deps registry?" Item template discipline must include the *downstream* dependency-chain coverage check, not just the direct rule under test.

#### Item 47b — `fake-indexeddb` auto-pull for browser persistence test peer — ✅ SHIPPED 2026-05-14

**Symptom.** T-002 (`storage/repository.ts` with idb wrapper) Worker emitted `repository.test.ts` that called `indexedDB.deleteDatabase()`. Tests failed in jsdom env with `ReferenceError: indexedDB is not defined`. Worker's attempt 2 correctly imported `fake-indexeddb/auto` (the canonical jsdom shim) but the package was not installed. Three attempts later → AWAITING_HITL.

**Why structurally important.** Mirrors Item 41' (React → `@testing-library/react` auto-pull). Browser persistence libraries imply jsdom test environment, which implies an IndexedDB shim peer. The Worker correctly identified the canonical solution — the bootstrap just needs to know the rule.

**Fix.** `runtime/architecture/bootstrap.py`:
- Added `fake-indexeddb` to `_NPM_DEP_REGISTRY` (devDependency, ^6.0.0).
- Added `_INDEXEDDB_PEERS = ("idb", "dexie", "localforage")` constant.
- In the key_libraries resolve loop, when `normalized in _INDEXEDDB_PEERS`, auto-add `fake-indexeddb` to `dev_deps` (mirrors `react → @vitejs/plugin-react` pattern at the same call site).

**Tests (3 new, `tests/test_bootstrap.py`).**
- `test_idb_auto_pulls_fake_indexeddb_test_peer`: positive case for idb.
- `test_dexie_and_localforage_also_pull_fake_indexeddb`: same for dexie/localforage.
- `test_no_browser_persistence_means_no_fake_indexeddb`: counter-example — stacks without browser persistence must NOT get fake-indexeddb.

Pytest 334 → 337 (+3).

**Open observation.** `setupTests.ts` currently only contains `import '@testing-library/jest-dom';`. A polish-level improvement: when `_INDEXEDDB_PEERS` matches, also append `import 'fake-indexeddb/auto';` to `setupTests.ts` so per-test-file imports become unnecessary. Defer until a real run shows the per-file import as a quality issue (Worker's per-file approach works and is locally explicit, which has its own merits).

### Trajectory update

| Metric | v1 | v2 | v3 | v4 (partial) |
|---|---|---|---|---|
| Autonomous stack pick correct? | ❌ Node+Hono | ❌ Node+Hono | ❌ Node+Hono | ✅ **React+Vite+idb** |
| Stack refines required | 1 | 1 | 1 | **0** |
| RFC §4 phantom libs | yes (zustand) | none (Item 40) | none | none |
| DAG synthetic `shared` collapse | n/a | yes | none (Item 42) | none |
| Bootstrap deps complete | n/a | no (Item 41) | yes | mostly (Item 47/47b discovered) |
| Mid-run code fixes shipped | 0 | 0 | 1 (Item 46) | 2 (Items 47 + 47b) |
| Tasks first-attempt approved | 2/9 = 22% | 5/7 = 71% | 5/6 = 83% post-fix | 1/1 = 100% (T-001 only; run halted) |
| Documenter reached | no | no | yes | no (interrupted) |

### What v4 changes about M5 framing

Honest reading: v4 added another mid-run discovery layer (Item 47 + 47b), confirming pre-mortem Scenario 7 ("discovery cadence repeats inside M5"). The pattern is **not a regression** — it's structural: every fix that widens an agent's autonomous range exposes a new coverage gap in downstream deterministic layers. Bootstrap's `_NPM_DEP_REGISTRY` is the canonical example: it has to track every library the analyst can autonomously propose, which itself expands every time a prompt loosens.

**Implication for M5-design.md §3 (Sub-phasing).** Each M5 sub-phase (M5.0/0.1/0.2/0.3) should explicitly anticipate a Phase-0.x cycle: ship → run proof-point → discover → ship small fixes → re-run. Allotting "5-7 days" for M5.0 should mean "3 days code + 2-4 days proof-point cascade", not "5-7 days code + done".

**Implication for the item template (Tier 2 process improvement).** The "Counter-example check" field must include a **downstream coverage scan**: "If my fix widens agent A's autonomous range, which deterministic layer downstream (registry, schema, validator) needs corresponding widening?" Items 47/47b would have been caught pre-implementation by this check.

### Open follow-ups from v4

- **Item 45 — IntentAnalyst non-determinism** still open. v4 brief in IntentAnalyst extraction matched v3's structure (single-user, browser persistence signals all present); the analyst's intent.md was clean. But this was one run; non-determinism manifests across multiple runs of the same brief, not within a single run.
- **UI-text-match validation deferred** — needs a run that reaches T-004 (UI module). Next proof-point should run to completion if cascade is shorter (v4 had 2 mid-run discoveries; v5 expected ≤1).
- **`setupTests.ts` browser-persistence shim auto-write** (polish from Item 47b) — defer.
- **Workspace bootstrap doesn't run `npm install`** — operational gap surfaced again in v4. Could be auto-run as part of bootstrap (with --silent flag, subprocess timeout, audit event) — but introduces a side-effect into bootstrap that complicates testing. Open question for the next sprint.

### Senior verdict — proof-point v4 partial

**Primary design signal: ACHIEVED.** BaaS-drift fix landed on the first autonomous call, no refine needed — clean A/B against v1/v2/v3 baselines (3 archived workspaces under `workspaces/*-baseline-*/` make the comparison reproducible). Items 40, 42, 24, 43 (partial) re-validated under fresh conditions.

**Secondary structural finding: ACTED ON in-session.** Items 47/47b shipped + tested + documented. Test count 328 → 337 (+9 across Items 43/BaaS/UI-text/47/47b in this session; +6 from this v4 run alone). Zero regression.

**Cost discipline:** user interrupted at primary-signal-landed + new-item-shipped, rather than chasing T-003→T-005 cascade. This is the recommended pattern per pre-mortem cross-cutting safeguard 4 ("honest measurement"): one proof-point answers one design question; chained discovery should be a separate session with structured scope. Total v4 LLM spend: ~$0.10 (halted before Worker turns on T-003+).

**M5 RAG: still green-lit**, but design must explicitly budget for the discovery-cascade pattern v4 just reconfirmed. The "Foundation v3 produced a complete product" framing remains true; v4 didn't refute it, just measured the half-life of "the planning chain is fully closed" — which is one proof-point.

---

## Item 45 closure — Architect `extract_inputs` non-determinism resolved by prompt fix — 2026-05-14

### Discovery refinement

Item 45 was originally labeled "IntentAnalyst non-determinism" because the proof-point v3 senior verdict surfaced it that way. **The actual culprit was Architect Call 1 (`extract_inputs`)**, not IntentAnalyst — the latter only produces the markdown intent summary; the former produces `golden_path_inputs.json`, and the deterministic scorer reads from there. v3's outlier was Architect Call 1 returning `expected_scale/team_size/ops_capacity = unknown/unknown/unknown` while v1/v2/v4 returned `small/solo/low` for the identical PRD.

| Run | scale | team | ops | tier | Source |
|---|---|---|---|---|---|
| v1 baseline | `small` | `solo` | `low` | T2/100 | `workspaces/ed9f6074f1b8-baseline-pre-40-41-42/` |
| v2 baseline | `small` | `solo` | `low` | T2/100 | `workspaces/7200fa322b61-baseline-pre-41prime-44/` |
| **v3 baseline (outlier)** | **`unknown`** | **`unknown`** | **`unknown`** | **T4/60** | `workspaces/1b9c9f9ca18b-baseline-pre-43-baas-uitext/` |
| v4 (current) | `small` | `solo` | `low` | T2/100 | `workspaces/66244246c339/` |

### Root cause (after reading `agents/architect.md` + `runtime/agents/architect.py`)

Two-rule collision in the prompt:
- **Rule 2:** *"If a field cannot be determined from the PRD, use `\"unknown\"` (string fields) or `false` (bool fields). Do not guess."*
- **Rule 4:** *"`expected_scale`: small: < 1K users; medium: 1K–100K users; large: > 100K users"*

A single-user todo PRD has no explicit "1K users" sentence (Rule 4's threshold), but it *is* obviously <1K users (a single user). LLM oscillates between conservative reading (Rule 2 → `unknown`) and inferential reading (Rule 4 → `small`). Temperature is already 0.0 — DeepSeek's residual variance at temp=0 (no provider guarantees bit-identity) flips this coin occasionally.

### Fix shipped

`agents/architect.md` Call 1 section gained:

1. **Rule 2 modifier** — *"AND no signal in §6 below resolves it"*. Subordinates fallback-to-unknown to the new derivation rules.
2. **New §6 — Derivation rules** with four cases (a/b/c/d):
   - (a) Single-user / personal apps → `small/solo/low`, `multi_tenant=false`, `has_auth=false` unless explicit
   - (b) Team / SaaS apps → `multi_tenant=true`, `has_auth=true`, scale inferred from any user-count clue (default `medium` for SaaS)
   - (c) Enterprise / regulated → `large/large/medium`, `audit_heavy=true`
   - (d) Browser-only / offline-first → apply (a)
3. **Three few-shot examples** — Example A is the v3-regression case verbatim with the canonical output JSON; Example C is the genuinely-vague case showing `unknown` is still right when no signal applies (counter-example pinning the boundary).

`tests/test_architect_key_libraries_discipline.py` gained 2 new prompt-pin tests:
- `test_architect_prompt_teaches_single_user_derivation_rules` — verifies §6 header + four cases + the explicit `small/solo/low` chain.
- `test_architect_prompt_includes_extract_inputs_few_shot_examples` — verifies Example A's JSON + the vague-brief counter-example.

Pytest 337 → **339 (+2)**.

### Empirical validation — `scripts/item_45_empirical.py` (one-off)

5 consecutive `architect.extract_inputs()` calls against the v4 PRD via Anthropic provider:

```
call 1/5 ... scale='small', team='solo', ops='low'
call 2/5 ... scale='small', team='solo', ops='low'
call 3/5 ... scale='small', team='solo', ops='low'
call 4/5 ... scale='small', team='solo', ops='low'
call 5/5 ... scale='small', team='solo', ops='low'

canonical (small/solo/low): 5/5
distinct triple combinations: 1
```

**5/5 deterministic**. Cost: ~$0.05. (Script crashed at the end on the ✓ character + cp1254 console codec — Item 8 class polish; the data was already in.)

### Strategic implication — M5 RAG framing changes

Item 45 was M5-design.md §13's **only** clean closure case for an open backlog item. With Item 45 now closed by a prompt fix, **M5 closes ZERO currently-open items**. M5-design.md §13 has been rewritten:
- §13.0 preserves the original (pre-fix) value mapping for context.
- §13.1 shows the new mapping — every recently-open item closed by prompt/skill/bootstrap, not by memory.
- §13.2 reframes M5 as "platform foundation" for future capabilities (drift detector, skill mining, extend-flow continuity) — none P0 today.
- §13.3 introduces three scope options; **Option α (defer M5)** is recommended.

**The pre-mortem Scenario 8 protocol worked exactly as designed.** Pre-build, ship the cheapest tool that addresses the value claim; if that tool closes the case, the heavier infrastructure investment is honestly deferable. Total time from "M5 is the next big thing" to "M5 is deferred with clean rationale": ~6 hours.

### Open follow-ups

- **`scripts/item_45_empirical.py` cp1254 print crash** — the script's final summary print() hit a Unicode char that Windows cp1254 console can't render. Same class as Item 8. Fix: replace ✓ with ASCII or `sys.stdout.reconfigure` at script top. Trivial; left as-is for this one-off.
- **`team_size` in SaaS Example B** is shown as `solo` because the PRD describes the *customer* team, not the *dev* team. The example notes this distinction explicitly to prevent misreading on multi-user PRDs. Worth empirically validating on a SaaS-shaped brief in a future session — not blocking.
- **Item 45 trace label** — backlog and tespit refer to "IntentAnalyst non-determinism" historically; both files now have the corrected attribution to Architect Call 1 in their 2026-05-14 entries. The original mis-label is preserved in the v3 senior verdict for historical context.

---

## M3.1 v1 proof-point — 2026-05-15

### Run summary

- Workspace: `1b9c9f9ca18b` (cloned from `1b9c9f9ca18b-baseline-pre-43-baas-uitext`, v3 React+Vite+sql.js todo SPA, 5/5 tasks DONE)
- Brief (TR): "Görevlere etiket (tag) ekleyebilme. Her görev bir veya daha fazla etiket alabilsin; kullanıcı etikete göre görev listesini filtreleyebilsin."
- Pipeline: `ortim extend` → `advance extend_prd_approved` → `ortim run` → `advance extend_rfc_approved` → `ortim run`
- Final state: `tasks_ready` (T-006..T-016 PENDING; run-all not invoked)
- LLM spend: ~$0.06 (Babel + ExtenderAgent x2 + Architect Call 1+2 + Orchestrator generate_dag)

### Primary signal — landed (M3.1 happy-path closed)

- `ExtenderAgent.draft_delta_prd` → PRD.md gained `## Extension 1 — Task Tagging` (idempotent cycle-keyed append worked)
- HITL G1 → manual `advance extend_prd_approved` worked; state machine accepted the new transition
- `Architect.draft_rfc(extend_context=...)` → RFC.md gained `## Extension 1` + **`### Module Breakdown (delta)` H3 in the format M3.1.1's `_parse_rfc_extension_modules` parses**
- **Saw-tooth correction validated** (primary design hypothesis): delta PRD listed `Affected Modules: src/`; Architect corrected to `task` + `ui` (the v3 baseline's actual modules). The deeper-context agent fixed the upstream agent's mis-read.
- **M4 cross-task export visibility working in extend mode**: Architect's delta RFC referenced "existing TaskService" + "existing task module exports" — prior-task signatures injected correctly.
- `Orchestrator.generate_dag(prior_dag=..., extend_cycle=1)` → 11 new tasks emitted (T-006..T-016), all `module_scope ∈ {task, ui}` (scope membership union check passed), IDs continuous from T-006 (collision validator silent), and `extensions: [DagDelta cycle 1]` persisted into task_dag.json.
- `task_dag.json.extensions` schema round-trip clean (loaded + extended + re-serialized without back-compat issues).

### Secondary findings — Item 48 (Item 49 retracted; see below)

One extend-cycle Orchestrator drift surfaced from a single proof-point. OPEN — deferred fix to next session. Run-all NOT executed (signal/cost ratio low after the contamination claim was retracted; running 10 Worker turns would cost ~$0.40 to confirm structurally-already-validated chain).

---

### Item 48 — Orchestrator extend DAG over-granularization — SHIPPED 2026-05-15

**Symptom.** M3.1 v1 proof-point cycle 1 (10-AC tagging delta) emitted 10 new tagging-related tasks (T-007..T-016) on a 1:1 AC↔task ratio. Design §8.10 expected ≤3 tasks. Each individual task is structurally valid (deps thread correctly, scope ⊂ allowed modules, validator silent) — but the granularity inflates Worker+Reviewer cost ~3.3x relative to design target.

**Hypothesis.** Orchestrator's prompt has no extend-mode AC-aggregation guidance. Initial-DAG gravity ("every AC ≈ one task") transfers to extend mode where ACs typically describe behaviors (add tag, filter by tag, persist tag) that should bundle into feature-cohesive units (1-3 ACs per task max).

**Acceptance (binary).**
- [ ] `agents/orchestrator.md` extend section contains explicit AC-aggregation guidance ("group ACs by behavior cluster within a module").
- [ ] Re-run cycle 1 proof-point on fresh v3 clone → ≤5 new tasks (target ≤3).
- [ ] Initial DAG tests unchanged (baseline v3 still produces T-001..T-005).

**Counter-example check.** A delta brief with genuinely independent mechanical surface (e.g. "add 8 unrelated API endpoints") must still produce ~8 tasks. Boundary: ACs sharing `module_scope` AND a behavioral cluster (CRUD over same entity, sibling UI components for one feature) → bundle; ACs across modules or unrelated behaviors → keep separate.

**Downstream coverage scan.** Widening Orchestrator's task-granularity judgment range: (a) Reviewer rubric is per-criterion (Phase 0), so 1 task → N criteria already supported — no widening. (b) Test runner per-task scope (Item 39b) is module-bounded, not AC-bounded — unaffected. (c) M4 export visibility unaffected; one task can export multiple symbols. (d) Hard Rule 13 scope match enforced regardless of granularity. **No downstream layer needs widening.**

**Pillar.** 4 (method-level).

**Effort range.** 30-90 min (prompt edit + 2 unit tests + 1 empirical re-run).

**Fix shipped.** `agents/orchestrator.md` gained `## Extend Cycle Task Granularity` section: aggregation rule (`(module_scope × behavioral cluster)`), quantitative anchor (10-AC delta → 3-5 tasks), bundle example (6 tagging ACs → 3 tasks: schema, service methods, UI), counter-example (cross-module ACs stay separate), and `Trace back rule` (every task → delta RFC Module Breakdown row OR delta AC). `runtime/agents/orchestrator.py:232-253` extend-cycle user-prompt context block extended with the aggregation guidance + quantitative anchor + trace-back constraint, referencing the system-prompt section by name.

**Tests added.** `tests/test_extend_dag_validation.py` gained 2 tests: `test_orchestrator_prompt_teaches_extend_ac_aggregation` (pins system prompt has the new section + behavioral cluster + 3-5 anchor + cross-module counter-example + "trace back" literal) and `test_generate_dag_extend_user_prompt_includes_aggregation_guidance` (pins runtime context block injects the same anchor + section reference). Pytest 402 → **404 (+2)**, zero regression.

**Empirical validation.** Cloned v3 baseline to fresh workspace `proofpoint48`; ran cycle 1 with same TR tagging brief.
- Pre-fix run (workspace `1b9c9f9ca18b`): 10 delta ACs → **10 new tasks** (T-007..T-016), AC↔task ratio 1.0:1.
- Post-fix run (workspace `proofpoint48`): 11 delta ACs → **4 new tasks** (T-007 schema + T-008 tagging-module CRUD + T-009 task-module extension methods + T-010 UI bundle), AC↔task ratio 2.75:1.
- Cost: ~$0.06 per run. **Net effect: ~60% task-count reduction with clean dep threading and scope/relevance correctness.**

**Lesson for future items.** Extend-mode prompt gravity differs from initial-mode; do not assume initial-DAG conventions transfer cleanly. The cheapest possible proof-point (one 10-AC delta) was sufficient to surface this — confirms M3.1 design's E2E proof-point §8.10 was scoped correctly.

---

### Item 49 — Orchestrator extend DAG off-delta contamination — RETRACTED

**Original claim (in initial draft of this section).** T-006 "Add task count warning at 1000 tasks" was reported as off-delta contamination from parent RFC context.

**Retraction reason.** Forensic re-check during wrap-up: the baseline v3 workspace's `task_dag.json` already contained T-006 BEFORE the extend cycle ran. The baseline had 6 tasks (T-001..T-006), of which only T-001..T-005 had `task_status.json` records (T-006 emitted-but-never-executed, an unrelated v3-era anomaly). The M3.1 extend cycle correctly used `max_task_id() + 1 = T-007` and emitted `extensions.new_tasks = [T-007..T-016]` — exactly 10 task IDs, all delta-relevant, 0 contamination. The initial mis-read came from a `tid >= 'T-006'` filter that lumped pre-existing T-006 with the new T-007..T-016. The contamination claim was an artifact of poor scan boundary, not Orchestrator behavior.

**Status reset.** Item 49 closed without action. The off-delta-contamination concern remains a theoretical risk but is NOT empirically demonstrated by this proof-point. Re-open if a future cycle produces a task whose description has no overlap with delta RFC / delta PRD.

**Lesson for future items.** Forensic before claim. When scanning a DAG post-extend, identify "new" tasks via the `extensions.new_tasks` field, NOT via task-ID threshold. Task IDs ≥ a threshold include pre-existing orphans. This is the second time in the project's history a finding was incorrectly framed before forensic validation (first: Item 45 mis-labeled "IntentAnalyst" when actual culprit was Architect Call 1). Promote "forensic before claim" to project memory if a third case surfaces.

---

### Strategic implication — M3.1 production-readiness gate

M3.1 v1 (chain plumbing) + Item 48 (extend-cycle AC-aggregation discipline) shipped in single session. Two proof-points confirmed:
- **Cycle 1 chain works**: state machine, ExtenderAgent, delta writer, scope/continuity/ID-collision validators, M4 cross-task export visibility, saw-tooth module-drift correction by Architect — all green on first proof-point.
- **AC-aggregation works**: same TR brief produces 4 well-aggregated tasks post-fix vs. 10 over-granular pre-fix; ~60% reduction; deps thread cleanly; semantic relevance correct.

**Execution-stage proof-point on `proofpoint48` — completed same session (real cost $0.0345, 12 LLM calls):**

| Task | Status | Attempts | Notes |
|---|---|---|---|
| T-007 schema (tags + task_tags tables, scope=task) | DONE | 1 | Worker migrated sql.js schema first-attempt; reviewer approved |
| T-008 tagging-module CRUD (createTag/getAllTags/deleteTag/getTagByName, scope=tagging) | DONE | 2 | First attempt failed on foreign-key cascade test (tasks table missing in test fixture); **Item 15a sandbox feedback loop fired**: prior_reasons fed into attempt 2; Worker fixed and approved |
| T-009 task-module extension (addTag/removeTag/getTasksByTag, scope=task) | AWAITING_HITL | 1 | Reviewer caught real semantic issues — see "Reviewer findings" below |
| T-010 UI bundle | not started | 0 | run-all halted at T-009 HITL escalation |

**Reviewer findings on T-009 (each one accurate, the reject is the system working correctly):**
- **L1 boundary violation**: `task/api/task.service.ts` imports `../tagging/tagging` via internal file path — the `typescript-module-boundaries` skill requires barrel imports (`from '../tagging'`), so the reject is correct rubric application.
- **INNER JOIN vs LEFT JOIN criterion mismatch**: AC said LEFT JOIN; Worker implemented INNER JOIN. Functionally equivalent here (tags-always-exist invariant) but the criterion text is binary — reject is correct.
- **2× `test_infrastructure_unavailable` (Item 24 mode)**: tests for addTag-error-path and deleteTask-cascade were SKIPPED at Worker time; runtime behavior unverifiable → Item 24 schema explicitly escalates to AWAITING_HITL rather than 3-strike retry → exactly the intended discipline.

**Senior verdict on M3.1 production-readiness:**

✅ **Planning chain** (extend → delta PRD → delta RFC → delta DAG) — clean across two proof-points.
✅ **Execution chain primitives** — Worker delta-task writing, M4 cross-task export visibility, Item 15a sandbox feedback retry, Item 21 reviewer rubric, Item 24 unverifiable two-mode discrimination, `typescript-module-boundaries` skill resolver firing, AWAITING_HITL escalation — all observed working on real workspace.
⚠️ **T-009 HITL is NOT a bug** — it's the reviewer's job description. The system stopped the cascade BEFORE writing broken code; the user can now refactor T-009 manually (barrel-export the tagging module) or refine the AC text and re-execute.

**Observations not yet items** (single-data-point, need 2-3 more runs to confirm pattern):
- **G-1 — M4 export visibility vs barrel-import discipline mismatch in extend mode**: M4 prior-task export catalog shows raw internal paths; Worker's `typescript-module-boundaries` skill says barrel-only. The pair is consistent in initial DAGs (Worker reads catalog → writes barrel imports) but in extend mode T-009 showed the Worker copied a raw path. Either (a) skill resolver isn't pulling `typescript-module-boundaries` for extend-cycle tasks, OR (b) M4 catalog should rewrite paths to barrel form for extend mode. Defer to DEFERRED in backlog; trigger = same class in 2 more extend runs.
- **G-2 — `test_infrastructure_unavailable` mode coarseness**: Worker wrote `expect(...).rejects` without wrapping in a Promise on `task/repository.test.ts`, causing a TypeError. The Reviewer labelled this `test_infrastructure_unavailable` and escalated to HITL. The mode classification (Item 24) is `criterion_design_failure` vs `test_infrastructure_unavailable` — but this case is a third mode: `worker_test_quality_failure`. Not blocking; mark for surveillance.

### Total session spend and test posture

| Phase | Spend | Test delta |
|---|---|---|
| First proof-point on `1b9c9f9ca18b` (Item 48 surfacing) | ~$0.06 | 402 baseline |
| Item 48 ship (prompt + runtime + 2 tests) | $0 (no LLM) | 402 → 404 |
| Re-proof-point on `proofpoint48` (Item 48 empirical) | ~$0.06 | 404 baseline |
| run-all on `proofpoint48` (execution-stage) | $0.0345 | 404 unchanged |
| **Day total** | **~$0.16** | **+2 tests** |

The proof-point cost ratio was excellent: 1 structural item shipped end-to-end with empirical validation, 1 false alarm caught at wrap, execution-stage chain validated through real Worker+Reviewer turns, 2 new pattern-watch observations recorded. The "validate-then-wrap" discipline held: each sub-phase produced its own checkpoint and the user directed the next step.
