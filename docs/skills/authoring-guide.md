# Skill authoring guide

A skill is a small markdown file that injects a project-specific pattern into the Worker or Reviewer prompt at the moment a matching task runs. Skills override default LLM habits — "use psycopg2 like this", "test text without emoji prefixes", "wire dependencies through Depends, not module globals". They're the layer between L1 principles (universal) and the per-call task spec (specific).

This guide explains how to write one. The format is small enough to learn in an afternoon and battle-tested by the skills already in the repo.

---

## 1. Anatomy

Every skill is a single markdown file under `skills/<topic>/<name>.md`. It has two parts:

```markdown
---
name: ...
description: ...
audience: [...]
triggers:
  tier: [...]
  app_class: [...]
  language: [...]
  keywords: [...]
  keywords_blocklist: [...]
---

# Title

Body in plain markdown. Code fences, tables, lists — whatever helps
the LLM and the human reader.
```

### Frontmatter fields

| Field | Type | Purpose |
|---|---|---|
| `name` | string | Unique id (used in audit log, `ortim skill show`, test assertions). Convention: `<topic>-<slug>`. |
| `description` | string | One-line summary. Shown back to the user in the Worker prompt header. Be concrete — "Don't mix async endpoints with sync DB clients" beats "FastAPI tips". |
| `audience` | list | `worker`, `reviewer`, or both. Default if omitted: `[worker, reviewer]`. |
| `triggers.tier` | list | Tier IDs (`T0`–`T6`, `M0`–`M2`, `D0`–`D1`). Empty = any tier. |
| `triggers.app_class` | list | `web`, `mobile`, `desktop`. Empty = any. |
| `triggers.language` | list | Locked stack language (`TypeScript`, `Python`, `Go`, `Rust`, …). Empty = any. |
| `triggers.keywords` | list | Phrases. Match against the task haystack (`title + description + module_scope`). At least one must hit. Empty = any. |
| `triggers.keywords_blocklist` | list | Phrases that **reject** the skill when present. Wins over a positive keyword match. Use for opt-out (`no docker`, `lokal kalsın`). Empty = no filter. |

### Body

The body is what the LLM actually sees in its context window. Write for two readers:

- **The LLM** — pattern + rule + 1-2 examples + a hard-rule bullet list. Avoid prose paragraphs longer than 4 lines; they get summarized away. Show the trap first ("❌"), then the fix ("✅").
- **The human contributor** — a short rationale up top so future-you remembers why the skill exists.

Keep total length under ~150 lines. The resolver enforces a 12 000-character total budget across all matched skills; an over-long skill crowds out the others.

---

## 2. Resolver semantics

When a task starts, the resolver walks every skill and asks `applies_to(audience, tier, app_class, language, haystack)`:

```
                ┌─────────────────────────────────────────────────────┐
                │ audience matches?                                   │
                │   if no → skip                                      │
                ├─────────────────────────────────────────────────────┤
                │ every populated trigger group AND-matches?          │
                │   tier        — exact membership                    │
                │   app_class   — exact membership                    │
                │   language    — exact membership                    │
                │   keywords    — at least one phrase in haystack     │
                ├─────────────────────────────────────────────────────┤
                │ keywords_blocklist — NO phrase in haystack          │
                │   (rejects even if positive triggers matched)       │
                ├─────────────────────────────────────────────────────┤
                │ accept                                              │
                └─────────────────────────────────────────────────────┘
```

Two more knobs:

- **Specificity ordering** — more-specific skills sort ahead of universal ones when the budget is tight. Specificity score: `language=4`, `tier=2`, `app_class=1`. A skill with `language=[Python]` beats a universal skill even if both apply.
- **Budget caps** — `max_skills=5` and `char_budget=12_000` by default. Skills past the cap are dropped silently. Audit log records which skills resolved.

### Special cases

- **`triggers: {}`** (or omitted entirely) → universal skill, applies anywhere the audience allows. Use sparingly — L1 principles already cover universal rules.
- **`language` set but `LockedStack` is None** → skill is dropped. Pre-M2 projects without a locked stack can't be promised a language-specific skill set.
- **All four positive triggers empty + a non-empty `keywords_blocklist`** → skill applies everywhere except where the blocklist hits. Rare but legal.

---

## 3. Choosing the audience

The Worker prompt and the Reviewer prompt have different headers:

- **Worker** sees: *"## Active Skills. The following project-specific patterns are HARD rules — same weight as L1 principles. They override any default coding habits a model may have."*
- **Reviewer** sees: *"## Active Skills. Acceptance criteria are interpreted in the context of these project patterns. If the Worker output violates a skill, mark the relevant criterion `fail` and cite the skill name."*

Pick based on what the skill controls:

- **`[worker]` only** — "how to write this code" (`deploy-dockerfile-node`, `react-dependency-injection`).
- **`[reviewer]` only** — review checklists where the Worker doesn't change behavior, but the Reviewer needs to widen its check (`auth-review-checklist`).
- **`[worker, reviewer]`** — patterns where both sides need to share the rule (`deploy-env-secrets`, `typescript-module-boundaries`).

When in doubt, write for the worker first and add `reviewer` only if the Reviewer's default checks would miss the violation.

---

## 4. Three examples

The repo carries fifteen+ shipped skills. Three to study, in order of complexity:

### Easy — `skills/deploy/dockerfile-node.md`

A template-shaped skill. The body is a Dockerfile, a `.dockerignore` block, and a short hard-rules list. Triggers narrow to `tier=[T4,T5,T6]`, `app_class=[web]`, `language=[TypeScript, JavaScript]`, plus a `keywords_blocklist` so a brief saying "no docker" suppresses it. Worker-only.

What to learn: how triggers compose to fire **only** when the brief is asking for a production deploy on a Node stack at T4 or above.

### Medium — `skills/react/dependency-injection.md`

A pattern-shaped skill. The body shows the trap (`new ServiceName()` inside an event handler) then the fix (DI via React Context). Triggers: `language=[TypeScript]`, `keywords=[App, wire, integrate, adapter, service, context]`. No tier filter — DI is a structural concern at every tier.

What to learn: keyword choice. The list captures the **module wiring** signal without firing on every React task. The proof-point v2 forensic showed Worker inlined services on T-007 (the App-wiring task) but not on T-002 (a leaf service task) — the keyword set has to discriminate.

### Hard — `skills/python/fastapi-async-patterns.md`

A diagnostic-shaped skill. The body explains WHY `async def` + sync I/O is wrong (event loop blocking), shows two correct shapes (sync def + threadpool **or** async def + async client), enumerates which sync calls remain allowed, and ends with a `grep` you can run to detect the mismatch.

What to learn: the body is doing two jobs — overriding a wrong default LLM habit (defaulting to `async def` everywhere because "modern Python"), and giving the model a model of **why** so it can transfer the rule to unfamiliar libraries (`smtplib`, `boto3`) the skill didn't enumerate explicitly.

---

## 5. Testing a new skill

Every new skill ships with a unit test that pins two facts:

1. The on-disk file loads (catches a frontmatter typo before it hits production).
2. The resolver fires on a representative task **and** doesn't fire on a representative non-task.

Pattern (real example from `tests/test_skill_docker_resolver.py`):

```python
def test_dockerfile_node_resolves_for_t4_web_typescript_deploy_brief():
    skills = load_all_skills(REPO_ROOT)
    out = resolve_for_task(
        skills=skills,
        task=_task("Add Dockerfile for production deploy of the API service"),
        tier="T4",
        app_class="web",
        locked_stack=_stack("TypeScript"),
        audience="worker",
    )
    assert "deploy-dockerfile-node" in {s.name for s in out}


def test_dockerfile_node_does_not_resolve_for_t0_cli():
    skills = load_all_skills(REPO_ROOT)
    out = resolve_for_task(
        skills=skills,
        task=_task("Ship the CLI for production deploy"),
        tier="T0",
        app_class="web",
        locked_stack=_stack("TypeScript"),
        audience="worker",
    )
    assert "deploy-dockerfile-node" not in {s.name for s in out}
```

One positive case + one or two negative cases is enough. The negative cases are what catch over-broad keyword lists down the line.

For skills with a `keywords_blocklist`, add a third test that proves the opt-out works:

```python
def test_dockerfile_node_does_not_resolve_when_brief_says_no_docker():
    ...
    assert "deploy-dockerfile-node" not in {s.name for s in out}
```

---

## 6. Common mistakes

Patterns we've already paid for once — don't repeat them.

### Over-broad keywords

`keywords: [code, function, class]` — every task description on Earth contains one of these. The skill fires for nothing in particular and crowds out specific skills under the char budget. Rule of thumb: a keyword should be specific enough that a reasonable person would NOT use it casually. `import`, `mock`, `wire`, `dockerfile`, `migration` good. `function`, `code`, `task`, `add` bad.

### Missing `language` filter on a language-specific skill

A "use `npm ci` not `npm install`" rule fires on a Python project if `language` is empty and the description happens to say "install". Always set `language` when the body is language-specific. The proof-point matrix taught us this — Item 18a (stack-aware test-cmd) is the same shape.

### Universal skill where a layered skill belongs

If a rule applies to "everything", it's probably an L1 principle, not a skill. L1 principles are loaded unconditionally; skills are resolved per task. Use skills when the rule is **conditional on context the resolver can detect**.

### Blocklist with negation conflict

`keywords: [docker]` + `keywords_blocklist: [no docker]` works because "no docker" is a distinct phrase. But `keywords: [auth]` + `keywords_blocklist: [no auth]` is risky — the keyword `auth` matches "no authentication required" too. Pick blocklist phrases that are unambiguous: full multi-word strings ("without docker", "lokal kalsın"), not single words.

### Skill body that doesn't say WHY

The LLM transfers patterns. A skill that says "use asyncpg, not psycopg2" works on `psycopg2`. A skill that says "async def + sync I/O blocks the event loop" works on `smtplib`, `redis-py`, `boto3`, and the next library that doesn't exist yet. When you can afford 5-10 extra lines, explain the failure mode.

### Audience set to `[worker, reviewer]` by default without thinking

Doubling the audience doubles the cost in every Reviewer call too. If the Reviewer's existing checks would already catch the violation, don't pile a skill onto its prompt. The Reviewer reads acceptance criteria + the diff; it doesn't need a copy of the Worker's how-to-write-it guide unless interpretation hangs on it.

---

## 7. Submitting

1. File goes in `skills/<topic>/<name>.md`. Use an existing topic directory if one fits (`deploy/`, `react/`, `python/`, `typescript/`, `security/`). New top-level topic OK when the file genuinely doesn't fit.
2. Frontmatter validates: `ortim skill show <name>` should print without warnings.
3. Tests in `tests/test_skill_<name>.py` (or extend the topic's existing test file): at least one positive case, one negative case, plus a blocklist case if applicable.
4. Run `pytest tests/test_skill*.py` — all green.
5. Commit message: `feat(skills): add <name> — <one-line description>`.

That's it.
