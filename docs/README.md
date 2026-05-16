# Ortim docs — reading order + structure

This directory is the **knowledge layer** the runtime loads into agent
prompts. The 3-tier structure mirrors the architecture defined in
[`../Ortim_Architecture.md`](../Ortim_Architecture.md) §3.2:

| Tier | What | When loaded | Files |
|---|---|---|---|
| **L1** Immutable Principles | Non-negotiable rules every agent must follow | Loaded into **every** Worker / Reviewer / Architect prompt | [`principles/core.md`](./principles/core.md) |
| **L2** Curated Patterns | Per-tier playbooks + templates + glossary | Retrieved when relevant (Architect picks tier, Babel uses glossary) | [`golden-paths/`](./golden-paths/), [`templates/`](./templates/), [`glossary/`](./glossary/) |
| **L3** Episodic Memory | Architectural Decision Records written after each significant PR | Future: retrieved by Reviewer for cross-PR consistency | [`adr/`](./adr/) |

Conflict resolution: **L1 > L2 > L3**. An L1 principle always wins over
a golden-path recommendation; an explicit golden-path beats a one-off
ADR precedent.

## Reading order for new contributors

1. **Start**: [`../Ortim_Architecture.md`](../Ortim_Architecture.md) — the system spec.
2. **L1**: [`principles/core.md`](./principles/core.md) — 22 rules that govern every agent's output.
3. **Default L2**: [`golden-paths/T4-modular-monolith.md`](./golden-paths/T4-modular-monolith.md) — the default web tier (covers most cases).
4. **Template shapes**: [`templates/`](./templates/) — what a PRD / RFC / Task looks like.
5. **Operational state**: [`../docs/backlog.md`](./backlog.md) — what's open right now.

## When to add docs where

| You wrote… | It goes in… | Trigger |
|---|---|---|
| A new immutable rule that applies to every agent | `principles/core.md` (extend the numbered list) | Must be enforceable + universal. Rare. |
| A new tier playbook (e.g. `T2-baas-firebase.md`) | `golden-paths/<tier>-<variant>.md` | A second viable stack appears for an existing tier. |
| A one-off architectural decision worth remembering | `adr/<NNNN>-<slug>.md` | The decision shaped the codebase and would need re-deriving without a note. |
| A new term Babel should preserve | `glossary/tr-en.md` (extend the table) | The term was mistranslated in a real Babel run. |

## What is NOT in `docs/`

- **Runtime configuration** → `.env.example` + `pyproject.toml`
- **Live project state** → `workspaces/<id>/state.json` (not version-controlled)
- **Test fixtures** → `tests/e2e/fixtures/` (small frozen real-LLM snapshots)
- **Chronological discovery log** → `tespit.md` (append-only, Turkish)
- **Canonical open work projection** → [`backlog.md`](./backlog.md)
