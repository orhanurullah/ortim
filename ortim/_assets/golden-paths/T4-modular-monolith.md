# T4 — Modular Monolith

> **The default tier.** Never blocked. Picked when no other tier strongly out-scores it.

## When to use
Standard SaaS workload: persistent state, authentication, multi-tenant possible, small-to-medium scale, small-to-medium team. **80% of projects belong here.**

## When NOT to use
- Truly static content → T0
- No backend at all → T1
- Throwaway prototype with BaaS-shaped requirements → T2
- Bursty cron-like workload with low ops appetite → T3
- Large team needing independent deploy cadence → T5
- Audit log as source of truth → T6

## Architecture
- Single deployable artifact
- Modules folder-isolated, lint-enforced (ESLint boundaries / ArchUnit / Go internal)
- Each module **owns its database schema** (no cross-module table writes — L1 #3)
- Cross-module communication via in-process typed API calls (the module's `api/` directory)

## Canonical Tech Stack
Pick one row, then stay consistent:

| Language | Framework | DB | Migrations | Deploy |
|----------|-----------|----|-----------|--------|
| TypeScript | NestJS | Postgres | TypeORM / Prisma | Docker → Render / Fly.io / Railway / k8s |
| Python | FastAPI | Postgres | Alembic | Docker → same as above |
| Go | chi / echo | Postgres | golang-migrate | Docker → same as above |
| Java | Spring Boot | Postgres | Flyway | Docker → same as above |

Plus: Redis for cache + queue. Object storage (S3 / R2) for files. Structured JSON logs.

## Module Layout
```
src/
├── modules/
│   ├── identity/           # owns: users, sessions, roles
│   │   ├── api/            # PUBLIC: other modules import only from here
│   │   ├── domain/         # INTERNAL: business logic, entities
│   │   ├── infra/          # INTERNAL: DB repo, JWT signer, adapters
│   │   └── http/           # INTERNAL: HTTP handlers / routes
│   ├── billing/            # owns: invoices, subscriptions
│   └── notifications/      # owns: outbox, delivery state
└── shared/                 # truly cross-cutting: logger, config, db pool, error types
```

## Module Boundary Enforcement (mandatory)
Choose one mechanism appropriate to the language and **make it a CI-blocking lint rule**:

- TypeScript: `eslint-plugin-boundaries` — only `modules/X/api/**` is reachable from `modules/Y/**`
- Java: `ArchUnit` test enforced in CI
- Go: directory must be `internal/` so the compiler refuses external imports
- Python: `import-linter` contracts (forbidden imports)

**Without an enforcement mechanism, T4 degrades to a tangled monolith within 6 months.**

## Data Ownership
- Each module owns its tables and is the only writer.
- Cross-module reads happen via the module's `api/` interface (not raw DB queries).
- Foreign keys to other modules' tables are forbidden — use IDs and lookup via API.
- This rule makes T4 → T5 (microservice extraction) mechanical: each module already has a schema-clean boundary.

## Cross-Cutting Concerns

### Authentication / Authorization
- Identity module owns sessions and roles
- Other modules receive a typed `AuthenticatedUser` from middleware — they do not call the auth library directly
- Default-deny: every endpoint declares its required role/permission

### Logging
- Structured JSON only (L1 #19)
- Mandatory fields: `timestamp`, `trace_id`, `module`, `event`, `user_id_hash`
- Level discipline: `error` for paging conditions, `warn` for retried ops, `info` for state changes, `debug` off in prod

### Error handling
- Boundary errors (HTTP layer) → mapped to status codes + sanitized client message
- Internal calls trust types and contracts (L1 #6)
- No silent catches (L1 #7)

### Configuration
- `.env` for local; secret manager for prod
- Config object validated on boot — fail fast if required key missing

### Observability
- OpenTelemetry traces with module-scoped spans
- Prometheus metrics: per-module request rate, error rate, p99 latency
- Trace ID propagated through all module calls and emitted in every log line

## CI/CD
- Pre-commit hook: format + fast lint
- PR pipeline: full lint + type check + unit tests + integration tests against real DB (L1 #15)
- Architectural fitness function: module boundary lint must be green
- Mutation testing on critical modules (auth, billing) — CI gates on minimum mutation score
- Deploy: blue-green or rolling, zero-downtime migration discipline

## Database Migrations (mandatory pattern)
- Forward migrations only — never rewrite history once merged
- Two-phase migrations for schema changes that break old code: deploy compatible schema → deploy new code → drop old columns in next release
- Migration must be reviewed by Migration Agent (HITL gate G3)

## Removal Protocol (sök/tak)
A module can be removed cleanly because of the boundary rules:
1. Verify no other module imports from `modules/X/api/**`
2. Drop the schema (or archive)
3. Remove feature flag
4. Remove `modules/X/` directory
5. Run boundary lint to confirm no orphan imports

## Migration to T5 (Microservices)
When team or scale demands it, T4 → T5 is a directed sequence per module:
1. Module's DB schema → separate database
2. In-process `api/` calls → HTTP/gRPC service stub
3. Module → its own deploy pipeline
4. Cross-module reads gain network failure modes — add retries, timeouts, circuit breakers
5. Distributed tracing becomes mandatory (it should already be on for T4)

The migration is mechanical only because T4 enforced the boundary rules from day one. **T4 done sloppily cannot be migrated to T5 without rewrite.**
