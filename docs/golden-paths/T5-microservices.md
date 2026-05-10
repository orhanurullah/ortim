# T5 — Microservices

> **Picked when** team size, deploy independence, or scale forces module-per-service. Implies a platform team and serious ops capacity.

## When to use
- Team of ≥ 8 engineers split across product areas with independent release cadence.
- A T4 monolith has reached the point where deploys block on someone else's PR.
- Different services genuinely need different stacks (e.g., real-time pipeline in Go, ML inference in Python).
- Scale beyond what one process / one DB can absorb.

## When NOT to use
- Solo or small team (≤ 5) — you'll pay the distributed-systems tax with no benefit.
- `ops_capacity: low` — distributed systems require platform discipline you don't have.
- Compliance prefers fewer trust boundaries — T4 is easier to audit.
- "It's the modern way" — not a reason. T4 is the modern default.

## Architecture
- One service per domain (extracted from T4 modules — never built top-down).
- Each service owns its database; no cross-service DB reads.
- Sync calls: HTTP/gRPC via service mesh (mTLS, retries, timeouts at the proxy layer).
- Async: Kafka / NATS / RabbitMQ between services.
- Each service has its own CI/CD pipeline; no monorepo deploy.
- Shared platform tier: ingress, identity, observability, secrets, schema registry.

## Canonical Tech Stack
| Concern | Tooling |
|---------|---------|
| Container orchestration | Kubernetes (or managed: EKS / GKE / AKS) |
| Service mesh | Linkerd / Istio (only if mesh problems are real) |
| Async messaging | Kafka or NATS JetStream |
| API gateway | Kong / Envoy / Traefik |
| Identity | OAuth2/OIDC (Keycloak / Auth0) — central, not per-service |
| Observability | OpenTelemetry → Prometheus + Grafana + Tempo / Loki |
| Schema registry | Confluent Schema Registry (Kafka) or AsyncAPI repos |
| Per-service DBs | Postgres / MongoDB / Redis as appropriate per service |

## Cross-Cutting Concerns
- **Auth:** central IDP issues JWTs; gateway verifies; services trust the gateway claims.
- **Authorization:** role/policy decisions at service boundaries; OPA or per-service.
- **Logging:** structured JSON, every line carries `trace_id` (propagated W3C tracecontext).
- **Tracing:** mandatory; absence = serious incident.
- **Schema:** every cross-service contract is versioned; backwards-incompatible changes go through a gate.
- **Failure modes:** every cross-service call has timeout + retry budget + circuit breaker; no infinite waits.
- **Deploy:** progressive delivery (canary or blue-green per service); registry tracks rollout.

## Blocker conditions
- `team_size: solo`/`small` → blocks T5.
- `ops_capacity: low` → blocks T5.
- HIPAA without strong segmentation strategy → consider — T5 multiplies your attack surface.

## Migration from T4
Per-module, never all at once:
1. Pick the module with the most independent deploy cadence pain.
2. Replace its `api/` in-process calls with HTTP/gRPC stubs (same shape, different transport).
3. Move its schema to a separate database.
4. Spin up its own deploy pipeline.
5. Add network failure handling on every caller.
6. Gain observability (trace shows the new hop).
7. Decide whether the next module's pain justifies the cost.

## Migration to T6
Trigger: durable event log becomes the design center, not a side effect — see T6.

## Notes
- "Microservices because Netflix does" → bullshit. Pick T5 only because T4 hurts.
- A service per developer is a smell, not a goal.
- Without a platform team you'll rebuild a worse version of Kubernetes; do not.
