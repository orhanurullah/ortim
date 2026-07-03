# Cloud governance (preview)

> **Status: early preview.** `ortim cloud` points at `cloud.ortim.dev` and is
> invite-only while the surface is being scoped. The local pipeline does **not**
> depend on it — Ortim's audit trail is local-first and works with zero account.
> This document describes exactly what the cloud layer does and, more
> importantly, what it never sends.

`ortim cloud` adds an **Observer layer** on top of a normal Ortim workspace. It
does not change how the pipeline runs, what the agents do, or where your code
lives. It lets a team see — and enforce policy over — the *governance metadata*
of runs across many machines.

---

## What syncs, and what never leaves your machine

`ortim cloud sync` reads the local hash-chained audit log (`.ortim/audit.jsonl`)
and sends a single request body (`OrtimSyncRequest` on the server) with
exactly these top-level fields:

| Field | Contents |
|---|---|
| `currentState` | The pipeline state name (`tasks_ready`, `executing`, …) |
| `taskDagMetadata` | DAG *structure* metadata only — task titles, dependencies, module scopes. Never task code |
| `auditChainHeadHash` | SHA-256 head of the pushed chain segment |
| `events` | The list of redacted `SyncEvent`s below |

Each audit record becomes one redacted `SyncEvent`:

| Field | Contents |
|---|---|
| `seq` | Monotonic cursor position |
| `prevHash` / `chainHash` | The same SHA-256 chain hashes the local verifier uses, so the server can confirm chain linkage |
| `eventType` | The event name (`worker_output_ok`, `gate_prd_approved`, …) |
| `occurredAt` | Timestamp |
| `payloadMeta` | The audit record's metadata **minus** every code-bearing key, plus a derived `cost_usd` |

**Source code is never sent.** Before anything leaves the machine, a recursive
denylist strips any code-bearing key from `payloadMeta` (defense-in-depth that
mirrors the server's own denylist):

```
code, source, source_code, diff, patch, content,
file_content, file_blocks, files,
prompt, response, completion, messages
```

PII redaction (KVKK/GDPR) already runs locally when the audit log is *written*
(see [why-ortim.md §2.6](why-ortim.md#26-hash-chained-audit-log)), so redacted
fields are hashed, not plaintext, before they reach the sync layer at all.
Token-cost pricing stays client-side (single source: `ortim/llm/providers`);
only the derived `cost_usd` number is attached for org-level metering.

---

## Offline-safe by design

A cloud outage must never block local work. `ortim cloud sync`:

- pushes only events past the `synced_seq` cursor stored in `.ortim/cloud.json`;
- on any cloud/network error, prints a warning and **exits 0 without advancing
  the cursor** — the next successful sync resumes exactly where it left off.

You can run the entire pipeline disconnected and sync later; nothing is lost.

---

## Commands

| Command | What it does |
|---|---|
| `ortim cloud login` | Sign in via the browser (device code): confirm a short code on `cloud.ortim.dev/device`. Works for Google sign-in accounts, which have no password |
| `ortim cloud login <email> [--password …]` | Legacy email+password path |
| `ortim cloud logout` | Clear the stored token |
| `ortim cloud status` | Show endpoint, account, and login state |
| `ortim cloud orgs` | List organizations you belong to (role + seat usage) |
| `ortim cloud link --org <id> [--name <n>] [-p <ws>]` | Create/link the current workspace to an org project (writes `.ortim/cloud.json`) |
| `ortim cloud sync [-p <ws>]` | Push redacted audit metadata + current pipeline state |
| `ortim cloud policy [--org <id>] [-p <ws>]` | Pull and display the org governance policy (and cache it locally for enforcement) |

A typical first run:

```bash
ortim cloud login                # opens the browser; confirm the short code
ortim cloud orgs                 # find your org id
ortim cloud link --org org_123   # link the workspace you're standing in
ortim cloud sync                 # push what's happened so far
```

---

## Org policy enforcement

`ortim cloud policy` pulls a governance policy and caches it locally so the
runtime (`execute` / `run-all`) can enforce it without a round-trip:

| Policy field | Effect |
|---|---|
| `mandatoryGates` | Gates the org requires to be human-approved (on top of the always-mandatory G1/G2) |
| `allowedProviders` | Allow-list of LLM providers; anything off-list is refused locally |
| `budgetCapUsd` | Hard cost ceiling — the same mechanism as the local G7 budget gate |

The CLI enforces the cached policy locally; it does not phone home on every call.

---

## Configuration

The endpoint defaults to `https://cloud.ortim.dev`. Override it for a
self-hosted control plane or local testing:

```bash
export ORTIM_CLOUD_URL=https://cloud.example.internal
```

or in `~/.ortim/config.toml`:

```toml
[cloud]
base_url = "https://cloud.example.internal"
```

---

## Threat model (honest framing)

The hash chain is **evidence, not prevention**. An attacker with write access to
both the local log and the control plane could rewrite a consistent chain. What
it buys you is *tamper-evidence*: after the fact, `ortim audit-verify` (local)
and the server's chain check can both prove whether a log was edited. For
compliance and post-hoc audit, "we can prove this log wasn't altered" is the
threat model that matters.

For the local side of the same story — what the audit log contains and how to
verify it offline — see **[why-ortim.md §2.6](why-ortim.md#26-hash-chained-audit-log)**.
