# RFC: {project_name}

> **Status:** DRAFT | AWAITING APPROVAL | APPROVED
> **Author:** Architect Agent
> **PRD:** {prd_path}

## 1. Context
{Background. Reference PRD goals.}

## 2. Golden Path Selection
**Selected:** T{X} — {tier name}

**Scoring:**
| Factor | Score | Note |
|--------|-------|------|
| Scale | | |
| Team size | | |
| Compliance | | |
| Latency SLO | | |
| Budget | | |

**Rejected alternatives:** {brief reasoning}

## 3. Architecture
{Text diagram. Major components and their relationships.}

## 4. Tech Stack
- **Language:** {...}
- **Framework:** {...}
- **Database:** {...}
- **Deploy target:** {...}
- **CI/CD:** {...}

## 5. Data Model
{Key entities. Schemas — column-level for critical tables.}

## 6. API Surface
{High-level OpenAPI/SDL outline. Endpoints, request/response shape.}

## 7. Module Breakdown
| Module | Responsibility | Owns Schema | Public Interface |
|--------|---------------|-------------|------------------|
| | | | |

## 8. Cross-Cutting Concerns
- **Authentication / Authorization:** {strategy}
- **Logging:** {format, destination}
- **Error handling:** {boundary policy}
- **Configuration:** {env vars vs. config files}
- **Observability:** {metrics, tracing}
- **Secrets management:** {provider}

## 9. Risks
| Risk | Impact | Likelihood | Mitigation |
|------|--------|------------|------------|
| | | | |

## 10. Decisions Locked
{ADR-style summaries — each decision gets one bullet.}

## 11. Deployment Strategy
- **Rollout pattern:** {blue-green | rolling | canary | recreate} — why this for this scale.
- **Health checks:** {liveness path, readiness path, expected response, timeout}
- **Rollback procedure:** {trigger, command, time-to-recovery target}
- **Environments:** {dev / staging / prod — per-env config diffs}
- **First-deploy preconditions:** {DNS, TLS, secrets seeded, DB initialized, etc.}

## 12. Observability Baseline
- **Metrics (RED for services, USE for resources):** list + thresholds
- **Logs:** required fields (`request_id`, `user_id`, `latency_ms`, ...) + destination + retention
- **Tracing:** sampling policy, span boundaries
- **Alerting rules:** which metric → which severity → who gets paged
- **Dashboards:** what link, what it answers

## 13. Security Posture
- **Secret management:** where secrets live, how they're rotated, who has access
- **Authn/Authz:** identity provider, token format, role model, session timeout
- **Audit trail:** events written, retention, tamper resistance
- **Threat model summary:** top 3 threats from STRIDE/LINDDUN — each with mitigation
- **Dependencies:** SAST + dep audit cadence + critical-CVE policy

## 14. Test Strategy
- **Pyramid distribution:** target % unit / integration / e2e
- **Coverage floor:** minimum line/branch coverage to merge
- **Mutation score floor:** {n}% if mutation testing is in scope
- **Contract tests:** for which boundaries (DB, external API, sibling service)
- **Performance budget tests:** specific p95 / throughput assertions if SLO-bound

## 15. Disaster Recovery
- **RTO / RPO targets:** {recovery time / point objectives}
- **Backup frequency + location:** {DB, blob storage, configs}
- **Failover procedure:** stepwise — what runs, what's manual, expected duration
- **Tested cadence:** when was the last DR drill, when is the next

## 16. Runbook Sketch
For each top oncall scenario (3–5 expected): symptom → first command to run → escalation path. Full runbook documents live in `docs/runbooks/`; this section is the index.

## 17. Out of Scope (this RFC)
{Items explicitly deferred to a future RFC.}
