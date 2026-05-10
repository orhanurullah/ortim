# Task: {task_id}

> **Status:** PENDING | IN_PROGRESS | REVIEW | DONE | FAILED
> **Project:** {project_id}
> **Branch:** task/{task_id}

## Title
{Imperative title — what this task does.}

## Description
{What needs to be done. Concise.}

## Inputs
- {Required preconditions}
- {Files / artifacts that must exist}

## Outputs
- {Files / artifacts produced by this task}

## Acceptance Criteria
- [ ] {Binary-checkable criterion 1}
- [ ] {Binary-checkable criterion 2}
- [ ] Tests added (TDD)
- [ ] L1 principles compliance verified

## Dependencies
- {Other task IDs that must be DONE before this can start}

## Estimated Token Budget
{N tokens — soft cap; hard cap is project-level}

## Worker Constraints
- Branch isolation: must work on `task/{task_id}`
- Must not modify files outside the declared module scope
- Must run lint + type check + tests before marking review-ready
- Max 3 retry on review failure → escalate to HITL

## RFC References
- §{section} — {decision being implemented}

## Integration / Staging
- **Runs in staging?** {yes / no — and why}
- **Smoke check:** {one command or HTTP call that proves the change is live}
- **Feature flag:** {name, default state, rollout plan — or `none` if shipped on}
- **Backwards-compatible?** {yes / no — note any data migration that must precede deploy}
