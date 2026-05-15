# M2 — Conversational Intake & Stack Iteration

**Status:** Design lock — 2026-05-13. Locked decisions from tespit.md item 10 + user confirmation.
**Effort estimate:** ~5–7 days of focused work, pytest 218 → ~230.
**Items closed structurally:** 2, 17, 18 (tier scoring drift, decoupled tier opinions, env-blind stack).
**Items improved transitively:** 26 (locked stack → correct test runner → tsc/vitest catches compile errors during pipeline).

---

## 1. Locked design decisions

| # | Question | Decision | Why |
|---|---|---|---|
| 1 | UX model | **Turn-based CLI** (`ortim refine <id> "<feedback>"`). No REPL in M2. | Sade; debug edilebilir; Windows PowerShell + Rich + prompt_toolkit etkileşim sürprizlerini elimine eder (madde 8 sınıfı). REPL M3+ için bırakıldı. |
| 2 | Diff display | `rich.console` minimal **unified diff** sadece `ortim lock` öncesi son onay anında. Refine sırasında diff yok. | Refine'ler hızlı olmalı; lock kalıcı kararı temsil ediyor — orada yavaşla. |
| 3 | Token budget cap | `AI_FACTORY_DIALOG_TURN_CAP=10` (per-state). Aşılırsa `[budget] turn cap exceeded` warning + `--force` zorunlu. | Kullanıcı 20 tur "biraz daha açıkla" dersse maliyet uçar. Sert blok değil, görünür guard. |
| 4 | Documenter | M2-3'te locked stack'i README context'ine geçir. README'deki `npm install` / `flutter pub get` doğru komut olur. | Mevcut `documenter.py` PRD+RFC bakıyor ama stack inference RFC'nin parsing'ine kalmış. Locked stack tek doğru kaynak. |

---

## 2. State machine extension

Mevcut zincir:
```
INTAKE → BABEL_PROCESSING → PRD_DRAFTING → PRD_AWAITING_APPROVAL → PRD_APPROVED → RFC_DRAFTING → ...
```

Yeni dialog zinciri (opt-in via `AI_FACTORY_DIALOG_MODE=on`, default `on` for new projects):
```
INTAKE → BABEL_PROCESSING → INTAKE_DIALOG → STACK_DIALOG → PRD_DIALOG → PRD_AWAITING_APPROVAL → ...
                          ↘ (legacy) PRD_DRAFTING ↗   (preserved for older projects + tests)
```

`BABEL_PROCESSING`'in `to`-set'ine `INTAKE_DIALOG` eklenir; `PRD_DRAFTING` çıkışı korunur (geriye uyumluluk + brownfield `INTAKE → PRD_DRAFTING` shortcut'ı zaten var, değişmiyor).

### Yeni state'ler

| State | Aktif artifact | Çıkış transitions |
|---|---|---|
| `INTAKE_DIALOG` | `workspace/intent.md` (refined niyet özeti) | `STACK_DIALOG` (lock), `PAUSED`, `FAILED` |
| `STACK_DIALOG` | `workspace/stack.md` (locked tier + locked language/framework + rationale) | `PRD_DIALOG` (lock), `INTAKE_DIALOG` (back-step), `PAUSED`, `FAILED` |
| `PRD_DIALOG` | `workspace/PRD.md` (legacy path korunur) | `PRD_AWAITING_APPROVAL` (lock), `STACK_DIALOG` (back-step), `PAUSED`, `FAILED` |

Back-step transitions (örn. `STACK_DIALOG → INTAKE_DIALOG`) kullanıcı "stack'i değiştirmek için niyeti yeniden konuşmam lazım" derse: lock kararını geri al, ilgili dialog state'e dön. Lock'lar tek yönlü değil ama PRD onayından sonra geri dönüş yok (`PRD_APPROVED` halen tek yön).

---

## 3. Agent ayrışması

`runtime/agents/analyst.py` korunur (legacy facade). Yeni sınıflar:

### `IntentAnalyst` (runtime/agents/intent_analyst.py)
- **Input:** `StructuredIntent` (Babel'den), opsiyonel önceki `intent.md`, opsiyonel `feedback`
- **Output:** markdown niyet özeti (PRD değil — daha kısa, sadece "ne yapıyoruz, kim için, hangi feature'lar")
- **Methods:** `draft(intent, project_id) → md`, `refine(prev_md, structured_intent, feedback, project_id) → md`
- **Boundary:** tech stack'e dokunmaz, sadece amaç/kullanıcı/özellik.

### `StackAnalyst` (runtime/agents/stack_analyst.py)
- **Input:** `intent.md`, deterministic `TierScore` (öneri), opsiyonel önceki `stack.md`, opsiyonel `feedback`
- **Output:** markdown stack belgesi (Tier code, language, framework, key libraries, test runner, deploy hedefi, rationale + alternatifler)
- **Methods:** `propose(intent_md, tier_score, app_class, project_id) → md`, `refine(prev_md, intent_md, feedback, project_id) → md`
- **Boundary:** kullanıcının override'ını respect eder ("Go değil Python istiyorum" → Tier korunabilir ama language değişir). User override deterministic tier scorer'ı **kilitler**.

### `PRDAnalyst` (runtime/agents/prd_analyst.py)
- **Input:** `intent.md` (locked), `stack.md` (locked), opsiyonel önceki `PRD.md`, opsiyonel `feedback`
- **Output:** markdown PRD (mevcut PRD template'i ile)
- **Methods:** `draft(intent_md, stack_md, project_name, project_id) → md`, `refine(prev_prd, feedback, project_id) → md`
- **Boundary:** stack'i değiştirmez; "PRD'de auth bahsediyorsun ama stack'te Supabase yok" gibi tutarsızlıkları **flag'ler**, kullanıcı `STACK_DIALOG`'a dönmeden çözmez.

### Disk layout

```
workspaces/<id>/
├── intent.json            # Babel raw output (unchanged)
├── intent.md              # IntentAnalyst draft/locked
├── stack.md               # StackAnalyst draft/locked
├── PRD.md                 # PRDAnalyst draft (legacy path also writes here)
├── RFC.md                 # Architect Call 2 output (M2-3'ten sonra stack.md'yi kullanır)
├── .dialog/
│   ├── intent_turns.jsonl # [{ts, user_feedback, response_hash, turn_n}]
│   ├── stack_turns.jsonl
│   └── prd_turns.jsonl
└── ...
```

Lock event'i sadece state transition. Artifact dosyası **yerinde kalır** (sadece okunur hâl alır — dosya sistemi düzeyinde değil, mantıksal: lock'tan sonraki refine yeni dialog state'e dönmediği sürece reddedilir).

---

## 4. CLI yüzeyi

### Yeni komutlar

```bash
ortim refine <id> "<feedback>"
  # Aktif dialog state'in agent'ını çağır. Önceki artifact + feedback → yeni artifact.
  # State INTAKE_DIALOG değilse / STACK_DIALOG / PRD_DIALOG: error.
  # Turn count workspace/.dialog/<state>_turns.jsonl'ye eklenir; cap aşımında uyarı.

ortim show <id> [--artifact intent|stack|prd]
  # Mevcut state'in (ya da --artifact ile belirtilen) markdown'unu konsola bas.
  # Lock öncesi son halini gösteriyor; diff için lock zamanında ayrı UI var.

ortim lock <id>
  # Aktif dialog state'i kilitle, bir sonrakine geç.
  # Önce diff göster (önceki turn'le): rich Panel — değişiklik özeti.
  # User onayı (--yes ile bypass) → state transition → audit dialog_lock event.

ortim refine <id> "<feedback>" --force
  # Turn cap'i aşıldıktan sonra bilinçli devam.
```

### Mevcut `ortim run` davranışı

- `ortim run <id> --step babel` aynı kalır.
- `ortim run <id> --step auto` (default): Babel sonrası dialog mode `on` ise `INTAKE_DIALOG`'a geçer ve **ilk intent.md draft'ını üretip durur** (kullanıcının `refine` veya `lock` ile devam etmesini bekler). Legacy mode'da olduğu gibi PRD'ye kadar koşmaz.
- `AI_FACTORY_DIALOG_MODE=off` set'liyse: BABEL → PRD_DRAFTING legacy yolu çalışır (mevcut testler patlmaz).

### Backward compat matrisi

| Senaryo | Davranış |
|---|---|
| Mevcut DONE proje + tekrar `run` | Etkilenmez (state DONE, transition yok). |
| Mevcut PRD_AWAITING_APPROVAL proje | Etkilenmez (zaten dialog state'lerinin ötesinde). |
| Yeni proje, `AI_FACTORY_DIALOG_MODE` set değil | Default `on` — dialog yoluna girer. |
| Yeni proje, `AI_FACTORY_DIALOG_MODE=off` | Legacy `BABEL → PRD_DRAFTING` yoluna girer. |
| `test_state_machine.py::test_happy_path_transitions_are_valid` | `BABEL_PROCESSING → PRD_DRAFTING` transition'ı **korunduğu** için pas geçer. |

---

## 5. Audit log

Yeni event tipleri:

```jsonl
{"event": "dialog_turn", "state": "intent_dialog", "turn_n": 3, "user_feedback_hash": "...", "response_hash": "...", "project_id": "..."}
{"event": "dialog_lock", "from_state": "intent_dialog", "to_state": "stack_dialog", "artifact_hash": "...", "turns_used": 4, "project_id": "..."}
{"event": "dialog_turn_cap_exceeded", "state": "intent_dialog", "turn_n": 11, "cap": 10, "forced": false, "project_id": "..."}
{"event": "dialog_back_step", "from_state": "stack_dialog", "to_state": "intent_dialog", "reason_hash": "...", "project_id": "..."}
```

User feedback hash'li (PII redaction default ON ile uyumlu). Raw text `AI_FACTORY_AUDIT_RAW=1` ile saklanır.

---

## 6. Bootstrap + Architect entegrasyonu (M2-3)

**Mevcut karmaşa (item 17 + 18a):**
- `_LANG_STACK_BY_TIER_APP` matrix — Architect'e tier-based stack constraint zorlar
- `_infer_test_cmd_from_rfc` — bootstrap'a RFC parse ederek test cmd seçtirir
- `_TEST_CMD_BY_TIER_APP` matrix — tier-based test cmd

Üç ayrı "stack opinion" üretici. M2-3'te:

1. `stack.md` artık tek doğru kaynak. Schema: locked Tier code, language, framework, test cmd, run cmd, deploy target — pydantic model `LockedStack` ile parse edilir.
2. `bootstrap_workspace_layout` `LockedStack | None` alır; varsa heuristic'ler **bypass**, doğrudan stack'ten template/test cmd çekilir.
3. `Architect.draft_rfc` `LockedStack | None` alır; varsa `_LANG_STACK_BY_TIER_APP` constraint string'i yerine `stack.md` içeriği gömülür ("Use EXACTLY this stack — do not deviate").
4. `_LANG_STACK_BY_TIER_APP` ve `_infer_test_cmd_from_rfc` **korunur ama deprecated** — sadece `AI_FACTORY_DIALOG_MODE=off` legacy yolunda kullanılır.
5. `DocumenterAgent.generate_readme` `LockedStack | None` alır; varsa README'deki install/run komutları stack'ten alınır (parse heuristic yok).

---

## 7. Test sayımı hedefi

| Dosya | Yeni testler |
|---|---|
| `tests/test_state_machine.py` | +3 (INTAKE_DIALOG transitions, lock ileri, back-step) |
| `tests/test_intent_analyst.py` (yeni) | +2 (draft, refine feedback honors) |
| `tests/test_stack_analyst.py` (yeni) | +3 (propose, user override locks scorer, refine) |
| `tests/test_prd_analyst.py` (yeni) | +1 (draft uses locked stack) |
| `tests/test_dialog_cli.py` (yeni) | +2 (refine + lock workflow, turn cap warning) |
| `tests/test_bootstrap.py` | +1 (LockedStack overrides heuristics) |
| `tests/test_architect_brownfield.py` | +1 (LockedStack injected verbatim into prompt) |
| **Toplam** | **+13** → pytest 218 → **231** |

---

## 8. Faz sırası ve commit stratejisi

```
M2-0 (this doc)
  └─ M2-1a: state machine + state transitions + tests
       └─ M2-1b: 3 new agent classes + system prompts
            └─ M2-1c: dialog artifact storage + LockedStack pydantic model + audit events
                 └─ M2-2: refine/lock/show CLI commands + run command rerouting + diff display
                      └─ M2-3: bootstrap + Architect Call 2 + Documenter integration
                           └─ M2-4: integration tests + E2E validation against item 26 regression
```

Her faz commit-able. Mevcut 218 testin tamamı her commit'te pas geçmeli (M2-1a hariç — orada +3 yeni test gelir).

---

## 9. Riskler

| Risk | Olasılık | Mitigation |
|---|---|---|
| Turn-based UX REPL kadar akıcı değil; "konuşma" hissi düşük | Orta | M3 Skills sonrası kullanıcı geri bildirimine göre M5/M6'da REPL eklenir. |
| `AI_FACTORY_DIALOG_MODE=on` default eski test fixtures'larını kırar | Düşük | State machine transition'larında **ekleme** var, **çıkarma** yok; legacy paths korunur. |
| `LockedStack` schema'sı sonradan değişirse eski projelerin stack.md'si parse edilemez | Orta | `version: int = 1` field'ı + forward-compat parser; eski projeler `--legacy` flag'iyle korunur. |
| StackAnalyst LLM kullanıcının "Go istiyorum" override'ını silent ignore edebilir | Yüksek | `stack_analyst.md` prompt'unda hard rule: "User explicit preference is FINAL — never override; only flag conflicts as warnings." Test: feedback `"use Python instead"` → output Python içermeli. |
| Lock öncesi diff UI Windows'ta UTF-8 escape'lerini bozar | Düşük | Madde 8 fix zaten reconfigure ediyor; ek olarak Rich Panel ASCII fallback. |

---

## 10. M2 dışında bırakılanlar (M3+'a ertelendi)

- Full REPL (textual TUI) — M3 sonrası kullanıcı feedback'iyle değerlendirilecek.
- Multi-modal intake (resim/ekran görüntüsü) — M5+.
- `ortim discuss --voice` ses girişi — M6+.
- Per-tenant dialog template'leri — Enterprise tier.
- Cross-task import verification (item 26'nın geri kalanı) — M3 Skills sistemiyle çözülecek.
