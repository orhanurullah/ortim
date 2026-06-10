# L1 Immutable Principles

These rules are non-negotiable and are loaded into **every** Worker /
Reviewer / Architect prompt by `runtime/memory/loader.py` via
`MemoryLoader.load_l1_principles()`. Violation is grounds for review
rejection — Reviewer agents are instructed to surface any L1 breach as a
criterion `fail` with an explicit citation, regardless of acceptance
criteria coverage.

Position in the 3-tier knowledge model (see [`../README.md`](../README.md)):

  * **L1** = this file. Universal, every prompt, conflict-priority highest.
  * **L2** = `docs/golden-paths/`, `docs/templates/`, `docs/glossary/`. Retrieved per tier / per call.
  * **L3** = `docs/adr/`. Episodic; future RAG retrieval.

Editing rule: every change here ships under a deliberate PR with a
test that pins the new rule (or a note in the PR description if the
rule is structural / hard to test). The cap is ~500 lines; if the list
grows past that, propose splitting before adding the next entry.

## Code Structure
1. **Dependency Injection always.** Pass dependencies as constructor parameters or function arguments. Never instantiate concrete dependencies inside business logic.
2. **Ports & Adapters for external services.** Database, payment, email, SMS, third-party APIs all sit behind interfaces. Adapters are isolated, swappable.
3. **One module = one schema.** No cross-module database writes. Cross-module reads only via API.
4. **Module boundary enforcement.** Use lint rules (ESLint boundaries, ArchUnit, Go internal packages) to prevent reaching into another module's internals at compile time.
5. **No premature abstraction.** Three similar lines is better than a wrong abstraction.

## Error Handling
6. **Validate at system boundaries only.** HTTP/gRPC/queue entrypoints validate input; internal calls trust types and contracts.
7. **No swallowed exceptions.** Either handle meaningfully (with logging) or propagate.
8. **No defensive `if x is None` everywhere.** Trust types, ORM guarantees, framework invariants.

## Security
9. **No secrets in code.** Use environment variables or secret manager. Never commit `.env`, `*.key`, `*.pem`, credentials, or tokens.
10. **Sanitize all external input.** SQL injection, XSS, command injection, path traversal, SSRF, deserialization.
11. **Default-deny authorization.** Every endpoint has an explicit allow rule; absence of rule means deny.
12. **PII handling requires explicit policy.** Personal data (KVKK/GDPR scope) must have stated retention, access controls, and right-to-be-forgotten support.

## Testing
13. **TDD for any logic.** Write the test first; the test defines the contract.
14. **Spec-first for APIs.** OpenAPI / GraphQL SDL / proto written before implementation. Generate types from spec.
15. **Integration tests hit the real database, not mocks.** Mocks for unit tests only.
16. **Mutation testing for critical logic.** Coverage % is meaningless if tests have no asserts.

## Operations
17. **Branch isolation per task.** No direct `main` work. One branch per task ticket.
18. **Feature flags for new modules.** Born behind a flag; removable by config change without redeploy.
19. **Structured logs only.** JSON, not free text. Include trace ID, user ID (hashed), event name.
20. **Idempotent operations.** Retries must not produce duplicates. Use idempotency keys.

## Determinism
21. **Code-generation tasks use temperature 0.** No creative variance in implementation.
22. **No `date.now()` or `random()` inside business logic** — inject a clock/RNG abstraction so tests are deterministic.

## Anti-Patterns (forbidden)
- Microservices unless Golden Path T5 or T6 selected.
- Global mutable state.
- Hardcoded URLs / file paths / secrets / customer IDs.
- Bypassing HITL gates G1–G6.
- Adding fields "for the future" — YAGNI.
- "Helper" functions used in one place.
- Comments explaining *what* the code does (only *why*).
