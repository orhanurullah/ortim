# Ortim — Failure Recovery Runbook

> What to do when things go wrong. Start here if you've finished the tutorial and a real project hit a wall.

Turkish-language original: [`docs/tr/runbook/failure-recovery.md`](../tr/runbook/failure-recovery.md).

Contents:
0. [Project mode command quick reference](#0-project-mode-command-quick-reference)
1. [Diagnose first](#1-diagnose-first)
2. [A task stuck in AWAITING_HITL](#2-a-task-stuck-in-awaiting_hitl)
3. [Worker failed after 3 attempts](#3-worker-failed-after-3-attempts)
4. [G7 budget gate tripped — can't continue](#4-g7-budget-gate-tripped--cant-continue)
5. [Old workspace fails to load (schema migration)](#5-old-workspace-fails-to-load-schema-migration)
6. [Architect picked the wrong stack](#6-architect-picked-the-wrong-stack)
7. [Sandbox rejecting writes (`module_scope` violation)](#7-sandbox-rejecting-writes-module_scope-violation)
8. [State machine "Cannot transition" error](#8-state-machine-cannot-transition-error)
9. [Nothing works — restart the workspace](#9-nothing-works--restart-the-workspace)

---

## 0. Project mode command quick reference

From Ortim 0.9, commands are **cwd-aware**: they discover the active workspace from the current directory (or its parents). Examples below assume you're running from inside the project directory.

| Command class | Pattern | Example |
|---|---|---|
| Read commands (`status`, `tasks`, `inspect`, `gates`, `show`, `extensions`, `retro`, `drift-check`) | `<cmd>` or `<cmd> <id>` (legacy pool fallback) | `ortim status` · `ortim retro` |
| Single-mutating (`run`, `run-all`, `refine`, `lock`, `scope`, `budget`, `rescan`, `baseline`) | `<cmd>` or `<cmd> <id>` (legacy pool fallback) | `ortim run` · `ortim scope --lock` |
| Multi-arg (`advance`, `execute`, `extend`) | `<cmd> <other-arg> [-p <id>] ...` | `ortim advance prd_approved --note "x"` |
| Workspace management | `ortim ls` · `ortim use <id\|name>` · `ortim workspace {show,archive,cleanup,doctor,migrate}` | `ortim use cool-project` |

From outside the project directory, or when multiple workspaces exist, the `--project / -p <id>` flag works on every command. Legacy pool workspace IDs also resolve as positional or via the flag.

Metadata location: Project Mode → `<your-dir>/.ortim/` (state.json, audit.jsonl, tasks/, ...). Pool Mode → `workspaces/<id>/`.

---

## 1. Diagnose first

Don't act before you know what happened. From the project directory:

```bash
ortim status        # state machine + history
ortim retro         # cost + retry rate + HITL escalations
ortim drift-check   # RFC ↔ DAG ↔ status alignment
```

Deeper:

```bash
# Audit log (project mode: .ortim/audit.jsonl)
type .ortim\audit.jsonl                           # Windows
# cat .ortim/audit.jsonl                          # Unix

# Filter audit log by task ID
findstr "T-005" .ortim\audit.jsonl                # Windows
# grep "T-005" .ortim/audit.jsonl                 # Unix

# Task DAG overview
ortim tasks

# Per-task status (last_review_reasons, retry count, current status)
type .ortim\task_status.json                      # Windows
# cat .ortim/task_status.json | jq .              # Unix
```

For pool legacy workspaces, the audit log is at `workspaces/<id>/audit.jsonl` or `runtime/audit/<date>.jsonl`.

`state.json` is always the ground truth — opening it directly (`.ortim/state.json` in project mode, `workspaces/<id>/state.json` in pool mode) is a legitimate diagnostic step.

---

## 2. A task stuck in AWAITING_HITL

### Symptom

`ortim tasks` shows one or more tasks in `AWAITING_HITL`. `ortim run-all` stops cleanly at that state.

### Identify the cause

Open `.ortim/task_status.json` (project mode) or `workspaces/<id>/task_status.json` (pool). It records each task's status, `last_review_reasons`, and retry count. Five tags to recognize:

| Tag | Meaning | Recovery path |
|---|---|---|
| `[sandbox]` | Worker wrote outside `module_scope` | §7 |
| `[criterion]` | An acceptance criterion failed | §2.1 |
| `[test_infrastructure_unavailable]` | Test runner missing or broken | §2.3 |
| `[security_veto]` | SecurityReviewer hard-vetoed | §2.4 |
| `[criteria_design_failure]` | The criterion itself is ambiguous | §2.5 |

### 2.1 Criterion fails — Worker can't satisfy it

First, understand where the code falls short:

```bash
# Worker output + Reviewer verdicts are in the audit log
findstr "T-005" .ortim\audit.jsonl                      # Windows
# grep '"T-005"' .ortim/audit.jsonl | jq .              # Unix

# Current code state on the task's branch
git log --all --oneline -- '*T-005*'
```

When code was written but doesn't meet expectations:

**Rerun the task (recommended)**

```bash
ortim execute T-005 --max-attempts 3
```

> To give Worker a signal it can't infer on its own, open `.ortim/tasks/T-005.md` and tighten the acceptance criteria. Then `ortim execute T-005`.

**Manual code fix:** committing the fix directly bypasses the Worker; the Reviewer chain still runs. There's currently no "skip code emission, use existing" signal for Worker, so mixing manual commits with `ortim execute` leaves the audit history inconsistent. Prefer rerunning.

### 2.2 Criterion is ambiguous — Reviewer correctly rejected

If a Reviewer verdict shows `status: unverifiable` + mode `criteria_design_failure`, Orchestrator emitted a bad criterion (Hard Rule 10 violation — "readable", "user-friendly", and similar vague words are banned).

Edit it manually:

```bash
# Open .ortim/tasks/T-005.md and fix the "Acceptance Criteria" list
# Ambiguous:  "stdout shows todos in readable format"
# Concrete:   "stdout matches /^(\[ \] [0-9a-f-]{36} .+\n)*$/"

ortim execute T-005
```

Or regenerate the DAG (cleaner, but pays the Architect/Orchestrator cost again):

```bash
ortim advance rfc_approved
ortim run            # Orchestrator re-runs
```

### 2.3 `test_infrastructure_unavailable`

Worker wrote tests, but the test runner returned non-zero (runner missing or broken).

```bash
# .ortim.env (project mode: at cwd root)
type .ortim.env                                # Windows
# cat .ortim.env                               # Unix
# ORTIM_TEST_CMD=npx vitest run
```

Pool mode: `workspaces/<id>/.ortim.env`.

Is the command correct? Are the relevant packages installed?

```bash
npm install        # or pip install -r requirements.txt
# manually run the test command
npx vitest run
```

If it works:

```bash
ortim execute T-005
```

If `ORTIM_TEST_CMD` is wrong, edit `.ortim.env` directly + rerun.

### 2.4 `security_veto`

SecurityReviewer issued a hard veto (hardcoded secret, SQL injection, eval, etc.). Inspect the verdict:

```bash
findstr "T-005" .ortim\audit.jsonl | findstr "security"   # Windows
# grep '"T-005"' .ortim/audit.jsonl | grep security        # Unix
```

The verdict names a concrete issue. Either edit `.ortim/tasks/T-005.md` to add an explicit criterion (e.g., "auth secret read from environment variable") and rerun, or fix the code manually and skip ahead.

### 2.5 `criteria_design_failure`

Orchestrator emitted a criterion that violated Hard Rule 10 (ambiguous wording). Manually edit `.ortim/tasks/T-005.md` and rerun. If the same pattern shows up repeatedly, the systemic fix is tightening Orchestrator's banned-words list in `agents/orchestrator.md`.

---

## 3. Worker failed after 3 attempts

3 attempts is the default max retry budget. State transitions to `AWAITING_HITL` (§2). To grant another 3 attempts:

```bash
ortim execute T-005 --max-attempts 3
```

If three attempts already failed and the next round fails too, the system is signaling: either the criterion is ambiguous, the code is too complex for the Worker LLM, or the task is over-scoped.

Remedies:
- **Split the task** — manually edit `.ortim/tasks/T-005.md` into 2–3 smaller tasks; patch `.ortim/task_dag.json` accordingly.
- **Upgrade the Worker LLM** — `WORKER_PROVIDER=anthropic` or `WORKER_MODEL=claude-opus-4` in `.env`.
- **Feed Reviewer feedback back into PRD/RFC** — sometimes the feature design itself is wrong, not the implementation.

---

## 4. G7 budget gate tripped — can't continue

### Symptom

```
G7 — Budget cap breached.
Spent $2.34 / cap $2.00 (117%)
```

State: `BUDGET_AWAITING_APPROVAL`. `run-all` halts.

### Three choices

**Continue (accept the overage):**

```bash
ortim advance budget_approved --note "approved overage for T-005-T-008"
```

**Raise the cap first:**

```bash
# In .env
ORTIM_BUDGET_CAP_USD=5.00
# open a fresh terminal so env reload picks up the new value
ortim advance budget_approved
```

**Pause:**

```bash
ortim advance paused --note "budget exceeded; reviewing"
```

After pausing, `ortim retro` breaks down spend by category. Where did it spike?
- Architect retried (drift validator fired).
- One task burned its full retry budget.
- PRD/RFC very large (high token count).

---

## 5. Old workspace fails to load (schema migration)

### Symptom

```
pydantic_core._pydantic_core.ValidationError: ...
```

The on-disk `state.json` or `scope.json` was written with an older schema; the current code expects new fields.

### Recovery

Pydantic `default` values should make older JSON load-compatible (older files get the new fields populated with defaults). If you're still seeing a hard error:

1. **Back up the workspace:**
   ```bash
   # Project mode: only the metadata
   cp -r .ortim .ortim.bak                       # Unix
   xcopy /E /I .ortim .ortim.bak                 # Windows
   # Pool mode: the whole directory
   # cp -r workspaces/<id> workspaces/<id>-backup
   ```

2. **Edit the JSON manually** — add missing fields:
   ```json
   // Example: pre-Phase-1.1 state.json after the Phase-1.1 schema bump
   {
     ...
     "user_stack_hints": [],
     "phase": 1
   }
   ```
   Project mode: `.ortim/state.json`. Pool mode: `workspaces/<id>/state.json`.

3. **Log the migration:**
   ```bash
   echo "$(date) — manual migration v0.7 → v0.8" >> .ortim/MIGRATIONS.md
   ```

> **Automatic migration tooling is deferred to Phase 4** (roadmap item 3.2). For now, migration is manual.

---

## 6. Architect picked the wrong stack

### Symptom

RFC §4 names a technology you didn't ask for (e.g., "I said SQLite, it wrote PostgreSQL").

### Diagnose

```bash
type .ortim\intent.json | findstr "user_stack_hints"     # Windows
# cat .ortim/intent.json | grep -A 10 user_stack_hints   # Unix
```

Is `user_stack_hints` empty, or does it list what you said?

**Empty:** Babel didn't extract the hint. Make the brief more concrete — name the technology explicitly ("PostgreSQL", "SQLite", "FastAPI") instead of generic terms ("database", "API").

**Populated but RFC overrode it:** Phase 1.2 B-2 fix is supposed to cover this. If you're still seeing the bug, file an issue with a reproduction.

### Fix

Roll back to `rfc_drafting`, edit `RFC.md` directly or rerun Architect:

```bash
ortim advance rfc_drafting
ortim run
```

Or edit `.ortim/RFC.md` manually and approve:

```bash
# Open .ortim/RFC.md, fix §4 by hand
ortim advance rfc_awaiting_approval
ortim advance rfc_approved --note "manually edited stack section"
```

---

## 7. Sandbox rejecting writes (`module_scope` violation)

### Symptom

In `.ortim/audit.jsonl`:
```
executor_sandbox_violation: Worker tried to write 'auth/foo.ts' but module_scope is 'tasks'
```

### Why

Worker tried to ship a file in a module other than the one declared in the task's `module_scope`. The sandbox correctly rejected it — L1 module boundary defense.

Two possible root causes:
- **Orchestrator bug:** task description bridges two modules. DAG needs regeneration.
- **Worker drift:** the Architect hinted at the right path but the Worker chose another.

### Fix

First, let Item 15a's sandbox feedback retry run — it injects a structured correction into the next attempt. If three attempts produce the same violation:

```bash
# Manually edit the task brief to make the expected path explicit
# .ortim/tasks/T-005.md → "Create the file `tasks/repository.ts` (NOT auth/...)"
ortim execute T-005
```

Or regenerate the DAG (Orchestrator re-runs):

```bash
ortim advance rfc_approved
ortim run
```

---

## 8. State machine "Cannot transition" error

### Symptom

```
InvalidTransition: Cannot transition prd_drafting -> rfc_drafting.
Allowed: ['failed', 'mvp_scope_locking']
```

The state machine is blocking you on purpose — you tried to skip a gate.

### Recovery

List legal transitions:

```bash
ortim states
```

Backward transitions are legal in many cases (post-Phase-1.1):
- `prd_awaiting_approval` → `prd_drafting`
- `mvp_scope_locking` → `prd_dialog` or `prd_drafting`
- `rfc_awaiting_approval` → `rfc_drafting`
- `executing` → `paused`
- `paused` → many states

Manually setting a state is fine: `ortim advance <state>` runs the transition.

---

## 9. Nothing works — restart the workspace

Sometimes the fastest fix is starting clean.

**Project mode** (recommended): archive the metadata or start in a fresh directory.

```bash
# Option A: keep the directory, reset just the metadata
mv .ortim .ortim.broken-$(date +%Y%m%d)         # Unix
# Windows: rename .ortim to .ortim.broken-YYYYMMDD
ortim init "$(cat brief.txt)"                    # fresh .ortim/

# Option B: archive in the registry, open a new directory
ortim workspace archive <id>
mkdir ~/dev/cool-project-v2 && cd ~/dev/cool-project-v2
ortim init "$(cat brief.txt)"
```

**Pool legacy:**

```bash
mv workspaces/<id> workspaces/<id>-broken-$(date +%Y%m%d)
mkdir ~/dev/cool-project && cd ~/dev/cool-project
ortim init "$(cat brief.txt)"
```

**Carry over from the old workspace:**
- `.ortim/intent.json`, `.ortim/PRD.md`, `.ortim/RFC.md` — manually copy, then advance the new project through the gates.
- `.ortim/task_dag.json` — usually cleaner to regenerate by re-running Orchestrator.

**Do NOT carry over:**
- `.ortim/state.json` — schema may have changed.
- `.ortim/audit.jsonl` — would corrupt the new project's hash chain.

---

## Asking for help

When opening an issue, include:
- `ortim doctor` output.
- `ortim status` + `ortim retro` + `ortim drift-check` (from the project directory).
- Last 30 lines of `.ortim/audit.jsonl` (scrub PII first).
- The brief used to reproduce the issue.

GitHub: [github.com/orhanurullah/ortim/issues](https://github.com/orhanurullah/ortim/issues)

---

Related documents:
- [Tutorial](../tutorial/getting-started.md) — start from scratch.
- [Why Ortim](../why-ortim.md) — value framing + comparison vs alternatives.
- [Architecture](../../Ortim_Architecture.md) — how the system works.
- [Backlog](../backlog.md) — open issues and their current status.
