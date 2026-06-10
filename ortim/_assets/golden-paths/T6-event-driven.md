# T6 — Event-Driven / Audit-Heavy

> **Picked when** the durable event log is the system of record, not a side effect. Reads are projections; writes are events.

## When to use
- Domains where audit trail is the product (finance, healthcare ops, regulated workflows).
- Real-time systems that must reconcile to a canonical history (trading, billing settlement).
- Systems where multiple consumers need the same stream of facts at different cadences.
- Replay-driven debugging is a hard requirement.

## When NOT to use
- CRUD over a small domain — T4 is faster and cheaper.
- `team_size: solo` or `ops_capacity: low` — you cannot run Kafka at scale alone.
- "Real-time-ish" requirements that a polling API would satisfy — don't pay the complexity.
- Read-heavy domains where eventual consistency is unwelcome — re-evaluate.

## Architecture
- **Event store** (Kafka / EventStoreDB / Pulsar) is the source of truth.
- **Command side:** services validate commands → emit events → events are the only durable write.
- **Query side (read models):** consumers project events into purpose-built read stores (Postgres for SQL, OpenSearch for full-text, ClickHouse for analytics).
- Each event carries a stable schema (Schema Registry); breaking changes are versioned.
- Replay: rebuild any read model from event 0 — that's the whole point.

## Canonical Tech Stack
| Concern | Tooling |
|---------|---------|
| Event store | Kafka (with KRaft) / NATS JetStream / EventStoreDB |
| Schema | Avro + Confluent Schema Registry, or Protobuf |
| Streaming | Kafka Streams / Flink / Faust |
| Read models | Postgres / OpenSearch / ClickHouse — one per query shape |
| Snapshotting | application-level — for long aggregates |
| Saga orchestration | Temporal / Cadence (or Flink for streaming sagas) |
| Observability | OpenTelemetry; trace-id flows through events |

## Cross-Cutting Concerns
- **Auth:** at command-API ingress; events themselves are internal — but `actor_id` is part of every event payload.
- **Authorization:** policy decisions on commands, not on read models (read models filter by claims).
- **Logging:** every consumer emits per-event log lines; offsets and lag are first-class metrics.
- **Schema discipline:** every event has a version; consumers handle N and N-1; deprecations are tracked.
- **Idempotency:** consumers must be idempotent; re-delivery is not an exception, it is the model.
- **Replay:** test that every consumer can rebuild from offset 0 in a staging environment monthly.
- **Tombstones / GDPR:** plan for right-to-be-forgotten via cryptographic shredding (encrypt PII per-subject, delete the key on request).

## Blocker conditions
- `team_size: solo`/`small` → blocks T6.
- `ops_capacity: low` → blocks T6.
- "We just need a queue between two services" → T5 with a message bus, not T6.
- HIPAA with no shredding strategy — solve before tier selection.

## Migration from T5
Trigger: read-side queries are increasingly served by a separate projection of an event log you've stitched together informally — formalize it.

Steps:
1. Designate the canonical event log; bus must be durable, ordered, partitioned.
2. Move writes to "command → emit event" pattern in one bounded context first.
3. Build the first read model as a separate consumer of the new log.
4. Verify replay works.
5. Repeat per bounded context.

## Migration from T4
Skipping T5 to go directly T4 → T6 is rare and only justified when the audit log was the original requirement (e.g., a trading system designed top-down). Otherwise: T4 → T5 → T6 over years.

## Notes
- T6 is the most expensive tier in human time; choose only if it's load-bearing.
- "Event sourcing because it's clean" → if your domain is CRUD it will be the worst code you ever ship.
- Schema review is the chokepoint; staff it.
- Read models are throwaways; never let business logic live in them.
