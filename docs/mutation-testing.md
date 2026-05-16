# Reviewer mutation testing

Mutation testing measures the Reviewer's ability to catch known bug shapes. We feed a hand-crafted buggy diff to the Reviewer with the original task's acceptance criteria and observe whether the verdict rejects it. The catch rate per bug class is the durable quality signal — if it drops, the Reviewer prompt has regressed or a new bug class has slipped past the rubric.

This document explains the suite, how to invoke it, and how to read the report.

---

## What's in the suite

The shipped suite (`runtime/mutation/cases.py::DEFAULT_CASES`) carries one case per bug class:

| Bug class | Case | Language | Pattern |
|---|---|---|---|
| `off-by-one` | `sum_consecutive_pairs` | Python | `range(len(nums))` instead of `range(len(nums) - 1)` |
| `null-check-removed` | `get_user_display_name` | TypeScript | `user.displayName` direct access on a nullable param |
| `auth-bypass` | `is_authorized` | Python | `return True  # TODO` instead of the real two-condition check |
| `sql-injection` | `find_user_by_name` | Python | f-string interpolation instead of parameterized SQL |
| `missing-await` | `get_user_count` | TypeScript | `return db.query(...)` instead of `return await db.query(...)` |
| `wrong-operator` | `can_book_appointment` | Python | `or` instead of `and` between two conditions |

Each case has:
- **original_code** — the correct version (kept for reference and diff rendering; never sent to the Reviewer).
- **mutated_code** — the buggy version, presented to the Reviewer as if a Worker emitted it.
- **acceptance_criteria** — 4-5 binary criteria (Hard Rule 10 style, no soft words).
- **bug_keywords** — phrases the Reviewer's verdict should mention for a strict catch.

---

## Scoring

Two definitions of catch:

- **Loose:** `verdict.approved is False`. Either a `fail`/`partial` criterion verdict OR an `l1_violations` entry triggers this. The primary signal — a buggy diff should never be approved.
- **Strict:** Loose AND the verdict's evidence (concatenated `criterion_verdicts[*].evidence` + `code_quote` + `l1_violations`) contains at least one of the case's `bug_keywords`. Case-insensitive substring match.

The gap between loose and strict is **diagnostic quality**. A high loose rate with a low strict rate means the Reviewer is rejecting on noise rather than naming the bug — that's bad for the auto-retry loop (Item 15a), which relies on `last_review_reasons` carrying actionable feedback.

### Targets

| Metric | Target | Action if below |
|---|---|---|
| **Loose rate** | ≥ 90% | Reviewer is approving buggy code → emergency prompt rewrite |
| **Strict rate** | ≥ 70% | Acceptable for v0.9 ship |
| **Strict rate** | ≥ 50% | Borderline — prompt iteration recommended |
| **Strict rate** | < 50% | Hard veto: ship gate on Faz 2.3 |

---

## Running the suite

### Dry run (zero cost — list cases, no LLM call)

```bash
ortim mutation-test
```

Bastırır:

```
Mutation suite — 6 cases (--live olmadan, sadece listeleme):
┌─────────────────────┬───────────────────────────┬──────────────┬───────────────────────────────────┐
│ Bug class           │ Case                      │ Language     │ Keywords (strict)                 │
├─────────────────────┼───────────────────────────┼──────────────┼───────────────────────────────────┤
│ off-by-one          │ sum_consecutive_pairs     │ Python       │ indexerror, index error, …        │
│ null-check-removed  │ get_user_display_name     │ TypeScript   │ null, undefined, typeerror        │
│ ...
```

### Live run (real Reviewer LLM call)

```bash
ortim mutation-test --live --provider=deepseek
```

DeepSeek tahmini maliyet: 6 case × ~1500 token = **~$0.02 total**. Anthropic ile çalıştırırsan ~10× pahalı.

### Single bug class

```bash
ortim mutation-test --live --bug-class=sql-injection
```

Sadece tek bir class'ı dener — bir specific regresyondan şüpheleniyorsan.

### Output (live mode)

```
Mutation suite — 6 cases, reviewer=deepseek/deepseek-chat

Mutation report — 6 cases
  Caught (loose): 6/6 (100%)
  Caught (strict): 5/6 (83%)

  Per bug class:
    off-by-one             loose=1/1  strict=1/1
    null-check-removed     loose=1/1  strict=1/1
    auth-bypass            loose=1/1  strict=1/1
    sql-injection          loose=1/1  strict=0/1
    missing-await          loose=1/1  strict=1/1
    wrong-operator         loose=1/1  strict=1/1

┌─────────────────────┬───────────────────────────┬───────┬────────┬─────────────────────────────┐
│ Class               │ Case                      │ Loose │ Strict │ Verdict summary             │
├─────────────────────┼───────────────────────────┼───────┼────────┼─────────────────────────────┤
│ off-by-one          │ sum_consecutive_pairs     │ ✓     │ ✓      │ fail=1 pass=3 approved=False │
│ sql-injection       │ find_user_by_name         │ ✓     │ ✗      │ fail=1 pass=3 approved=False │
│ ...
```

Exit code:
- `0` if strict rate ≥ 50%
- `1` if strict rate < 50% (CI fail signal)

---

## When to re-run

- **Before shipping a Reviewer prompt change** — make sure the catch rate didn't drop.
- **Before model upgrades** — moving from DeepSeek to a Claude or Ollama variant; re-baseline.
- **After observing a real-world reviewer miss** — add a new case to `DEFAULT_CASES`, re-run to confirm the new case is initially missed, then iterate the prompt until it's caught.

The suite is small (6 cases) by design — extending it is expected as new bug shapes show up in real runs. Add cases via the `MutationCase` dataclass in `runtime/mutation/cases.py` and ensure each carries non-empty `bug_keywords`.

---

## Cost notes

Each case fires one Reviewer call. Reviewer's user prompt carries the task spec, RFC excerpt, acceptance criteria, and the mutated code — typically 1200-1800 input tokens. The verdict JSON is small (~600 output tokens). Per-case spend approximations:

| Provider | Input + Output per case | 6-case suite |
|---|---|---|
| DeepSeek | ~$0.003 | ~$0.02 |
| Anthropic Claude (Opus) | ~$0.06 | ~$0.36 |
| Ollama (local) | $0.00 | $0.00 |

A nightly cron running the suite on DeepSeek costs ~$7/year. Affordable as a regression gate.

---

## Limits

- **The suite is a sample, not a population.** 6 cases against well-trained bug shapes. A Reviewer that catches all 6 isn't proven to catch novel bugs — only proven not to have regressed on these shapes.
- **Strict-keyword matching is approximate.** A Reviewer that says "the function won't work on the last element" catches off-by-one semantically but won't match `IndexError` literally. Tune keywords or weaken to loose-only for borderline cases.
- **No isolated-test counterfactual.** Today the runner doesn't compare the verdict on the mutated code against the verdict on the original. If the Reviewer would reject *both*, the loose catch is meaningless. A future enhancement could add a "no-op" pair to detect this.

---

## Architecture

The mutation suite lives in `runtime/mutation/`:

```
runtime/mutation/
  __init__.py          — public API
  case.py              — MutationCase, CatchResult, CatchRateReport dataclasses
  cases.py             — DEFAULT_CASES (6 inline cases)
  runner.py            — run_mutation_suite + ReviewerLike Protocol
  scoring.py           — score_case (loose + strict)
```

The runner is decoupled from `CodeReviewerAgent` via a `Protocol` — tests pass synthetic FakeReviewers without instantiating the SDK. The CLI command (`ortim mutation-test --live`) wires the real Reviewer in.
