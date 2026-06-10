# T3 — Serverless / Functions-First

> **Picked when** the workload is bursty, event-driven, or schedule-driven, with low ops appetite. Steady-state load doesn't justify a 24/7 server.

## When to use
- Cron-shaped workloads: scheduled reports, batch ingest, periodic syncs.
- Webhook receivers (Stripe, GitHub, Slack) where the work is short.
- Glue between SaaS systems (Zapier-but-yours).
- Public API with very spiky traffic that a managed runtime can absorb without provisioning.

## When NOT to use
- Long-running stateful workloads (websockets, video transcode > 15 min) → T4.
- Workloads where cold start latency matters and you can't keep functions warm → T4.
- Per-second steady traffic where a small VM is cheaper — do the math.
- Vendor lockin is unacceptable → T4 is more portable.

## Architecture
- Functions deployed individually; each function is one entry point with its own deploy unit.
- State lives in a managed DB (DynamoDB / Firestore / Postgres on RDS-Serverless).
- Object storage (S3 / R2) for artifacts and large blobs.
- Queue (SQS / Pub/Sub) between functions to decouple.
- IaC describes the whole graph (Terraform / Pulumi / CDK).

## Canonical Tech Stack
| Cloud | Runtime | Trigger | DB | Queue | IaC |
|-------|---------|---------|----|----|----|
| AWS | Lambda (Node/Python/Go) | API GW / EventBridge / S3 | DynamoDB / Aurora Serverless | SQS / EventBridge | CDK / Terraform |
| GCP | Cloud Functions / Run | HTTP / Pub/Sub / Scheduler | Firestore / Cloud SQL | Pub/Sub | Terraform |
| Cloudflare | Workers + Durable Objects | HTTP / Cron | D1 / KV / R2 | Queues | Wrangler |
| Vercel | Functions | HTTP | any external DB | external | git-driven |

## Cross-Cutting Concerns
- **Auth:** at the gateway (API Gateway authorizers / Cloudflare Access / Auth0 lambda). Functions trust the gateway.
- **Logging:** structured JSON to platform log sink. Aggregate by `correlation_id`.
- **Observability:** distributed tracing mandatory — every function call gets a trace; cold start time is a tracked metric.
- **Secrets:** secret manager per cloud (AWS Secrets Manager / GCP Secret Manager / Cloudflare secrets binding). Never in env files at deploy time.
- **Cold start budget:** track p95 cold start; over budget → smaller bundle, ahead-of-time compile, or provisioned concurrency.

## Blocker conditions
- Steady high RPS that makes always-on cheaper → reconsider.
- Dependencies that don't fit the function size limit (e.g., 250MB Lambda zip).
- Workloads needing >15 min execution → not a fit.
- `audit_heavy: true` with a need for in-process correlation across requests → T6 fits better.

## Migration to T4
Trigger: more than ~15 functions sharing implicit conventions, or "where do I put this?" becomes a daily question.

Migration order:
1. Group functions by domain into modules.
2. Lift shared utilities into a single deployable.
3. Replace queue-between-functions with in-process calls (boundary lint takes over).
4. Keep the queues that survive across module boundaries; drop the rest.

## Migration to T6
Trigger: audit/event log becomes the system of record; functions are *consuming* events, not orchestrating workflows.

## Notes
- Dependency size discipline matters more than in any other tier.
- Local development requires emulators; budget the time to set them up.
- A single misconfigured function can issue an unbounded retry storm — alarm on per-function invocation count, not just errors.
