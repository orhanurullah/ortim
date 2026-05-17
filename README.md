# Ortim

> Yapay zeka destekli, sıkı kurallı, çok-ajanlı yazılım geliştirme platformu.

Ortim Türkçe brief'inden çalışan koda — PRD → RFC → Task DAG → Worker + Reviewer chain'i ile — götürür. Felsefe net: **markdown bilgiyi söyler, runtime kuralı zorlar**. LLM "atlamak" istese bile state machine, deterministik tier scorer ve DAG validator engeller.

```bash
pip install ortim
```

Gereksinim: Python ≥ 3.11, bir LLM API key (DeepSeek veya Anthropic).

## Ne işe yarar

LLM ile kod yazmanın yaygın acılarını yapısal olarak çözer:

- **Sonsuz hata döngüleri yok** — her task için 3-deneme bütçesi, sonrasında `AWAITING_HITL`. Aynı failure'ı sessizce tekrarlamaz; Reviewer geri bildirimi yeni denemeye inject edilir.
- **Belge-tabanlı akış** — PRD (ne) → RFC (nasıl) → Task DAG (atomik iş paketleri). Her ajan kendi katmanında kalır, biri diğerinin işini gizlice yapmaz.
- **2 zorunlu insan onay noktası** (G1=PRD, G2=RFC) artı 5 koşullu gate (schema, external integration, security, deploy, budget) — kritik anlarda akış durur, sen onaylarsın.
- **Çift-modelli ekonomi** — pahalı kararlar (Architect, Security Reviewer) Claude'da, ucuz/yüksek-hacim iş (Babel, Worker) DeepSeek'te kalabilir. Tek pipeline, başına ~$0.02-0.05 planning maliyeti.
- **Audit + tamper-evidence** — her LLM çağrısı, her state geçişi, her hook çıktısı hash-chained JSONL'e düşer. PII redaction (KVKK/GDPR) default açık.
- **Brownfield desteği** — mevcut Flutter/Tauri/React projeye `ortim new --from-existing` ile plug-in olur; framework auto-detect, import-graph extraction, scope-aware task generation.

## Hızlı başlangıç

```bash
# 1) Yeni proje aç (TR brief ile)
ortim new "Bir görev yönetim CLI'sı istiyorum, Python + SQLite, tek kullanıcı" --name todo-cli

# 2) Babel + Analyst + Stack diyaloğu — PRD'ye doğru ilerleme
ortim run <project-id>

# 3) PRD'yi gözden geçir, onayla (G1)
ortim advance <project-id> prd_approved

# 4) Architect RFC çizsin
ortim run <project-id>

# 5) RFC'yi gözden geçir, onayla (G2)
ortim advance <project-id> rfc_approved

# 6) Orchestrator DAG üretsin
ortim run <project-id>

# 7) DAG'ı sıralı (veya paralel, --parallel) koştur
ortim run-all <project-id>

# Maliyet raporu
ortim budget <project-id>
```

Default'lar üretim-için-hazır: dialog mode açık, G1/G2 zorunlu insan onayı, Worker test komutunu önceden yazılı `.ortim.env`'den okur, git branch izolasyonu auto.

Hızlı tam-pipeline demo'su (insan onay adımları otomatik):

```bash
ortim demo --brief "Mini bir kişisel finans REST API. JWT auth, gelir/gider CRUD, aylık özet. Python + FastAPI + SQLite."
```

Demo tüm planning chain'i (Babel → Analyst → Architect → Orchestrator) sondan sona koştur; ~$0.02-0.05 maliyet (DeepSeek).

## Multi-provider

`ortim` her ajan rolünü ayrı bir LLM provider'a yönlendirebilir. `.env`:

```ini
# Tek provider yeterli
DEEPSEEK_API_KEY=sk-...

# Veya kritik rolleri Anthropic'e yönlendir
ANTHROPIC_API_KEY=sk-ant-...
ARCHITECT_PROVIDER=anthropic
SECURITY_REVIEWER_PROVIDER=anthropic
```

Bir tam planning chain DeepSeek'te ~$0.01. Architect + Security Reviewer Anthropic'teyse ~$0.05-0.10. Mevcut provider'lar: `anthropic`, `deepseek`, `ollama` (lokal/self-host), `openai`-uyumlu endpoint'ler.

## Mimari özet

```
[TR brief]
   ↓ Babel (TR → structured intent)
intent.json
   ↓ IntentAnalyst + StackAnalyst + PRDAnalyst (M2 conversational)
PRD.md + stack.json
   ↓ G1 — PRD onayı
   ↓ Architect (Call 1: tier scorer inputs, Call 2: RFC)
RFC.md + golden_path_inputs.json
   ↓ G2 — RFC onayı
   ↓ Orchestrator (TaskDAG, Hard Rule 13: DAG ⊂ RFC modülleri)
task_dag.json + tasks/T-NNN.md
   ↓ Worker + Reviewer (chain: Code + Security + Test + Perf)
   ↓ Hooks (pre_commit / pre_deploy)
DONE
```

İki invariant koruma altında:

- **Tier seçimini LLM yapmaz.** Architect Call 1 PRD'den parametre çıkarır; `ortim/architecture/golden_paths.py` kural-temelli skor hesaplar. 7 tier (T0-T6 web + M0-M2 mobile + D0-D1 desktop).
- **DAG'ı runtime validate eder.** LLM cycle, eksik dep, RFC dışı modül üretirse 3× retry; sonrasında `AWAITING_HITL`.

Detaylı spec: [`Ortim_Architecture.md`](./Ortim_Architecture.md).

## CLI komutları

| Komut | Amaç |
|---|---|
| `ortim doctor` | Environment health check (Python, API keys, runtime binaries) |
| `ortim new <brief> --name <ad>` | Yeni proje aç |
| `ortim demo --brief "..."` | Tam pipeline demo (G1/G2 auto-approve) |
| `ortim run <id>` | State'e göre uygun ajanı koştur |
| `ortim discuss <id>` / `refine <id> "<feedback>"` / `lock <id>` | M2 conversational intake (intent / stack / PRD diyaloğu) |
| `ortim advance <id> <target>` | Manuel state ilerletme (gate onayı, vs.) |
| `ortim tasks <id>` | TaskDAG + batch'ler |
| `ortim execute <id> <task-id>` | Tek task'ı Worker → tests → Reviewer pipeline'ından geçir |
| `ortim run-all <id> [--parallel]` | DAG'ı topolojik batch'lerde koştur |
| `ortim extend <id> "<brief>"` | DONE projeye iteratif feature delta'sı (M3.1) |
| `ortim budget <id>` / `ortim retro <id>` | Token + USD raporu / per-task analiz |
| `ortim drift-check <id>` | Multi-cycle integrity check |
| `ortim states` | Tüm state'ler ve izinli geçişler |

Tam liste: `ortim --help`.

## State machine ve HITL gate'ler

```
intake → babel → intake_dialog → stack_dialog → prd_dialog → prd_drafting
       → prd_awaiting_approval → prd_approved
                 ↑ G1 (zorunlu)
       → rfc_drafting → rfc_awaiting_approval → rfc_approved
                              ↑ G2 (zorunlu)
       → tasks_generating → tasks_ready → executing → done
```

5 koşullu gate: **G3** (schema/migration), **G4** (external API call detected), **G5** (security severity ≥ medium), **G6** (deploy), **G7** (budget cap aşıldı). Her gate task'ı `AWAITING_HITL`'e gönderir, ilerleme `ortim advance ... <state>_approved`'a kadar durur.

## Lisans

**Core**: [FSL-1.1-Apache-2.0](./LICENSE) — 2 yıl Functional Source License (non-compete), sonra otomatik Apache-2.0'a dönüşür.

**Enterprise** (`enterprise/` dizini, M5+ kapsamı): [Commercial](./LICENSE.commercial). Multi-tenant orchestrator, SSO, audit retention, SLA. Şu an boş iskelet.

## Daha fazla

- **Mimari**: [`Ortim_Architecture.md`](./Ortim_Architecture.md) — full spec
- **Başlangıç rehberi**: [`docs/tutorial/getting-started.md`](./docs/tutorial/getting-started.md) — 15 dakikalık adım adım
- **Hata kurtarma**: [`docs/runbook/failure-recovery.md`](./docs/runbook/failure-recovery.md)
- **Sürüm geçmişi**: [`CHANGELOG.md`](./CHANGELOG.md)
- **Geliştirici kurulumu** (katkı için): repo'yu klonla, `pip install -e .[dev]`, `pytest`

## Geliştirme

```bash
git clone https://github.com/orhanurullah/ortim.git
cd ortim
python -m venv .venv
.venv/Scripts/activate            # Windows
# source .venv/bin/activate       # macOS/Linux
pip install -e .[dev]

ruff check .
mypy ortim
pytest
```

606 birim/entegrasyon testi, 22 deselect edilmiş e2e baseline (real-LLM fixture'lı, `-m e2e` ile opt-in). Tüm suite ~25 saniye.

## Sorun bildirimi + destek

- Issues: [github.com/orhanurullah/ortim/issues](https://github.com/orhanurullah/ortim/issues)
- Lisans soruları: `LICENSE` ve `LICENSE.commercial` notlarına bak; özel durumlar için `contact@ortim.dev`
