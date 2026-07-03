# Why Ortim

> Coding with a bare LLM works in a demo and fails at production scale. This document explains the structural choices that turn an unreliable LLM into a reviewable software pipeline, and where Ortim sits next to Cursor, Aider, Claude Code, and Continue.dev.

If you've shipped real code with an LLM, you've met the same wall everyone meets. This is the design rationale for trying to climb it differently.

---

## 1. The problem with prompting a model and hoping

Spend a week building a real project with raw LLM prompts and you collect the same defects:

**The model forgets what it already wrote.** It re-implements `parseQuery` because the conversation scrolled past the original. Two functions with the same name and slightly different behavior now exist in your codebase, and which one a caller hits depends on the import order.

**Errors loop.** Test fails → fix attempt → new test fails → fix attempt → first test fails again. By the third turn, the LLM has invented an explanation that connects all three failures and is now editing files unrelated to any of them.

**Tests get skipped silently.** "I'll add tests in the next step" — the next step never comes. Or worse, the LLM writes `expect(fn).rejects` without wrapping in a Promise, the test runner throws a TypeError, and the LLM reports "test passed" because exit code was zero.

**Architecture inflates.** "Build me a todo app" gets you a microservices split across an API gateway, an auth service, and an event bus, because the model has seen more enterprise tutorials than weekend projects.

**Libraries get hallucinated.** "use psycopg3" with imports from a function that exists only in psycopg2, or a JSX prop that was deprecated three versions ago. The code typechecks against the model's prior probability distribution, not your installed packages.

**Approval fatigue sets in.** By the fourth time the model asks "should I add input validation?" you've started clicking yes without reading, which means the fifth time — when it's asking to drop the staging database — you don't notice the difference.

**Compliance is invisible.** When the model wrote that code that ended up in production, what was the prompt? What model version? What was the reasoning? Six months from now, when a customer asks why their PII was logged: no audit trail.

These aren't prompting issues. They're **production-engineering issues**: state, isolation, contracts, retries, observability, audit. Patching them with longer prompts is patching a load-bearing wall with paint.

---

## 2. What Ortim does differently

Ortim treats AI coding as a pipeline that needs the same primitives a CI/CD pipeline needs. Each defect above gets a structural answer, not a prompt-engineering answer.

### 2.1 A state machine you can't talk your way past

Every project moves through an explicit state machine:

```
intake → babel → intake_dialog → stack_dialog → prd_dialog → prd_drafting
       → prd_awaiting_approval → prd_approved
       → rfc_drafting → rfc_awaiting_approval → rfc_approved
       → tasks_generating → tasks_ready → executing → done
```

Two transitions are **mandatory human approvals**: G1 (PRD), G2 (RFC). Five more (G3 schema, G4 external API, G5 security ≥ medium, G6 deploy, G7 budget) fire automatically when conditions match. Trying to advance the state from `prd_drafting` to `executing` doesn't fail silently — it raises `InvalidTransition` with the legal next states listed.

The LLM cannot route around this. It writes code; the state machine decides what runs next.

### 2.2 A deterministic architecture picker

Tier selection is **not an LLM call**. Architect Call 1 extracts numeric and categorical signals from the PRD (team size, scale, latency target, auth complexity, ...). A rule-based scorer in `ortim/architecture/golden_paths.py` then picks one of 12 canonical architectures — T0–T6 web, M0–M2 mobile, D0–D1 desktop.

A `tier_score` table is emitted with the picked tier, the runner-up, and the gap. Two LLM runs on the same PRD produce the same tier. You can override by editing the inputs and rerunning, or by directly choosing a tier with `ortim advance rfc_drafting` and editing `RFC.md`.

### 2.3 A task DAG validated outside the LLM

Orchestrator emits a DAG (`task_dag.json`) of atomic work packages. Then runtime validators check four invariants:

1. **No cycles.**
2. **No missing dependencies.**
3. **`module_scope` ⊂ RFC §7 modules.** A task cannot ship code into a module the RFC didn't declare.
4. **`phase` ∈ {1, 2+}.** Phase-2 features get tasks but stay PENDING until `ortim extend` reopens them.

A violation triggers up to 3× retry. Strike out: `AWAITING_HITL`. The validators see the LLM's output as text; they don't trust it.

### 2.4 Module-scoped sandboxes (no boundary leaks)

Each task carries a `module_scope` (e.g. `"auth"`). The sandbox checks every file the Worker tries to write against that scope. Trying to ship `auth/foo.ts` while scoped to `tasks/` raises `WorkerOutOfScope` — the task fails, but the failure is captured: `last_review_reasons` gets a `[sandbox]`-tagged feedback string ("import this from auth/index.ts; do not recreate it"), which is **prepended to the next Worker attempt's prompt**. That's how the system learns from rejection instead of looping on it.

### 2.5 A reviewer chain that distinguishes "fail" from "unverifiable"

After the Worker writes code, a chain runs: Code reviewer → Security reviewer → Test reviewer → Perf reviewer. Each emits a rubric-shaped verdict (`criteria_verdicts: list[CriterionVerdict {criterion, status: pass|fail|partial|unverifiable, evidence, code_quote}]`) plus any L1 principle violations.

`unverifiable` is **not** an approval. It means the criterion as written can't be checked — usually because the test runner is missing or the criterion uses banned ambiguous words like "readable" or "user-friendly". The system surfaces `criteria_design_failure` (not Worker's fault — the criterion itself is broken) and escalates to HITL.

A verdict's `criteria_verdicts` length must equal the task's `acceptance_criteria` length. If the LLM drops a criterion (it tries occasionally, especially for static file-existence checks), a length validator catches it and the system retries with structured correction injected into the prompt. Three strikes → `RuntimeError`.

### 2.6 Hash-chained audit log

Every LLM call, every state transition, every gate decision, every hook output writes a line to `.ortim/audit.jsonl`. Each entry includes a `prev_hash` field referencing the previous entry's hash, forming a chain. `ortim audit-verify` walks the chain and flags any entry whose hash doesn't match its declared prior.

If anything in the chain was edited after the fact, verification fails — the chain has tamper-evidence whether or not you treat it as legally binding evidence.

PII redaction (KVKK/GDPR) is on by default; the redacted fields stay in the chain so the audit is still complete, but the content is hashed instead of plain text.

### 2.7 Project Mode (0.9+): cwd-aware execution

Workspaces live where your code lives:

```
~/dev/my-project/
├── .ortim/                  ← Ortim metadata (state, PRD, RFC, tasks, audit)
├── auth/                    ← Worker-written code
├── package.json
└── ...
```

Every command discovers the workspace from `cwd` (or a parent directory's `.ortim/`, or the registry's `current` pointer). No UUID arguments to memorize. Multiple workspaces? `ortim ls`, `ortim use <name>`, `ortim workspace {show,archive,cleanup}`.

This matches the pattern of `git`, `cargo`, `terraform`, `claude-code` — no surprises for anyone who's used a modern dev tool.

### 2.8 Multi-provider routing for budget realism

Each agent role can target its own LLM provider. The intended pattern is **cheap models for high-volume mechanical work, premium models for expensive judgement**:

```ini
DEEPSEEK_API_KEY=sk-...
ANTHROPIC_API_KEY=sk-ant-...

# Default everything to DeepSeek
ARCHITECT_PROVIDER=anthropic           # Architect's RFC is hard to redo
SECURITY_REVIEWER_PROVIDER=anthropic   # Catching a SQL injection is worth $0.02 extra
# Babel, Worker, Code reviewer → DeepSeek by default
```

A typical planning chain on DeepSeek-only routing is **$0.02–0.05**. The hybrid above is **$0.05–0.10**. The cost is bounded by design: G7 budget gate trips when `ORTIM_BUDGET_CAP_USD` is exceeded.

---

## 3. Concrete comparison: vanilla LLM vs Ortim

A single proof-point run from the project memory, `proofpoint-v3` (2026-05-14):

**Brief:** Turkish-language brief asking for a React + Vite + SQL.js single-page todo app with tags.

**Vanilla LLM workflow (typical pattern from prior runs):**
- 22 % first-attempt approval — the rest required re-prompting with reviewer-style critiques manually composed by the developer.
- Architecture drifted twice (proposed Node+Hono backend despite "browser-only" intent; second attempt proposed Firebase despite "no third-party storage" requirement).
- Reviewer-equivalent step skipped silently 2× (tests didn't run, but "tests passed" was reported).
- Two libraries hallucinated (`@vite/plugin-sql`, `react-testing-utils`).
- Cost: hard to measure cleanly because the loop wasn't a single chain — but the developer spent ~3 hours on a 1-hour scope.

**Ortim run (same brief, fresh workspace `ed9f6074f1b8` → after Items 40/41/42/46 shipped → `proofpoint-v3`):**
- **6 of 6 tasks DONE**, project complete, README auto-drafted.
- ~83 % first-attempt approval rate. One Worker retry on a UI test scoping issue (auto-recovered via Item 15a sandbox feedback loop).
- No architecture drift. No hallucinated libraries (`_FRAMEWORK_PACKAGES` map installs only declared deps).
- No silent test skips (Item 24 distinguishes `unverifiable` from `pass`; the developer was paged when test infrastructure was missing).
- Cost: **~$0.16** total for the day across three proof-point runs. The successful single-run was ≈$0.05.
- Total wall time: ~25 minutes including the developer reading the PRD and RFC.

**Different runs, same direction.** Across the documented proof-point series the pattern holds: 60–80 % first-attempt approval in greenfield, sub-$0.10 per planning chain, zero hallucinated libraries on the 12-tier stable set. The raw run-by-run forensic log is kept internally.

This isn't free — Ortim asks for two human approvals (G1, G2) per project that bare LLM coding doesn't. You're trading roughly 5 minutes of focused reading per gate for the structural safety. If your project is one-prompt-throwaway, this trade is not worth it. If you're shipping something that has to last a year, it is.

---

## 4. Where Ortim sits next to the alternatives

Ortim is not a replacement for an IDE coding assistant. It's a different shape of tool. The comparison below is uncharitable to all four (every tool ships fast; treat as a snapshot, not a final verdict).

| | **Cursor** | **Claude Code** | **Aider** | **Continue.dev** | **Ortim** |
|---|---|---|---|---|---|
| **Primary mode** | IDE-integrated chat + autocomplete | CLI agent with file/shell access | CLI git-coupled editor | IDE plugin (custom models) | CLI pipeline: brief → PRD → RFC → DAG → code |
| **Unit of work** | A file or a function | A task in conversation | A commit | A code suggestion | A validated task in a DAG |
| **State persistence** | Conversation history | Conversation history + project memory | Git log | None (per-session) | Hash-chained state machine + audit log |
| **Architecture choices** | The model picks | The model picks | The user types them in | The model picks | Deterministic scorer over PRD-derived signals |
| **Approval points** | None enforced | None enforced | User reviews each commit | None enforced | G1, G2 mandatory + 5 conditional gates |
| **Test discipline** | Suggested, manual | Can be prompted | Manual | None | Reviewer chain treats skip ≠ pass |
| **Audit / compliance** | None | Conversation log | Git history | None | Hash-chained JSONL, tamper-evident, PII-redacted |
| **Budget bound** | None | None | None | None | G7 budget gate trips at `ORTIM_BUDGET_CAP_USD` |
| **Brownfield handling** | Yes (your editor) | Yes | Yes | Yes | Yes — manifest auto-detect + import-graph extraction |
| **Best at** | Live coding with you | Open-ended exploration | Iterative committed changes | Inline assist | Greenfield + brownfield pipelines that have to be defensible later |
| **Worst at** | Anything cross-file that requires planning | Long projects that need traceability | Anything past one repo | Complex multi-step work | Quick one-shot edits (use an IDE plugin for that) |

**Use Ortim** when the question is "how do I take a real brief through a real pipeline reliably and explain later what happened". **Don't use Ortim** for "tweak this function while I watch". The tools are complementary — a typical workflow runs Ortim for the project skeleton + critical features, then switches to an IDE assistant for ongoing edits.

---

## 5. Limits and non-goals

Things Ortim deliberately does not do:

- **No live IDE integration.** Today's surface is a CLI. An MCP server / VS Code extension is roadmap (M5+), not shipping.
- **No code review replacement.** The reviewer chain catches structural defects, L1 principle violations, and obvious security issues. It does not catch business-logic bugs, UX problems, or subtle algorithm errors. A senior human still reviews before production.
- **No autonomous deploy.** G6 is a human gate. Ortim writes the deploy artifacts; you push them.
- **No model fine-tuning.** Ortim composes prompts; it doesn't ship custom weights.
- **No team collaboration yet.** Each workspace is single-user. Multi-user concurrent editing is enterprise-tier scope (M5+).
- **No web UI.** Everything is CLI + markdown. Honest tradeoff: writing a web UI well takes engineering attention away from agent quality.
- **No silent retry of business-rule failures.** When the reviewer says "this contradicts PRD §3.2", Ortim does not "fix" the contradiction. The human resolves whether the PRD is wrong or the implementation is wrong.

Things Ortim is also not yet:

- **A managed service.** You run it locally; provider API costs are yours.
- **Multi-language at human-level fluency.** Babel handles Turkish + English well; Spanish/French/German are competent but not benchmarked. Other languages depend on the underlying provider.
- **Production-tested at scale.** As of 0.9.1, the largest run on record is a 12-task DAG. Internal proof-points exist for 4–12 tasks. There is no public case study of a 50+ task project yet.

---

## 6. Who this is for

Ortim is built for developers who:

- Want LLM speed but treat AI code like third-party code: reviewed, audited, gated.
- Are shipping something that has to last (compliance, internal tooling, side projects you'll touch in a year).
- Read PRDs and RFCs and want machine-generated ones that mean something.
- Tolerate a CLI and a markdown editor over a glossy UI.

Ortim is **not** for:

- One-off prototypes you'll throw away on Friday.
- Pure "write me this regex" interactions.
- Teams that want the LLM to operate without any human gate (Ortim disagrees with this model).
- Anyone who needs a managed multi-tenant service today (enterprise tier is being scoped).

---

## 7. Next steps

- Install: `pip install ortim`
- Quick tour (no input needed): `ortim demo`
- 15-minute walkthrough: [docs/tutorial/getting-started.md](tutorial/getting-started.md)
- What to do when something breaks: [docs/runbook/failure-recovery.md](runbook/failure-recovery.md)
- The deep architectural spec: [Ortim_Architecture.md](../Ortim_Architecture.md)

Honest report from the trenches lives in [`docs/backlog.md`](backlog.md) (canonical open-item view); the raw chronological forensic log is kept internally. The backlog is deliberately uncurated — what you see is what's actually under work, not a marketing snapshot.
