# Ortim

> A disciplined, multi-agent AI software factory. Turn a one-paragraph brief into working, reviewed, audit-trailed code — without surrendering control to the LLM.

[![PyPI](https://img.shields.io/pypi/v/ortim.svg)](https://pypi.org/project/ortim/)
[![Python](https://img.shields.io/pypi/pyversions/ortim.svg)](https://pypi.org/project/ortim/)
[![License: FSL-1.1-Apache-2.0](https://img.shields.io/badge/license-FSL--1.1--Apache--2.0-blue.svg)](LICENSE)

```bash
pip install ortim
```

Requires Python ≥ 3.11. After install, run `ortim config init` to pick a provider (DeepSeek / Anthropic / local Ollama) and store credentials — no `.env` setup needed.

---

## Why this exists

Coding with a bare LLM ("write me X") fails the same way every time:

- It re-implements code you already have because it forgot.
- It tries a fix, the fix breaks something else, three turns later you've lost the original intent.
- It quietly invents library names. It silently skips tests. It tells you it ran the migration when it didn't.
- It picks microservices for a CRUD app, then asks for your approval on the same decision four times in a single session.
- You can't audit any of it. There is no record of why a choice was made — only the final diff.

Ortim treats AI coding as a **production-engineering problem**, not a prompting problem. A deterministic state machine, two mandatory human gates, a hash-chained audit log, scope-locked task DAGs, and module-boundary sandboxes turn an unreliable LLM into a reviewable software pipeline.

→ **[docs/why-ortim.md](docs/why-ortim.md)** — what the structural differences buy you, with a side-by-side cost/quality comparison against vanilla LLM coding.

---

## Quick start

```bash
# 1) Go to a project directory (greenfield or brownfield).
mkdir ~/dev/task-tracker && cd ~/dev/task-tracker

# 2) Initialize. Ortim creates a .ortim/ namespace here and auto-detects
#    whether the directory is a fresh start or an existing codebase.
ortim init "A small task tracker CLI in Python with SQLite, single user, local only."

# 3) Let Babel + Analyst draft a PRD from the brief.
ortim run

# 4) Review the PRD and approve gate G1.
ortim show --artifact prd
ortim advance prd_approved

# 5) Architect produces an RFC (tier, stack, modules, risks).
ortim run

# 6) Review the RFC and approve gate G2.
ortim show --artifact rfc
ortim advance rfc_approved

# 7) Orchestrator generates the task DAG; Worker + Reviewer execute it.
ortim run                    # DAG generation
ortim run-all --phase 1      # execute MVP tasks

# Observability
ortim status                 # state + history
ortim retro                  # token + USD cost rollup
ortim drift-check            # RFC ↔ DAG ↔ status integrity
```

Every command discovers the workspace from `cwd` (project mode, 0.9+). Run them inside the project directory, or use `--project / -p <id>` from anywhere. `ortim ls` lists every known workspace.

For a quick end-to-end walkthrough with no input:

```bash
ortim demo
```

→ Full tutorial: **[docs/tutorial/getting-started.md](docs/tutorial/getting-started.md)** (~15 minutes from install to a finished project).

---

## What it actually does

| Pain point | Ortim's structural answer |
|---|---|
| **Endless error loops** | 3-attempt budget per task with reviewer feedback injected into each retry; failures escalate to `AWAITING_HITL` instead of spinning forever. |
| **Silent test/hook skips** | Reviewer chain (Code → Security → Test → Perf) treats `unverifiable` differently from `pass`; a missing test runner trips a distinct mode, not a false approval. |
| **Architecture drift** | The Architect agent **does not** pick a tier — an LLM extracts characteristics from the PRD, a deterministic scorer (12 canonical tiers across web/mobile/desktop) picks the architecture. |
| **Scope creep** | PRD locks MVP vs deferred features (Phase 1 / Phase 2+). Orchestrator emits zero tasks for Phase 2; they wait for `ortim extend` in a later cycle. |
| **Module-boundary leaks** | Each task has a `module_scope`; the sandbox rejects writes outside it. Cross-module use is via imports, not file creation. |
| **Hallucinated dependencies** | Bootstrap installs only declared `key_libraries`; an Architect validator (item 40) catches phantom libs in §4 of the RFC before they poison the DAG. |
| **Token waste in non-English flows** | Babel translates a Turkish/etc. brief into a structured intent before any expensive call; "premium" models are reserved for Architect + Security Reviewer. |
| **No audit trail** | Every LLM call, state transition, gate decision, and hook output lands in a hash-chained JSONL (`.ortim/audit.jsonl`). `ortim audit-verify` detects tampering. |
| **Approval fatigue** | Two mandatory gates (G1 = PRD, G2 = RFC). Five conditional gates fire only when relevant (schema, external API, security finding ≥ medium, deploy, budget cap). |
| **AI coding on existing codebases** | `ortim init` in a directory with `package.json` / `pyproject.toml` / `Cargo.toml` / `go.mod` / `pubspec.yaml` auto-enters brownfield mode: import-graph extraction, scope-aware task generation. |

---

## How it compares

Ortim is not an IDE assistant, and isn't trying to be. Cursor, Claude Code, Aider, and Continue.dev all optimize the same loop: you, in your editor, steering the model edit by edit. Ortim optimizes a different one — a brief going through a defensible pipeline you can still explain six months later.

| | IDE assistants (Cursor / Claude Code / Aider) | **Ortim** |
|---|---|---|
| **Unit of work** | A file, a function, a commit, a chat turn | A validated task in a scope-locked DAG |
| **Who picks the architecture** | The model | A deterministic scorer over PRD-derived signals |
| **Approval points** | None enforced | G1 (PRD) + G2 (RFC) mandatory, 5 conditional gates |
| **Test discipline** | Suggested / promptable | Reviewer chain treats `unverifiable` ≠ `pass` |
| **Audit trail** | Conversation or git log | Hash-chained, tamper-evident JSONL, PII-redacted |
| **Best at** | Live, in-editor edits with you watching | Greenfield + brownfield pipelines that must be defensible later |

**Reach for Ortim** when the task is "take a real brief through a real pipeline and be able to explain later what happened and why." **Reach for an IDE assistant** when the task is "tweak this function while I watch." They're complementary — many users run Ortim for the skeleton plus critical features, then switch to an IDE plugin for day-to-day edits.

→ Full feature-by-feature table (incl. Continue.dev) plus the proof-point cost/quality numbers: **[docs/why-ortim.md § Where Ortim sits](docs/why-ortim.md#4-where-ortim-sits-next-to-the-alternatives)**.

---

## Architecture at a glance

```
[brief]
   ↓  Babel       (any language → structured intent, token-frugal)
intent.json
   ↓  Analyst chain (IntentAnalyst + StackAnalyst + PRDAnalyst; M2 conversational)
PRD.md + stack.json
   ↓  G1 — human approval (mandatory)
   ↓  Architect    (Call 1: scorer inputs; Call 2: RFC with two-tier module breakdown)
RFC.md + golden_path_inputs.json
   ↓  G2 — human approval (mandatory)
   ↓  Orchestrator (TaskDAG; Hard Rule 13: DAG ⊂ RFC modules)
task_dag.json + .ortim/tasks/T-NNN.md
   ↓  Worker × N  (FILE_BLOCK output, git branch per task)
   ↓  Reviewer chain (Code → Security → Test → Perf; rubric-shaped verdicts)
   ↓  Hooks       (pre_commit / pre_deploy)
DONE
```

Two invariants worth naming:

- **The LLM never picks a tier.** Architect Call 1 emits parameters; `ortim/architecture/golden_paths.py` does rule-based scoring (12 tiers: T0–T6 web, M0–M2 mobile, D0–D1 desktop).
- **DAGs are runtime-validated.** If the LLM emits a cycle, a missing dependency, or an off-RFC module, validators retry up to 3× then escalate to `AWAITING_HITL`.

Want to see the scorer's verdict before committing to a project? `ortim score-tier` runs the algorithm standalone — **no API key, no workspace, deterministic**:

```bash
ortim score-tier --state --auth --scale large --compliance KVKK,GDPR --audit-heavy
# → a tier table with the picked architecture, the runner-up, and the score gap
```

Full specification: **[Ortim_Architecture.md](Ortim_Architecture.md)** (currently mixed TR/EN; full English translation tracked under Phase 4).

---

## Multi-provider routing

Ortim routes each agent role to its own LLM provider. Most production setups use DeepSeek-only for budget reasons; route Architect and Security Reviewer to Anthropic when judgement matters. No API key at hand? Use Ollama locally.

**Recommended path — `ortim config init` (0.9.4+).** Interactive wizard writes `~/.ortim/config.toml`. No `.env` required, works from any directory:

```bash
ortim config init                # pick provider → model → key, once
ortim config show                # verify what's resolved, with source per field
ortim config set-role architect --provider anthropic   # role override
```

**Or set env vars** (still supported — `~/.ortim/config.toml` only fills gaps, never overrides):

```ini
# .env — minimal
DEEPSEEK_API_KEY=sk-...

# Hybrid — premium reasoning where it pays off
ANTHROPIC_API_KEY=sk-ant-...
ARCHITECT_PROVIDER=anthropic
SECURITY_REVIEWER_PROVIDER=anthropic
```

**Per-invocation override** — highest precedence:

```bash
ortim run --provider ollama --model qwen2.5-coder:7b
ortim demo --provider ollama          # try the demo with zero API keys
```

Resolution order: `--provider` flag → shell / `.env` env var → `~/.ortim/config.toml` → hardcoded default.

Approximate costs on observed proof-point runs (TR brief, 6–8 tasks, 80 %+ first-attempt approval):
- DeepSeek-only: **$0.02–0.05** per planning chain, **$0.02–0.04** per task execution.
- Hybrid (Architect + SecRev on Anthropic): **$0.05–0.10** planning, **$0.04–0.08** per task.
- Ollama-only: **$0.00** (local; throughput depends on hardware).

Supported providers: `anthropic`, `deepseek`, `ollama` (local), any OpenAI-compatible endpoint.

---

## CLI cheatsheet

```bash
# Health + setup
ortim doctor                       # keys, runtimes, prompts, templates
ortim config init                  # one-time provider/key wizard
ortim config show                  # what's active + where it came from
ortim config set-role architect --provider anthropic   # per-role override
ortim config setup-local           # wire up a local Ollama, no API key
ortim config path                  # where the resolved config file lives

# New project (project mode — cwd-aware)
mkdir ~/dev/cool && cd ~/dev/cool
ortim init "<brief>"
ortim run                          # Babel + Analyst → MVP_SCOPE_LOCKING
ortim scope --lock                 # accept default phase split + advance to G1
ortim show --artifact prd
ortim advance prd_approved
ortim run                          # Architect → RFC_AWAITING_APPROVAL
ortim advance rfc_approved
ortim run                          # Orchestrator → tasks_ready
ortim run-all --phase 1            # Worker × N
ortim execute T-003                # run a single task through the pipeline

# Brownfield (existing codebase — auto-detected by ortim init)
ortim inspect                      # codebase scan summary (frameworks, modules)
ortim rescan                       # refresh the scan after large changes
ortim baseline --recapture         # re-run the test suite, store the baseline

# Try the deterministic tier scorer (no API key, no workspace)
ortim score-tier --state --auth --scale medium --compliance KVKK

# Observability + integrity
ortim status                       # state + history
ortim tasks                        # task DAG
ortim gates                        # open HITL gates (G1–G7) + budget status
ortim states                       # full state machine + legal transitions
ortim budget --by-provider         # token + USD, per provider
ortim retro                        # multi-axis rollup over the audit log
ortim drift-check                  # RFC ↔ DAG ↔ status ↔ audit alignment
ortim audit-verify                 # walk the hash chain, flag tampering
ortim show --artifact rfc

# Iteration
ortim refine "<feedback>"          # dialog-mode refine
ortim extend "<new feature>"       # DONE project → delta cycle
ortim extensions                   # extend-cycle history

# Skills (project-specific Worker/Reviewer patterns)
ortim skill list
ortim skill show <name>

# Workspace management (from anywhere)
ortim ls                           # all known workspaces; '*' = active
ortim use <id|name>                # set active pointer (registry-backed)
ortim status -p <id>               # target a specific workspace
ortim workspace archive <id>
ortim workspace unarchive <id>
ortim workspace migrate            # upgrade an older layout to the current one
ortim workspace doctor             # diagnose registry / layout issues
ortim workspace cleanup --older-than 30 --archived-only --yes

# Governance & cloud sync (preview — see docs/cloud.md)
ortim cloud login <email>          # authenticate against cloud.ortim.dev
ortim cloud link --org <id>        # link this workspace to an org project
ortim cloud sync                   # push redacted audit metadata (offline-safe)
ortim cloud policy                 # pull + show the org governance policy
```

Full reference: `ortim --help`.

---

## State machine

```
intake → babel → intake_dialog → stack_dialog → prd_dialog → prd_drafting
       → prd_awaiting_approval → prd_approved
                 ↑ G1 (mandatory)
       → rfc_drafting → rfc_awaiting_approval → rfc_approved
                              ↑ G2 (mandatory)
       → tasks_generating → tasks_ready → executing → done
```

Conditional gates fire mid-execution: **G3** schema/migration, **G4** external API call, **G5** security severity ≥ medium, **G6** deploy, **G7** budget cap. Each pauses the task in `AWAITING_HITL`; `ortim advance <state>_approved` resumes.

---

## Governance & cloud sync (preview)

The audit trail is local-first and works with zero account. For teams that need shared governance, `ortim cloud` adds an **Observer layer** on top — without changing how the pipeline runs:

- **What syncs:** redacted audit metadata + pipeline state only. **Source code is never sent**; PII is redacted before it leaves the machine.
- **Offline-safe:** if the cloud is unreachable, `ortim cloud sync` prints a warning and exits 0 — the local pipeline is never blocked.
- **Policy enforcement:** an org policy can pin mandatory gates, an allow-list of providers, and a budget cap; the CLI pulls it and enforces it locally.

```bash
ortim cloud login you@org.com
ortim cloud link --org <id>        # link the current workspace to an org project
ortim cloud sync                   # push redacted metadata
ortim cloud policy                 # show the org's governance rules
```

This is an early **preview** pointing at `cloud.ortim.dev`; access is invite-only while it's being scoped. Full payload shape + threat model: **[docs/cloud.md](docs/cloud.md)**.

---

## License

- **Core** (this repo): [FSL-1.1-Apache-2.0](LICENSE) — Functional Source License, automatically converts to Apache-2.0 after two years. Production use is free; building a competing service against the same APIs is the only thing restricted, and only for two years.
- **Enterprise** (`enterprise/` — multi-tenant orchestrator, SSO, audit retention, SLA): [Commercial](LICENSE.commercial). Currently a stub; first beta enterprise pilot is being scoped.

---

## More documentation

- **[Why Ortim](docs/why-ortim.md)** — value framing, comparison vs vanilla LLM coding, when to use this vs Cursor/Aider/Claude Code.
- **[Getting started](docs/tutorial/getting-started.md)** — ~15-minute end-to-end tutorial (greenfield + brownfield).
- **[Failure recovery runbook](docs/runbook/failure-recovery.md)** — what to do when a task lands in `AWAITING_HITL`, budget gate trips, schema migration fails, etc.
- **[Cloud governance (preview)](docs/cloud.md)** — `ortim cloud` Observer layer: what syncs (redacted metadata only), offline-safety, org policy enforcement.
- **[Architecture spec](Ortim_Architecture.md)** — full master specification (TR/EN mixed; English-only revision is in flight).
- **[Golden paths](docs/golden-paths/)** — reference docs for each of the 12 tiers.
- **[Skill authoring guide](docs/skills/authoring-guide.md)** — how to inject project-specific patterns into Worker/Reviewer prompts.
- **[Changelog](CHANGELOG.md)**.
- **Türkçe arşiv:** [`docs/tr/`](docs/tr/) — original Turkish-language tutorial and runbook (kept in sync best-effort; the English version is canonical).

---

## Development

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

735 unit + integration tests, 22 deselected end-to-end baselines (real-LLM fixtures, opt-in with `-m e2e`). Full suite runs in ~37 seconds.

---

## Issues + contact

- Issues: [github.com/orhanurullah/ortim/issues](https://github.com/orhanurullah/ortim/issues)
- License questions or commercial inquiries: `contact@ortim.dev`
