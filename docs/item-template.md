# Item template — how to write a new tespit.md entry

> Note: `tespit.md` is the internal chronological discovery log (kept under
> `_internal/notes/`, not published). This template documents its entry format;
> the public status projection lives in [`backlog.md`](./backlog.md).

> **Why this exists.** Items entered tespit.md historically as free-form prose. The structure that worked got copied; the structure that didn't (the missing piece) recurred. Items 41 → 41' and BaaS-drift → 47 / 47b were both cascades where a fix shipped without checking what downstream coverage layer also needed widening. This template encodes the lesson.
>
> **When to use.** Any new tespit.md entry that proposes a fix or documents a structural finding. Observation-only entries (run summaries, status updates) don't need the full template — they get short-form chronological notes.

## The template

Copy this block verbatim when opening a new item. Replace every angle-bracketed placeholder. **Do not skip fields.** If a field genuinely doesn't apply, write `N/A — <one-line reason>`.

```markdown
### Item <N> — <one-line title> — <STATUS>

**Symptom.** <The observable failure. One paragraph. Cite the run, workspace, task ID, or test that surfaced it. No diagnosis here — just what was observed.>

**Hypothesis.** <Single sentence: why is the symptom happening? What is the root cause guess? If you're not sure, state competing hypotheses with their likelihood evidence.>

**Acceptance (binary).** <Three to six checklist items, each one a regex / file existence / exit-code / function-signature assertion. Banned-words list applies (no "readable", "good UX", "appropriate" — see agents/orchestrator.md Hard Rule 10).>
- [ ] <e.g. agents/X.md contains the literal phrase "Y"; grep -c returns ≥1>
- [ ] <e.g. tests/test_X.py::test_Y passes after the fix>
- [ ] <e.g. running scripts/Z.py against fixture F produces N/N canonical output>

**Counter-example check.** <One paragraph describing the input that the fix should NOT change. If your fix is "in case A, output X", spell out what input would still legitimately produce non-X. Items survive longer when boundaries are explicit.>

**Downstream coverage scan.** <One paragraph. If this fix widens any agent's autonomous range, schema, or accepted-input space, which deterministic layer downstream now needs corresponding widening? Walk the chain explicitly. Items 47 and 47b would have been caught pre-implementation by this question on the BaaS-drift item: "if StackAnalyst can now pick idb autonomously, is idb in _NPM_DEP_REGISTRY? Does the test environment need a shim?">

**Pillar.** <One of 1=Babel, 2-3=Conversational intake/stack/PRD, 4=Method-level/two-shot, 5=RAG, 6=Skills, 7=MCP, 8=Dynamic LLM routing. Or N/A — <reason> if the item doesn't map to a pillar (operational bugs often don't).>

**Effort range.** <min-max in minutes or hours. Single-point estimates are forbidden — always a range so reality has room to surface.>

**Fix shipped.** <What changed. File paths + one-line summary per file. Test deltas (e.g. pytest 328 → 331 (+3)). Audit-event additions if any.>

**Tests added.** <Test file paths + names + what each pins.>

**Empirical validation (optional).** <If the fix involved LLM-emitted output, run the relevant call N times and report variance. Cost in $. Without this, "the prompt now says X" is structural change without empirical confirmation.>

**Lesson for future items.** <One sentence. What did the discovery process teach about the planning / template / discipline? File under "process improvements" if recurring.>
```

## Field-by-field guidance

### Symptom

- One paragraph, observable only. Resist diagnosis here.
- Cite the run + workspace ID: makes the entry replayable.
- Quote literal error messages or LLM output when the symptom is text-based.

### Hypothesis

- Single sentence. Multiple hypotheses → list them with competing evidence.
- Acceptable to be wrong here — it's why we have empirical validation below.

### Acceptance (binary)

- Inherits the Hard Rule 10 ban-list from `agents/orchestrator.md`: no "readable", "good", "user-friendly", "proper", "intuitive".
- Every item must be machine-checkable: regex match, exit code, file exists, function signature, JSON shape, count comparison, test name.
- Three to six items typical; fewer means the acceptance is too coarse, more means the fix is doing too many things and should split.

### Counter-example check

- Most-skipped field. Most-load-bearing field.
- The question: "what input would the fix wrongly affect if I were sloppy?"
- Item 43 example: a Reviewer that cites stack.json correctly should still pass. The fix shouldn't punish correct citations.
- BaaS-drift example: a brief that genuinely requires a backend (multi-user, auth) should still allow `Hono`. The fix shouldn't blanket-ban server frameworks.

### Downstream coverage scan

- **The discipline lesson from Items 41 → 41' and BaaS-drift → 47 / 47b.**
- Question to ask: **"If my fix widens agent A's autonomous range, which downstream deterministic layer needs corresponding widening?"**
- Walk the chain: StackAnalyst widens → which registry? which bootstrap branch? which validator?
- If the walk surfaces a coverage gap, that gap is a co-shipping item, not a future discovery.
- Examples of downstream layers that frequently need widening:
  - `_NPM_DEP_REGISTRY` (bootstrap package resolution)
  - `_FRAMEWORK_PACKAGES` (bootstrap framework → deps map)
  - `_LANG_TEST_CMD` / `_TEST_CMD_BY_TIER_APP` (test runner inference)
  - `stack_constraint()` matrix (Architect Call 2 hard constraint)
  - `select_tier()` scoring weights (Golden Path scorer)
  - Reviewer prompt rules (boundary semantics)
  - Skill resolver trigger keywords

### Empirical validation (optional)

- Skip for purely-structural items (e.g. "rename function X to Y").
- Required when the fix relies on LLM behavior changing. A prompt change without empirical validation is a hypothesis, not a fix.
- Format: N calls, report variance + cost.
- One-off scripts go under `scripts/` and are git-tracked but excluded from the pytest suite (would burn $ on every run).

### Lesson for future items

- Single sentence.
- If recurring (same lesson surfaces in 3+ items), it's a process improvement — promote it to the item template or the project memory.

## Examples of items that followed (parts of) this template

- **Item 21** (Reviewer length validator) — has Symptom + Root cause + Fix + Tests + a "lesson" subsection ("prompt vs validator division of labor").
- **Item 40** (Architect §4 key_libraries discipline) — has Symptom + Root cause + Fix proposal + Effort + Priority.
- **Item 45** (Architect Call 1 derivation rules, 2026-05-14) — first item to include empirical validation (5/5 deterministic via `scripts/item_45_empirical.py`).

## Examples of cascade misses that this template would have caught

- **Items 41 → 41'** — the BaaS-drift fix widened StackAnalyst's range to include `idb`/`dexie`/`localforage`. Downstream coverage scan was not done. `_NPM_DEP_REGISTRY` was sized to v2/v3 (sql.js only); `idb` was silently dropped. Two follow-up items (47 + 47b) fixed it post-discovery; the template's downstream scan would have flagged it pre-merge.
- **Items 17 → 18 → 18a** — tier-stack constraint matrix was dev-environment-blind. Downstream coverage scan ("if my matrix is the source of truth, what about runtimes-not-installed?") would have surfaced 18 before 17 even shipped.

## Maintenance

- This template lives in `docs/item-template.md`.
- New tespit.md entries reference it implicitly by following the structure.
- If the template misses a class of cascade three times in a row, add a new field. Don't grow the template proactively — let real cascades guide the design.
