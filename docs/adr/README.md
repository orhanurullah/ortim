# L3 — Architectural Decision Records

ADRs capture **why** a specific decision was made when the answer would
otherwise have to be re-derived (or worse, re-litigated) months later.
They are the third tier in Ortim's knowledge model (see
[`../README.md`](../README.md)):

  * **L1** principles apply everywhere, every prompt.
  * **L2** golden-paths apply per tier × app_class.
  * **L3** ADRs apply per specific past decision, retrieved for context.

ADRs are **not** documentation of how the system works (that lives in
the architecture spec). They are documentation of *why we chose A over B
when both were viable*, so the reasoning survives team turnover and
future model retraining.

## When to write an ADR

Write one when **all three** are true:

  1. The decision shaped the codebase (added a file, changed an
     interface, locked a library choice, ruled out a competing option).
  2. Re-deriving the reasoning from the code alone would take more than
     ~30 minutes.
  3. Future you (or the next agent) would benefit from knowing the
     *constraints* that were active at decision time, not just the
     outcome.

Examples:

  * "Locked sql.js + IndexedDB for browser persistence — alternatives
    Dexie / localForage rejected because the team needed schema-level
    SQL access for tag-task joins."
  * "Item 48 — extend cycle uses 1:few task aggregation, not 1:1 with
    delta ACs. Pre-fix produced 10-task drift; post-fix produces 4.
    Trade-off accepted: occasional under-decomposition (preferred) over
    consistent over-decomposition (rejected)."

Skip the ADR when:

  * The decision is mechanical (matched a framework convention).
  * The decision was reversed within the same PR (write a comment, not
    a record).
  * The "why" is obvious from the diff (well-named function, clear
    test).

## Format

Use [`0000-template.md`](./0000-template.md) as the starting point. The
shape is intentionally small: one-page max, four required sections
(Context / Decision / Consequences / Status).

File naming: `<NNNN>-<kebab-slug>.md` where `NNNN` is a 4-digit
monotonic counter. The next number is one higher than the highest
existing ADR.

## Index

| ID | Title | Status | Date |
|---|---|---|---|
| _no entries yet_ | | | |
