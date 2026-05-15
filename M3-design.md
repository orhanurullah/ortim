# M3 — Skills System

**Status:** Design lock — 2026-05-13. Locked decisions per tespit.md item 11 + web-todo-m2 E2E findings.
**Effort estimate:** ~1 session (foundation only). pytest 244 → ~260.
**Items closed structurally:** the remaining 2 of 4 categories of item 26 (cross-module imports, library invention) by giving Worker a stack-aware skill block.
**Items improved transitively:** T-009 / web-todo-m2 T-004 class L1 violations should fall to zero on tasks that match a skill.

---

## 1. Locked design decisions

| # | Question | Decision | Why |
|---|---|---|---|
| 1 | File format | Markdown body + simple YAML-like frontmatter (custom parser, no PyYAML dep) | Mirrors how `.ai-factory.env` is parsed already. Frontmatter keys: `name`, `description`, `audience`, `triggers.tier`, `triggers.app_class`, `triggers.language`, `triggers.keywords`. Lists in flow form `[a, b, c]`. |
| 2 | Trigger model | AND across trigger groups, OR within a group. Missing group = "matches anything." | Mirrors the way Claude Code routes skills. Keeps the resolver predictable. |
| 3 | Resolution priority | (a) language-specific > (b) tier-specific > (c) app_class-specific > (d) universal. Stable alphabetical tiebreak by name. | More-specific skills override more-general ones — same priority order as tier docs. |
| 4 | Injection budget | At most **5 skills** per LLM call, total body cap **12,000 chars** (≈ 3,000 tokens). Skills past the cap dropped in alphabetical order with audit entry. | Skills inflate every Worker/Reviewer call. A hard ceiling keeps p99 token cost bounded. |
| 5 | Audience | Each skill declares `audience: [worker, reviewer]` (default both). Resolver filters per call site. | Some skills are "what to write" (Worker), others are "what to check" (Reviewer). Mixing them at the prompt level confuses both. |
| 6 | Storage | `<repo_root>/skills/<scope>/<name>.md`. `scope` is just a folder for organization — has no semantic meaning to the resolver (triggers are explicit). | Discovery-by-folder-walk; no manifest file needed. |
| 7 | Audit | `worker_output_ok` and `reviewer_verdict` events gain `active_skills: list[str]` (skill names only — body hashes deferred until skill versioning lands). | Mirrors `routing_decision` (item 23) — lets a future post-mortem ask "did skill X help here?" |
| 8 | CLI | `ortim skill list [project_id]` (without id = all skills; with id = those that would resolve for that project's stack), `ortim skill show <name>`. No edit / create command — skills are repo artifacts edited via normal text editors. | Read-only CLI surface keeps the scope tight. |

**Deferred to M4+:** per-project skill overrides (`workspace/.skills/<name>.md`), skill versioning, mtime cache invalidation, cross-skill conflict detection, skill self-tests, runtime fetching from a skill registry.

---

## 2. Skill file shape

```markdown
---
name: typescript-module-boundaries
description: Cross-module imports go through the public barrel, not direct paths.
audience: [worker]
triggers:
  language: [TypeScript]
  app_class: [web]
---

# TypeScript module boundaries

When a task in module `A` needs a symbol from module `B`:

- **DO** import from the module root: `import { foo } from '../B'`
- **DO NOT** import from internal files: `import { foo } from '../B/internal.ts'`
- **DO NOT** import from sibling files in another module's tree at all — go
  through `B`'s public `index.ts` (or `index.tsx`) instead.

The Worker treats `../<module>` as the only legal import path for a sibling
module. Cross-module imports of *types* follow the same rule — re-export
types from the public barrel.

## Example

```ts
// in task-service/index.ts
import { dbCreate, dbGet } from '../db-adapter';  // ✅ barrel import

// NOT
import { dbCreate } from '../db-adapter/internal.ts';  // ❌
```
```

### Frontmatter grammar (minimal)

- Frontmatter is delimited by `---` lines at the top of the file.
- Each line is `key: value` OR `key:` followed by indented `- value` (bullet list, not used in M3 but reserved).
- Values are strings unless wrapped in `[a, b, c]` flow brackets → parsed as a list of trimmed strings.
- Trailing comments (`# ...`) are stripped.
- Unrecognized keys are stored on the skill but ignored by the resolver — future-compat.

---

## 3. Schema (pydantic)

```python
class SkillTriggers(BaseModel):
    tier: list[str] = Field(default_factory=list)         # ["T1", "T2"]
    app_class: list[str] = Field(default_factory=list)    # ["web"]
    language: list[str] = Field(default_factory=list)     # ["TypeScript"]
    keywords: list[str] = Field(default_factory=list)     # ["import", "module"]


class Skill(BaseModel):
    name: str
    description: str
    audience: list[str] = Field(default_factory=lambda: ["worker", "reviewer"])
    triggers: SkillTriggers = Field(default_factory=SkillTriggers)
    body: str
    path: str          # repo-relative path of the skill file (for audit / debug)
```

---

## 4. Resolver contract

```python
def resolve_for_task(
    *,
    skills: list[Skill],
    task: TaskSpec,
    tier: str,
    app_class: str,
    locked_stack: LockedStack | None,
    audience: str,                 # "worker" or "reviewer"
    char_budget: int = 12_000,
    max_skills: int = 5,
) -> list[Skill]:
```

Algorithm:
1. Filter by audience.
2. For each remaining skill, evaluate trigger groups against the call site:
   - `tier`: `tier in skill.triggers.tier` OR `not skill.triggers.tier`
   - `app_class`: `app_class in skill.triggers.app_class` OR `not skill.triggers.app_class`
   - `language`: `locked_stack.language in skill.triggers.language` OR `not skill.triggers.language` (skipped entirely when `locked_stack is None`)
   - `keywords`: at least one of `skill.triggers.keywords` matches the task description case-insensitively OR `not skill.triggers.keywords`
3. Compute specificity score: `len(triggers.language) > 0` adds 4, `tier` adds 2, `app_class` adds 1. Universal stays 0.
4. Sort by (-specificity, name).
5. Iterate; append while `total_body_chars + len(body) <= char_budget` and `count < max_skills`.

---

## 5. Injection contract

### Worker
`WorkerAgent.execute(..., active_skills: list[Skill] | None = None)` — when set, append after L1 principles:

```
## Active Skills

The following project-specific patterns must be followed. They override
any default coding habits a model may have for this language.

### {skill.name} — {skill.description}

{skill.body}

---

### {next skill}
...
```

### CodeReviewer
`CodeReviewerAgent.review(..., active_skills: list[Skill] | None = None)` — same shape, but framed as:

```
## Active Skills

Acceptance criteria are interpreted in the context of these project
patterns. If the Worker output violates a skill, mark the relevant
criterion `fail` and quote the skill name in the verdict reason.

### {skill.name} — {skill.description}
...
```

Runner builds the skill list **per task** (different module/keywords = different skill set) and passes it into both calls.

---

## 6. CLI surface

```
ortim skill list                # all loaded skills, with frontmatter summary
ortim skill list <project_id>   # only those that resolve for project's stack
ortim skill show <name>         # full body of one skill
```

Audit log entries are dumped via existing `ortim` commands; no new skill-specific audit command for M3.

---

## 7. Seed skills (M3-3)

Tightly scoped to web-todo-m2 T-004 + similar T-009-class failures. Four files:

| File | Audience | Triggers | What it teaches |
|---|---|---|---|
| `skills/typescript/module-boundaries.md` | worker, reviewer | language=TypeScript | Barrel imports only; never reach into a sibling module's internal files |
| `skills/typescript/imports-from-locked-stack.md` | worker | language=TypeScript | Only import libraries declared in the locked stack's key_libraries; if you need another, surface it in the summary, don't invent |
| `skills/typescript/vitest-co-located.md` | worker | language=TypeScript, keywords=[test, vitest, behavior, criteria] | When the task has runtime acceptance criteria, emit a co-located `*.test.ts` alongside the impl |
| `skills/react/component-patterns.md` | worker, reviewer | language=TypeScript, app_class=web, keywords=[component, ui, render, props] | Functional components + hooks only; no class components; props typed via interface; one component per file |

---

## 8. Faz sırası

```
M3-0 (this doc)
  └─ M3-1: schema + loader/resolver + frontmatter parser + tests
       └─ M3-2: Worker + Reviewer skill injection + audit + runner threading
            └─ M3-3: write 4 seed skills
                 └─ M3-4: ortim skill list / show CLI
                      └─ M3-5: E2E regression on web-todo-m2 T-004 (skills loaded, expect Reviewer NOT to L1-reject)
```

Her faz commit-able. M3-3 ile M3-2 birbirine bağımlı — seed skill'lerin frontmatter şeması M3-1'in parser'ıyla uyuşmazsa fail fast.

---

## 9. Test sayımı hedefi

| Dosya | Yeni testler |
|---|---|
| `tests/test_skills_loader.py` (yeni) | +6 (frontmatter parse, audience filter, tier/lang/keyword trigger matches, specificity ordering) |
| `tests/test_skills_resolver.py` (yeni) | +4 (budget cap, max_skills cap, locked_stack=None handling, no-match returns empty) |
| `tests/test_worker_skill_injection.py` (yeni) | +2 (skills land in system prompt, audit logs active_skill_names) |
| `tests/test_reviewer_skill_injection.py` (yeni) | +2 (skills land in reviewer prompt, audit captures) |
| `tests/test_skills_cli.py` (yeni) | +2 (list with/without project_id, show happy path) |
| **Toplam** | **+16** → pytest 244 → **260** |

---

## 10. Riskler

| Risk | Olasılık | Mitigation |
|---|---|---|
| Frontmatter parser misses an edge case (multi-line scalar, escaped quotes) | Orta | Keep grammar narrow; reject unknown shapes loudly. Add a test for every malformed-input case we want to support. |
| Skill body blows token budget on big tasks | Düşük | char_budget cap is hard; audit logs which skills got dropped. |
| Skill teaches the wrong thing → Worker regression | Orta | Skill bodies live in the repo; reviewable in PR. M3 ships only 4 narrowly-scoped skills. |
| Worker ignores the skill even when injected | Orta | Stack-rank skill content above task spec in the prompt; reinforce in `agents/worker.md` ("Active Skills are HARD rules — same level as L1"). |
| Resolver explodes on a malformed skill file | Düşük | Loader catches per-file parse errors, logs to audit, skips the bad skill; never fails the whole load. |
| Seed skill set incomplete for next E2E | Yüksek | Accepted — M3 ships the foundation, more skills added incrementally. README of `skills/` directory documents how to add new ones. |
