# Ortim — Enterprise Tier

> **License:** Commercial. See `../LICENSE.commercial`. Source files in this
> directory carry the SPDX identifier `LicenseRef-Commercial`.

This directory is the home of the Ortim commercial / enterprise tier. It is
**intentionally empty** in M1 — the directory exists so contributors and
auditors immediately see the open-core boundary.

## Roadmap (post-M1)

The following capabilities are planned for the enterprise tier. None ship in
the FSL-licensed core.

| Capability | Target milestone | Status |
|---|---|---|
| Multi-tenant orchestrator (per-tenant rate limits, isolated audit logs, per-tenant LLM key mapping) | M5 | Not started |
| SSO / SAML / OIDC integration | M5 | Not started |
| Long-term audit retention with off-site export (S3 / GCS / Azure Blob) | M5 | Not started |
| SLA-backed support tier (response-time guarantees, priority bug triage) | M5 | Not started |
| Custom Golden Path tiers (per-customer architecture catalogues) | M6 | Not started |
| Custom reviewer chains (custom hard-veto reviewers, weighted scoring) | M6 | Not started |
| White-label / OEM redistribution | M6 | Not started |
| Cross-tenant audit dashboard (compliance officer view) | M6 | Not started |
| Hash-chain export to external WORM storage (regulatory audit) | M6 | Not started |

## Boundary policy

The boundary between core (FSL-1.1-Apache-2.0) and enterprise (Commercial)
follows two rules:

1. **Anything that can be derived from the audit log is core.** This includes
   budget tracking, profile reports, drift detection, and re-running
   previously executed projects. The audit log is open-core territory.

2. **Anything that requires shared infrastructure across tenants /
   organisations is enterprise.** Multi-tenant routing, SSO, off-site export,
   and per-tenant rate limits are tied to a deployment model (SaaS,
   on-prem-shared) that justifies a commercial license.

A capability that violates these rules is misclassified and should be moved.

## Contact

Commercial licensing inquiries: `licensing@ortim.dev`
