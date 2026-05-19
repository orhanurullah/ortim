# Ortim — Getting Started

> A step-by-step walkthrough from install to a finished project. Written for working developers; assumes a terminal, an LLM API key, and basic Git familiarity.

What this is:
- A guided run through `ortim`'s end-to-end flow, with the rationale behind each step.

What this is not:
- The architectural specification ([`Ortim_Architecture.md`](../../Ortim_Architecture.md) covers that).
- A complete CLI reference (`ortim --help` covers that).
- The value pitch — see [`docs/why-ortim.md`](../why-ortim.md) for that.

Turkish-language original: [`docs/tr/tutorial/getting-started.md`](../tr/tutorial/getting-started.md).

Contents:
1. [Install + environment](#1-install--environment)
2. [ortim doctor — health check](#2-ortim-doctor--health-check)
3. [First run — `ortim demo`](#3-first-run--ortim-demo)
4. [Real project — `ortim init` to DONE](#4-real-project--ortim-init-to-done)
5. [Trust calibration — the AI wrote it, you sign it](#5-trust-calibration--the-ai-wrote-it-you-sign-it)
6. [Common problems + fixes](#6-common-problems--fixes)
7. [Where to go next](#7-where-to-go-next)

---

## 1. Install + environment

### 1.1 Install

```bash
pip install ortim
```

Requires Python ≥ 3.11. If `pip` is not on your PATH on Windows, use `py -m pip install ortim` instead.

For development (contributing):

```bash
git clone https://github.com/orhanurullah/ortim.git
cd ortim
python -m venv .venv
.venv/Scripts/activate            # Windows
# source .venv/bin/activate       # macOS/Linux
pip install -e .[dev]
```

Editable install (`-e`) keeps the `ortim` command in sync with your local edits.

### 1.2 LLM provider — `ortim config init` (0.9.4+)

Easiest path: run the interactive wizard. It writes `~/.ortim/config.toml` once and applies everywhere — no per-project `.env` files needed.

```bash
ortim config init
```

It asks three things:
1. **Provider** — `anthropic` (Claude), `deepseek` (Anthropic-compatible, cheap), or `ollama` (local, no API key).
2. **Default model** — accept the provider's default or pick your own.
3. **API key** — hidden input; skipped for `ollama` since it runs locally.

Verify what's active:

```bash
ortim config show
# │ default provider  │ deepseek        │ config  │
# │ default model     │ deepseek-chat   │ config  │
# │ deepseek api key  │ set (length 35) │ config  │
```

The `Source` column tells you where each value came from:
- `config` — `~/.ortim/config.toml` (set via the wizard)
- `env` — shell variable or `.env` in the project directory
- `default` — neither; the hardcoded fallback will apply

**Per-role overrides** — cheap model for high-volume work, premium for the calls that matter:

```bash
ortim config set-role architect --provider anthropic
ortim config set-role security_reviewer --provider anthropic
ortim config set-role babel --provider deepseek
```

**Per-invocation override** — try a different provider for one command without touching config:

```bash
ortim run --provider ollama --model qwen2.5-coder:7b
ortim demo --provider ollama        # try the demo with zero API keys
```

**Resolution order** (highest precedence first):
1. `--provider` / `--model` CLI flag
2. Shell or `.env` env var (`LLM_PROVIDER`, `DEEPSEEK_API_KEY`, role-specific `BABEL_PROVIDER`, ...)
3. `~/.ortim/config.toml`
4. Hardcoded default (`anthropic` + `claude-opus-4-7`)

So setting `LLM_PROVIDER=ollama` in your shell for one session always wins over whatever the config file says, and `--provider deepseek` on a single command always wins over both.

**Alternative — `.env` file.** Still fully supported. Create a `.env` in the directory where you'll run `ortim`:

```ini
# Cheap baseline — entire pipeline works on DeepSeek
DEEPSEEK_API_KEY=sk-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
LLM_PROVIDER=deepseek

# Optional — route the high-judgement roles to Claude
ANTHROPIC_API_KEY=sk-ant-xxxxxxxxxxxxxxxxxxxxxxxxxxxxx
ARCHITECT_PROVIDER=anthropic
SECURITY_REVIEWER_PROVIDER=anthropic

# Optional — per-project USD cap (G7 budget gate)
ORTIM_BUDGET_CAP_USD=2.00
```

**Why both API key entries are optional:** Ortim is multi-provider. With no keys and no Ollama, LLM-driven commands (`init`, `run`, `demo`, `run-all`, `extend`) won't work; deterministic ones (`status`, `tasks`, `drift-check`, `score-tier`, `retro`) still run. Pick one of: DeepSeek (cheap), Anthropic (premium), Ollama (local, free).

**Getting a DeepSeek key:** [platform.deepseek.com](https://platform.deepseek.com) → Sign up → API Keys → Create. Free credit covers ~500 planning chains.

**Running Ollama locally:** install from [ollama.com](https://ollama.com), then `ollama pull qwen2.5-coder:7b`. `ortim config set-provider ollama` and you're done — no API key, no monthly bill.

### 1.3 Workspace pattern — Project Mode (0.9+)

Ortim 0.9 made Project Mode the default — it behaves like `git`, `cargo`, or `terraform`. Each project lives in its own directory; Ortim keeps metadata in a `.ortim/` namespace inside it, and writes generated code to the project root.

```
~/dev/my-project/             ← cwd; any directory you like
├── .ortim/                   ← Ortim metadata (state.json, PRD.md, RFC.md, tasks/, audit.jsonl, ...)
├── auth/                     ← Worker-written code (module-scoped)
├── src/
├── package.json              ← used for brownfield manifest detection
└── ...
```

Add `.ortim/` to `.gitignore` if you don't want metadata in version control. Some teams do commit PRD/RFC (the human-readable artifacts) but not `audit.jsonl` and `.cache/`. Choose what fits your team.

**Discovery order:** Ortim resolves which workspace a command targets in this sequence:

1. `--project / -p <id>` flag on the command line (explicit override).
2. `.ortim/` in the current directory.
3. `.ortim/` in any parent directory.
4. `current` pointer in `~/.ortim/registry.json` (set by `ortim use <id|name>`).
5. None found → friendly error suggesting `ortim init`.

**Managing multiple projects:**

```bash
ortim ls                       # all known workspaces; '*' marks the active one
ortim use my-project           # set the registry's `current` pointer
ortim workspace show <id>      # details for one workspace
ortim workspace archive <id>   # archive (blocks mutating commands, keeps it in the list)
```

**Legacy pool layout** (0.8 and earlier): workspaces lived under `<repo>/workspaces/<uuid>/`. 0.9+ still reads them. `ortim workspace migrate <pool-id> --to <path>` moves a pool workspace into Project Mode. New projects should use `ortim init`.

---

## 2. ortim doctor — health check

First command, always:

```bash
ortim doctor
```

Sample output (abridged):

```
Ortim doctor — Environment health check

┌─────────────────────┬────────┬───────────────────────────────────────────────┐
│ Check               │ Status │ Detail                                        │
├─────────────────────┼────────┼───────────────────────────────────────────────┤
│ Python ≥ 3.11       │   OK   │ 3.14.0                                        │
│ Active LLM provider │   OK   │ deepseek (source: config; DEEPSEEK_API_KEY set) │
│ DEEPSEEK_API_KEY    │   OK   │ set (length 35)                               │
│ ANTHROPIC_API_KEY   │  MISS  │ not set                                       │
│ Node.js             │   OK   │ v24.11.1 (T1-T4 web)                          │
│ npm                 │   OK   │ 11.6.4                                        │
│ Flutter             │   OK   │ Flutter 3.38.3                                │
│ Go                  │   --   │ not installed                                 │
│ Skills directory    │   OK   │ 7 skill file(s)                               │
└─────────────────────┴────────┴───────────────────────────────────────────────┘

required: 5/5  recommended: 4/5  optional: 5/6
```

The **Active LLM provider** row is the one that matters when an LLM call fails — it tells you which provider would be selected right now and whether the matching credential is set. The per-key rows below it are informational (the missing one may be deliberate if you picked a different provider).

Three check classes:

- **required** (FAIL = system can't run): Python version, workspace write permission, L1 principles file, audit log dir, agent prompt files.
- **recommended** (MISS = practically blocking): at least one usable LLM provider, Git binary.
- **optional** (MISS = only matters for projects in that stack): Node, Flutter, Cargo, Go, JVM.

A `MISS` / `FAIL` produces a `Fix hints` section explaining what to do.

---

## 3. First run — `ortim demo`

`ortim demo` runs the entire planning chain end-to-end with no human input. It's the fastest way to see what the system actually does.

> The demo creates a temporary pool workspace (`workspaces/<uuid>/`) so it doesn't dirty your `cwd`. Inspect it after, delete it whenever. For real projects, use `ortim init` (§4).

```bash
ortim demo
```

The default brief is an English todo CLI. Use your own:

```bash
ortim demo --brief "A small personal expense tracker. SQLite, Python, single user. Track income, expenses, monthly summary. Local only."
```

### 3.1 What the demo runs

```
Brief
  ↓ Babel (any language → structured intent JSON)
intent.json
  ↓ Analyst (PRD draft)
PRD.md
  ↓ MVP_SCOPE_LOCKING (auto-locked in demo)
scope.json
  ↓ G1 — PRD approval (auto-approved in demo)
  ↓ Architect (Call 1: tier inputs; Call 2: RFC)
RFC.md + golden_path_inputs.json
  ↓ G2 — RFC approval (auto-approved in demo)
  ↓ Orchestrator (Task DAG)
task_dag.json + tasks/T-001.md ... T-NNN.md
  → tasks_ready
```

The last line of output prints the pool workspace path, e.g. `workspaces/2050c9291eb7`. Open it:

```bash
cd workspaces/2050c9291eb7
ls
# PRD.md  RFC.md  intent.json  scope.json  golden_path_inputs.json  state.json  task_dag.json  tasks/
```

> Pool mode is demo-only. In a real project these files sit under `<your-dir>/.ortim/` (§4).

### 3.2 What each artifact is for

| File | What it holds | Who wrote it |
|---|---|---|
| `intent.json` | Structured intent extracted from the brief (goal, must_have, user_stack_hints) | Babel |
| `PRD.md` | Human-readable product requirements doc | Analyst |
| `scope.json` | Phase + priority assignment per feature | `ortim scope` (auto in demo) |
| `golden_path_inputs.json` | Tier scorer inputs (auth, scale, app_class, ...) | Architect Call 1 |
| `RFC.md` | Architecture decision doc — tier, stack, modules, risks | Architect Call 2 |
| `task_dag.json` | DAG of atomic work packages | Orchestrator |
| `tasks/T-NNN.md` | Per-task brief that the Worker reads | Orchestrator |
| `state.json` | Project state machine history | runtime |

Print any to the console with `ortim show --artifact prd|rfc|scope|intent|stack` (from inside the workspace).

### 3.3 Cost check

```bash
cd workspaces/<demo-id>
ortim retro
```

Token usage + USD cost table. A planning-only demo is typically ~$0.01 on DeepSeek; with Architect on Anthropic, ~$0.05–0.10.

---

## 4. Real project — `ortim init` to DONE

The demo is "watch it work"; a real project starts with `ortim init` in your own project directory. From 0.9 forward, every command is cwd-aware — the workspace is resolved from `.ortim/` in the current or parent directory; you do not pass UUIDs.

### 4.1 Initialize the workspace

```bash
mkdir ~/dev/task-tracker && cd ~/dev/task-tracker
ortim init "A small task tracker CLI in Python with SQLite, single user, local only."
```

Long briefs: shell heredoc or `$(cat brief.txt)`. The default name is the directory's name; override with `--name`.

Output:

```
Initialized 7f3a2b9c1d4e (task-tracker, greenfield)
Path: /home/you/dev/task-tracker
State: intake

Next: ortim run (Babel + Analyst; configure a provider first via `ortim config init`)
```

A `.ortim/` directory now exists in `cwd`. Every subsequent command — `run`, `status`, `scope`, `tasks`, `run-all`, ... — picks up this workspace automatically when run from this directory or any of its subdirectories.

**Brownfield (existing codebase):** if the directory already contains manifest files (`package.json`, `pyproject.toml`, `Cargo.toml`, `go.mod`, `pubspec.yaml`, ...), `ortim init` auto-enters brownfield mode — it scans the codebase, detects framework/language, skips Architect Call 1, and goes straight to RFC drafting. Manual override: `--greenfield` (treat as empty directory) or `--brownfield` (force codebase scan).

### 4.2 Babel + planning

```bash
ortim run
```

No positional UUID — the command resolves `.ortim/` from `cwd`. If you're elsewhere, pass `--project <id>` or run `ortim use <id>` to set the active context.

`run` calls the appropriate agent for the current state. The first call runs Babel → produces `intent.json` → state advances to `PRD_DRAFTING`.

Default behavior: with **dialog mode off**, `run` chains Babel + Analyst and leaves you at `MVP_SCOPE_LOCKING`. With dialog mode on (M2 conversational intake), each dialog state is handled explicitly via `ortim refine` + `ortim lock`.

### 4.3 Scope locking — Phase 1.1

When the PRD is drafted, state becomes `MVP_SCOPE_LOCKING`. `scope.json` auto-seeds (must_have → phase 1, nice_to_have → phase 2). Now the decision:

```bash
ortim scope
```

Interactive table + per-feature phase prompt. Hit Enter to accept defaults.

Headless (CI or quick-use):

```bash
ortim scope --set "social login=2" --lock
```

`--set "<substring>=<phase>"` can repeat. `--lock` skips the interactive prompt and advances to `PRD_AWAITING_APPROVAL`.

**Why this step matters:** Architect Call 2's RFC §7 Module Breakdown is **two-tier** (Phase 1 MVP / Phase 2+ Deferred). Phase 2 features get RFC entries but no DAG tasks — they wait for a future `ortim extend` cycle.

### 4.4 G1 — PRD approval

```bash
ortim show --artifact prd
```

Read it. Every must_have feature represented? Non-goals clear? Any `open_questions` that need answering?

Approve:

```bash
ortim advance prd_approved --note "reviewed"
```

> `advance`, `execute`, and `extend` take multiple positional args (state alias / task id / brief), so the workspace ID moved to a `--project / -p` flag. From inside the workspace, the flag is unnecessary; from elsewhere: `ortim advance prd_approved -p 7f3a2b9c1d4e --note "..."`.

To revise: `ortim refine "feedback"` (dialog mode) or `ortim advance prd_drafting` to roll back, then edit `PRD.md` directly or rerun `ortim run`.

### 4.5 Architect — RFC + tier

```bash
ortim run
```

Architect Call 1 extracts `GoldenPathInputs` from the PRD. If Babel captured `user_stack_hints` (e.g., "Flutter", "SQLite"), they override the scorer's `app_class` and tier hints. The deterministic scorer then picks one of the 12 tiers, and Architect Call 2 drafts `RFC.md`.

### 4.6 G2 — RFC approval

```bash
ortim show --artifact rfc
```

Check:
- §2 **Selected Tier** — correct family (T0–T6 web / M0–M2 mobile / D0–D1 desktop)?
- §4 **Tech Stack** — names the libraries you actually want? "user-named" tags present where applicable?
- §7 **Module Breakdown** — two-tier (Phase 1 | Phase 2+)?
- §9 **Risks** — non-empty, ideally three or more, with concrete mitigations (not "monitor closely")?

To revise: `ortim advance rfc_drafting` and edit `RFC.md` directly. Otherwise:

```bash
ortim advance rfc_approved --note "reviewed"
```

### 4.7 Orchestrator — DAG generation

```bash
ortim run
```

Orchestrator reads the RFC and produces atomic tasks. Validators (no cycles, no missing deps, `module_scope` ⊂ RFC §7, `phase` ∈ {1, 2+}) catch violations and retry up to 3×.

```bash
ortim tasks
```

Task list + dependency table. Each task lives under `.ortim/tasks/T-NNN.md`.

### 4.8 Worker — execution

```bash
ortim run-all --phase 1
```

`--phase 1` runs MVP tasks only (Phase 2+ stays `PENDING`). Default is sequential, with Git branch isolation per task.

For each task, Worker:
1. Reads RFC + task brief + matching skills.
2. Writes code (FILE_BLOCK-formatted `WorkerOutput`).
3. Passes the sandbox structural validator (module-scope check).
4. Runs the test command (`.ortim.env`'s `ORTIM_TEST_CMD`).
5. Routes through the Reviewer chain (Code / Security / Test / Perf).
6. `APPROVED` → DONE; `REJECT` → up to 3 retries with feedback injected; `AWAITING_HITL` → halt.

Generated code lands in `cwd` root (`auth/`, `src/`, ...); metadata stays in `.ortim/`.

### 4.9 Progress monitoring

```bash
ortim status        # state + history
ortim drift-check   # RFC ↔ DAG ↔ status integrity
ortim retro         # cost + retry rate + HITL escalations
```

Once everything is DONE, `ortim run-all` also auto-drafts a `README.md` for the generated project.

---

## 5. Trust calibration — the AI wrote it, you sign it

Ortim's deterministic state machine + audit trail answer "what did the AI do?" — but **the decision is yours**. At every gate, ask:

### G1 — PRD approval
- Is any feature listed that isn't in your brief? **Reject.** Babel/Analyst occasionally invent features; rare, but real.
- Are open_questions unanswered? If so, the Architect will make assumptions. Answer them first.
- Does `inferred_compliance` (KVKK/GDPR) match your actual obligations?

### G2 — RFC approval
- Tier correct? Self-audit: "a small backend → T4 monolith makes sense; T5 microservices doesn't."
- Stack matches what you named? §4 should tag "user-named" where applicable.
- §9 Risks — real risks with concrete mitigations, or boilerplate? "Monitor closely" is not a mitigation.
- §10 Decisions Locked — each pick has a `rationale`.
- §11–§16 (deployment, observability, security, test strategy, DR, runbook) — any `**[NEEDS-INPUT]**` tags must be filled by you. Architect doesn't know your infrastructure.

### G3 — Schema/migration approval (auto-triggered)
- If a schema or migration task lands in the DAG, state goes to `SCHEMA_AWAITING_APPROVAL`. Read the SQL. Production downtime risk?

### G7 — Budget gate (auto-triggered)
- `ORTIM_BUDGET_CAP_USD` exceeded → state `BUDGET_AWAITING_APPROVAL`. Raise the cap or pause.

### Task-level — AWAITING_HITL
- A task that fails 3× or trips a SecurityReviewer hard veto ends in `AWAITING_HITL`. Manual intervention required ([failure-recovery.md](../runbook/failure-recovery.md)).

### Audit log
- `.ortim/audit.jsonl` — every LLM call, every state transition, every gate. Hash-chained; `ortim audit-verify` detects edits.

### What the Reviewer actually catches
- L1 principle violations (missing DI, side effects in module init).
- Acceptance criteria mismatches.
- Module boundary leaks (raw imports across modules instead of barrels).
- SQL injection, XSS, hardcoded secrets (SecurityReviewer).
- Missing or broken test infrastructure (Item 24 mode).

### What the Reviewer does NOT catch
- Logical bugs (the algorithm is wrong).
- Business-rule gaps (user said X, PRD wrote Y).
- UX issues (frontend visual problems, content mismatches).

**Bottom line:** the reviewer chain is a code-quality + security floor, not a substitute for code review. For production, run the chain *plus* your own review, integration tests, and a canary deploy.

---

## 6. Common problems + fixes

### 6.1 "DEEPSEEK_API_KEY is not set (resolved provider: 'deepseek')"

Three fix paths — pick whichever fits:

1. **Run the wizard** (recommended, works from any directory): `ortim config init`.
2. **Set the env var** in your shell (`export DEEPSEEK_API_KEY=...`) or in a `.env` file in the directory where you'll run `ortim`. New terminal after editing if env vars look cached.
3. **Use a different provider** for this run: `ortim run --provider ollama` (local, no key) or `--provider anthropic`.

If you intended a different provider and got the wrong one, `ortim config show` prints the resolved provider and where each value came from. `ortim doctor` includes an "Active LLM provider" row for quick triage.

**Before 0.9.4** there was a bug where `.env` in your project directory was silently ignored on PyPI installs (the lookup walked from the install location, not your cwd). Upgrade to ≥ 0.9.4 — `pip install --upgrade ortim` — if you hit "ANTHROPIC_API_KEY not set" despite a valid `.env` in cwd.

### 6.2 Architect picked the wrong tier

- "Why T5 instead of T4?" → likely `team_size: large` or `expected_scale: large`. Open `.ortim/golden_path_inputs.json` and check.
- "T2 BaaS chosen but I want self-hosted" → make sure your brief names a self-hosted technology explicitly ("PostgreSQL", "FastAPI", "SQLite"), not generic terms ("database"). Babel captures named technologies into `user_stack_hints`.

### 6.3 A task is stuck in AWAITING_HITL

Two common reasons:
- **Sandbox / criterion failure** — Worker failed 3 attempts. Look at `.ortim/audit.jsonl` filtered to the task ID. `last_review_reasons` in `.ortim/task_status.json` shows the recurring issue.
- **`test_infrastructure_unavailable`** — the test runner is missing or broken (Item 24 mode). Check `.ortim.env`'s `ORTIM_TEST_CMD`.

Recovery paths: [failure-recovery.md](../runbook/failure-recovery.md).

### 6.4 Cost spike

Set `ORTIM_BUDGET_CAP_USD` (e.g., 2.00). When exceeded, G7 trips and the run pauses.

Typical spike sources:
- Architect on Anthropic + RFC drafting retried (drift validator fired).
- One task hit max retries.
- Very large PRD/RFC (high token count).

`ortim retro` breaks down spend by category.

### 6.5 State machine error — "Cannot transition X -> Y"

You tried to skip a gate. `ortim states` lists every legal transition. Common back-steps are allowed:
- `prd_awaiting_approval` → `prd_drafting` (edit the PRD).
- `mvp_scope_locking` → `prd_dialog` (rewrite the PRD).
- `rfc_awaiting_approval` → `rfc_drafting`.
- `executing` → `paused`.

### 6.6 "command not found: ortim"

Venv not activated. `.venv/Scripts/activate` (Windows) or `source .venv/bin/activate` (Unix).

Or editable install is stale: `pip install -e .` again.

### 6.7 Workspace eating disk

`node_modules`, `.venv`, `target` (Rust) etc. live under `cwd` root (project mode). Dependency dirs grow.

```bash
ortim ls                                # all known workspaces
ortim workspace archive <id>            # block mutating commands, keep in list
ortim workspace cleanup --older-than 30 --archived-only --yes
                                        # delete .ortim/ for archived workspaces older than 30 days
ortim workspace doctor                  # registry ↔ disk consistency scan
```

In Project Mode, `cleanup` only deletes `.ortim/` — your generated code is untouched. In pool legacy workspaces, the whole directory is deleted.

---

## 7. Where to go next

- **The value pitch:** [`docs/why-ortim.md`](../why-ortim.md) — what the structural choices buy you, comparison vs Cursor/Aider/Claude Code.
- **Architecture deep dive:** [`Ortim_Architecture.md`](../../Ortim_Architecture.md) — agents, state machine, audit, RAG.
- **Tier selection logic:** [`docs/golden-paths/`](../golden-paths/) — reference doc per tier.
- **Authoring skills:** [`docs/skills/authoring-guide.md`](../skills/authoring-guide.md) — inject project-specific patterns into Worker/Reviewer prompts.
- **Brownfield (existing codebase):** `cd <project> && ortim init "<brief>"` — manifest-based auto-detection. `ortim inspect` shows the baseline.
- **Iteration:** `ortim extend "<feature brief>"` from inside a DONE project. From elsewhere: `ortim extend "..." -p <id>`.
- **Multiple workspaces:** `ortim ls` (list), `ortim use <id|name>` (active context), `ortim workspace {show,archive,cleanup,doctor,migrate}`.
- **Pool → project migration (legacy):** `ortim workspace migrate <pool-id> --to <path>` — moves a pool workspace to project mode (rollback-safe `--copy` default).
- **Audit + drift:** `ortim drift-check`, `ortim audit-verify`.
- **Roadmap + open items:** [`docs/plans/2026-Q2-roadmap.md`](../plans/2026-Q2-roadmap.md), [`docs/backlog.md`](../backlog.md).

---

## Cheatsheet

Project mode is the default — commands resolve `.ortim/` from `cwd`. Examples below assume you're inside the project directory.

```bash
# Health + setup
ortim doctor

# Quick tour (pool workspace, no input)
ortim demo

# New project
mkdir ~/dev/cool && cd ~/dev/cool
ortim init "<brief>"               # create .ortim/ (brownfield: auto-detect)
ortim run                          # Babel + Analyst → MVP_SCOPE_LOCKING
ortim scope --lock                 # accept default phase split + advance to G1
ortim show --artifact prd
ortim advance prd_approved         # advance/execute/extend: 1 positional + -p flag
ortim run                          # Architect → RFC_AWAITING_APPROVAL
ortim advance rfc_approved
ortim run                          # Orchestrator → tasks_ready
ortim run-all --phase 1            # Worker × N

# Observability (cwd-aware)
ortim status
ortim tasks
ortim retro
ortim drift-check
ortim show --artifact rfc

# Iteration
ortim refine "<feedback>"          # dialog-mode refine
ortim extend "<new feature>"       # DONE → delta cycle

# Workspace management (from anywhere)
ortim ls                           # all known workspaces; '*' = active
ortim use cool                     # set active pointer
ortim status -p 7f3a2b9c1d4e       # target a specific workspace
ortim workspace archive <id>
ortim workspace cleanup --older-than 30 --archived-only --yes
```

That's the tour. Hit a wall or find a gap? Open an issue: [github.com/orhanurullah/ortim/issues](https://github.com/orhanurullah/ortim/issues).
