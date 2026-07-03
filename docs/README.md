# Ortim documentation

The human-facing documentation index. Start here, then follow the links.

> **Runtime knowledge assets are not here.** The agent prompts, golden-path
> playbooks, templates, glossary, and immutable principles that the runtime
> loads at execution time live under [`../ortim/_assets/`](../ortim/_assets/)
> (bundled with the package since 0.9.5). The conceptual framing for that
> 3-tier knowledge model (L1 principles / L2 patterns / L3 ADRs) is specified
> in [`../Ortim_Architecture.md`](../Ortim_Architecture.md) §3.2.

## What's where

| Document | Read it when… |
|---|---|
| [`tutorial/getting-started.md`](./tutorial/getting-started.md) | You're new — ~15-minute end-to-end walkthrough (greenfield + brownfield). |
| [`why-ortim.md`](./why-ortim.md) | You want the value framing + comparison vs Cursor / Aider / Claude Code. |
| [`runbook/failure-recovery.md`](./runbook/failure-recovery.md) | A task landed in `AWAITING_HITL`, a gate tripped, a migration failed. |
| [`cloud.md`](./cloud.md) | You're evaluating `ortim cloud` (Observer governance layer, preview). |
| [`local-llm.md`](./local-llm.md) | You want to run Babel/Worker fully local (Ollama / LM Studio). |
| [`mutation-testing.md`](./mutation-testing.md) | You want to measure the Reviewer chain's catch rate. |
| [`skills/authoring-guide.md`](./skills/authoring-guide.md) | You're writing a project-specific Worker/Reviewer skill. |
| [`adr/`](./adr/) | You want the "why we chose A over B" record (L3 knowledge tier). |
| [`backlog.md`](./backlog.md) | You want the canonical list of open work + its status. |
| [`tr/`](./tr/) | Türkçe: [`kullanim-rehberi.md`](./tr/kullanim-rehberi.md) (kapsamlı rehber), tutorial, runbook. |

## Reading order

**New user:**
1. [`../README.md`](../README.md) — install + quick start (canonical).
2. [`tutorial/getting-started.md`](./tutorial/getting-started.md) — first project, gate by gate.
3. [`runbook/failure-recovery.md`](./runbook/failure-recovery.md) — keep handy for when something stalls.

**New contributor:**
1. [`../Ortim_Architecture.md`](../Ortim_Architecture.md) — the system spec (layers, agents, state machine).
2. [`../ortim/_assets/principles/core.md`](../ortim/_assets/principles/core.md) — L1 rules every agent output must satisfy.
3. [`../ortim/_assets/golden-paths/T4-modular-monolith.md`](../ortim/_assets/golden-paths/T4-modular-monolith.md) — the default web tier (covers most cases).
4. [`../ortim/_assets/templates/`](../ortim/_assets/templates/) — what a PRD / RFC / Task looks like.
5. [`backlog.md`](./backlog.md) — what's open right now.

## What is NOT in `docs/`

- **Runtime knowledge assets** → [`../ortim/_assets/`](../ortim/_assets/) (principles, golden-paths, templates, glossary, agents, skills).
- **Runtime configuration** → `.env.example` + `pyproject.toml`.
- **Live project state** → `.ortim/` (project mode) or `workspaces/<id>/` (pool legacy) — not version-controlled.
- **Test fixtures** → `tests/e2e/fixtures/` (small frozen real-LLM snapshots).
- **Internal notes, plans, marketing kit** → `_internal/` (gitignored, local-only; never published).
