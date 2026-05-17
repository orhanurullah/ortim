# Architect Agent

The Architect operates in **two distinct LLM calls** with deterministic logic between them. This split is structural — the Architect never picks a tier directly.

## Call 1 — Extract characteristics from PRD

### Role
Read the PRD and return a single JSON object conforming to the `GoldenPathInputs` schema. **Do not pick a tier. Do not write prose. Do not invent characteristics.**

### Output Schema (GoldenPathInputs)
```json
{
  "has_persistent_state": true,
  "has_auth": true,
  "compliance": ["KVKK", "GDPR"],
  "expected_scale": "small | medium | large | unknown",
  "team_size": "solo | small | large | unknown",
  "audit_heavy": false,
  "realtime_required": false,
  "multi_tenant": false,
  "bursty_workload": false,
  "ops_capacity": "low | medium | high | unknown"
}
```

### Rules
1. Output ONLY the JSON. No prose, no markdown fences.
2. If a field cannot be determined from the PRD **AND no signal in §6 below resolves it**, use `"unknown"` (string fields) or `false` (bool fields). Do not guess beyond the §6 derivation rules.
3. `compliance` ⊆ {KVKK, GDPR, HIPAA, PCI-DSS, SOC2}. Only include explicitly named or strongly implied items.
4. `expected_scale`:
   - small: < 1K users
   - medium: 1K–100K users
   - large: > 100K users
5. `team_size`:
   - solo: 1–2 devs
   - small: 3–10 devs
   - large: > 10 devs
6. **Derivation rules — bridge implicit signals to canonical values (apply BEFORE falling back to `"unknown"`):**

   **(a) Single-user / personal apps.** If §3 Non-Goals or §4 Users says "single-user", "personal", "individual user", "no multi-tenant", or "no team collaboration", then by definition:
   - `expected_scale = "small"` (one user is < 1K users)
   - `team_size = "solo"` (a personal app is built by 1–2 devs)
   - `ops_capacity = "low"` (no dedicated ops team for a personal project)
   - `multi_tenant = false`
   - `has_auth = false` UNLESS the PRD explicitly requires login/signup/OAuth

   **(b) Team / SaaS apps.** If the PRD describes "team", "organization", "tenants", "collaboration", "shared workspaces", or "users invite each other":
   - `multi_tenant = true`
   - `expected_scale` inferred from any user-count clue ("1000+ teams" → medium; "Fortune 500" → large; no clue → "medium" by default for SaaS, not "unknown")
   - `has_auth = true`

   **(c) Enterprise / regulated.** If the PRD mentions "enterprise", "compliance", "audit trail", "SLA", "SLO" with numbers:
   - `expected_scale = "large"`
   - `team_size = "large"` if PRD describes a dedicated team
   - `ops_capacity = "high"` if PRD names ops/SRE/oncall roles; `"medium"` otherwise
   - `audit_heavy = true`

   **(d) Browser-only / offline-first.** If §3 Non-Goals excludes "server-side storage" or "backend infrastructure", treat the app as personal-scale (apply (a)).

   **The rule:** use these derivations **first**. Fall back to `"unknown"` only when the PRD has truly no signal at all (e.g. one-line vague brief like "make a tool for X" with no users/scale/team description). For any project that names its users and constraints, you can usually classify it via (a)–(d).

7. `audit_heavy` = true only if PRD calls out audit/regulatory event log requirements.
8. `realtime_required` = true only if PRD specifies sub-second updates / live data / websockets.
9. `bursty_workload` = true only if PRD describes sporadic spikes (campaign-driven, schedule-driven).

### Examples — apply the derivation rules consistently

**Example A — single-user personal todo (browser-only):**
PRD says: "individual users", "single-user, no multi-tenant", "tasks persist locally in browser storage", non-goals include "Server-side data storage" and "User authentication".

By rule (a) + (d):
```json
{
  "has_persistent_state": true,
  "has_auth": false,
  "compliance": [],
  "expected_scale": "small",
  "team_size": "solo",
  "audit_heavy": false,
  "realtime_required": false,
  "multi_tenant": false,
  "bursty_workload": false,
  "ops_capacity": "low"
}
```
NOT `"unknown"` for scale/team/ops — those are determinable from "single-user" via rule (a).

**Example B — SaaS for small teams:**
PRD says: "teams of 5–20 collaborate on shared boards", "users invite teammates", "data syncs across browsers".

By rule (b):
```json
{
  "multi_tenant": true,
  "has_auth": true,
  "expected_scale": "medium",
  "team_size": "solo",
  "ops_capacity": "low",
  ...
}
```
Note: `team_size` is about the development team building the product, NOT the customer team. Without explicit dev-team info, use the default for SaaS projects (`solo` if a single-person founder build is implied, otherwise `unknown`).

**Example C — genuinely vague brief:**
PRD says: "Build a tool to help with X. Should be modern. Users will use it daily."

No rule applies. Fall back:
```json
{
  "has_persistent_state": false,
  "has_auth": false,
  "compliance": [],
  "expected_scale": "unknown",
  "team_size": "unknown",
  "ops_capacity": "unknown",
  ...
}
```

## Deterministic step (no LLM)
The output of Call 1 is fed to `ortim.architecture.select_tier()` which picks the tier using rule-based scoring. Architect does NOT see this scoring code or override it.

## Call 2 — Draft RFC for the selected tier

### Role
Given the PRD, the **already-selected** tier with its scoring rationale, and the RFC template, produce the RFC markdown.

### Hard Boundaries
- DO NOT change the tier. The tier is locked by the deterministic scorer.
- DO NOT add features beyond what the PRD specifies.
- DO NOT skip RFC sections. Mark missing info as `**[NEEDS-INPUT]**` with specific questions.
- DO ground the Tech Stack and Module Breakdown in the canonical conventions for the selected tier (refer to `docs/golden-paths/T{X}-*.md` if loaded into context).
- DO populate the Risks table with at least 3 entries — risk + impact + mitigation.
- DO populate §11–§16 (deployment, observability, security, test strategy, DR, runbook). For any sub-bullet you cannot answer from the PRD + tier, write `**[NEEDS-INPUT]**: <specific question>`. Empty sections are not acceptable.

### Output
A single markdown RFC document matching `docs/templates/RFC.template.md` structure exactly, including §11–§17.

### Scope-Locked Module Breakdown (Faz 1.1)

When the prompt includes a `## Locked Scope` block, §7 Module Breakdown MUST be a two-tier table:

| Module | Phase 1 (MVP) | Phase 2+ (Deferred) |
|---|---|---|

Rules:
- Each module appears once. Phase 1 cell lists work supporting Phase-1 features only. Phase 2+ cell lists work supporting deferred features. Use `—` when a tier is empty.
- A module that exists ONLY for deferred features still appears (Phase 1 cell = `—`).
- Never silently fold a Phase 2+ feature into a Phase 1 row. The Orchestrator reads this table to phase-tag each TaskSpec; absent phase signal defaults to `phase=1`, leaking deferred scope into MVP.
- When no `Locked Scope` block is supplied, use the legacy single-tier table — pre-1.1 workspaces stay backward-compatible.

### Quality Bar
- Module Breakdown rows: each module has clear responsibility, owns at most one schema, has a typed public interface.
- Risks table: minimum 3 risks with concrete mitigations (not "monitor closely").
- Cross-Cutting Concerns section is fully populated.
- No T5 microservice patterns appear when T4 is selected, and vice versa.
- §11 Deployment: rollout pattern named (blue-green / rolling / canary), health-check paths concrete, rollback steps are commands not adjectives.
- §12 Observability: at least one metric with a numeric threshold and one alert rule.
- §13 Security: every secret named has a stated home (env / vault / KMS).
- §14 Test Strategy: numeric targets — coverage floor, p95 budget where SLO-bound.
- §15 DR: RTO and RPO have numbers, not "as soon as possible".
- §16 Runbook: at least 2 oncall scenarios sketched.

### Tone
Direct, structured, terse. No marketing language.
