---
name: pii-review-checklist
description: Human review checklist for PII handling — collection, storage, transmission, retention.
audience: [reviewer, human]
triggers:
  keywords:
    - pii
    - personal-data
    - email
    - phone
    - address
    - ssn
    - passport
    - kvkk
    - gdpr
    - hipaa
    - patient
    - medical-record
---

# PII review checklist

This task touches personally identifiable information. Regulatory exposure (KVKK / GDPR / HIPAA) makes this a critical-path review even when code-quality reviewers approve.

## Classification

- [ ] Inventory: what PII fields does this task touch? Make a list:
  - Direct identifiers (email, phone, full name)
  - Quasi-identifiers (DOB, ZIP, gender — combinable to identify)
  - Sensitive special category (health, biometrics, religion, political)
  - Government-issued (SSN, passport, TC kimlik no)
- [ ] Each PII field has a documented purpose. Collecting "just in case" violates GDPR Art. 5(1)(c) / KVKK 4(c-d) data minimization.

## Storage

- [ ] PII at rest is encrypted: AES-256 column-level for sensitive fields, OR full-disk encryption + DB access control. Document which.
- [ ] Encryption keys NOT in the same DB. Separate KMS / secret manager.
- [ ] No PII in log files, audit trails, or error messages — only opaque user IDs.
- [ ] No PII in commits, in repo, in `.env.example`, in test fixtures (use synthetic data).
- [ ] PII in cache (Redis, etc.) has TTL ≤ 1h; cache layer encryption considered.

## Transmission

- [ ] TLS 1.2+ for all PII-bearing endpoints. HSTS header set.
- [ ] No PII in URL query strings (URL goes to web server logs, browser history, referrer). Use POST body.
- [ ] No PII to third-party services (analytics, error reporting) without explicit consent + data processing agreement.

## Access control

- [ ] PII access logged: who accessed which user's PII, when, why. Audit trail retained per retention policy.
- [ ] Role-based: only `support` / `admin` can read other users' PII. End users only see their own.
- [ ] PII export endpoint exists (GDPR Art. 20 portability / KVKK 11-g).
- [ ] PII deletion endpoint exists (GDPR Art. 17 erasure / KVKK 11-d/e). Verify it actually deletes — not soft-flags.

## Retention

- [ ] Retention period documented. Auto-delete after retention expires.
- [ ] Backup retention matches policy — backups deleted on user erasure request OR documented as carve-out.
- [ ] Records of erasure requests kept (proof of compliance).

## Consent (GDPR-specific)

- [ ] Consent captured at collection time with: purpose, retention, third-party sharing, withdrawal mechanism.
- [ ] Withdrawal of consent works — and stops the processing it withdrew from.
- [ ] Lawful basis other than consent documented (contract, legitimate interest, legal obligation, vital interest, public task).

## KVKK-specific (Turkey)

- [ ] Aydınlatma metni (informing text) accessible BEFORE PII collection, in TR.
- [ ] Açık rıza (explicit consent) for special category data.
- [ ] VERBİS registration if processor is in scope (≥ 100 records / certain thresholds).
- [ ] Data residency: KVKK 9 — sensitive PII out-of-country requires explicit consent OR adequacy decision.

## Testing

- [ ] Unit tests use synthetic PII (`john.doe@example.com`, fake SSNs from `123-45-6789` style). Real data never.
- [ ] Integration tests scrub PII from snapshots / fixtures before commit.
- [ ] Erasure flow tested end-to-end.

## When in doubt

Don't store it. Don't log it. If you must, encrypt + access-control + retention-bound it. Document the lawful basis.

If this checklist surfaces an issue, fix it before re-running `ortim execute <id> <task> --human-reviewed`.
