---
name: auth-review-checklist
description: Human review checklist for authentication, session, and authorization tasks.
audience: [reviewer, human]
triggers:
  keywords:
    - auth
    - login
    - signin
    - signup
    - password
    - jwt
    - session
    - token
    - oauth
    - mfa
    - sso
    - authorization
---

# Auth review checklist

This task touches authentication / authorization. Even when SecurityReviewer + CodeReviewer approve, the liability cost of a missed bug here is high — walk this checklist before merging.

## Authentication

- [ ] Password hashing uses `bcrypt`, `argon2`, or `scrypt` — NOT `md5`, `sha1`, or plain. Cost factor / work factor set sane (bcrypt rounds ≥ 10, argon2 memory ≥ 64MB).
- [ ] Login endpoint rate-limited (per-IP and per-account-name). Brute force lock-out after N failed attempts in a window.
- [ ] No information leakage in error messages: "Invalid credentials" — NOT "User not found" vs "Wrong password".
- [ ] Login over HTTPS only (no HTTP fallback). Set-Cookie has `Secure` + `HttpOnly` flags. SameSite is `Strict` or `Lax` deliberately, not default.
- [ ] Session ID regenerated on login (no fixation vulnerability).
- [ ] Logout invalidates the session server-side AND clears the cookie.

## Tokens (JWT / opaque)

- [ ] JWT signature verified on EVERY request — never decoded without verification. Algorithm pinned (no `alg=none`, no algorithm confusion).
- [ ] Token signing key is at least 256-bit, kept in env var / secret manager — NOT in code, NOT in repo, NOT in `.env.example`.
- [ ] Token expiry set (≤ 15 min for access tokens; refresh tokens separate).
- [ ] Refresh token rotation if used; old refresh tokens revoked on use.
- [ ] Token revocation list / kill-switch for compromised tokens.

## Authorization

- [ ] Every privileged route has an explicit auth check — NOT inferred from middleware order.
- [ ] Role / permission check at the data boundary too (defense in depth). `user_id` from token used to scope queries (no IDOR — Insecure Direct Object Reference).
- [ ] No "admin bypass" hardcoded routes / accounts.

## Multi-factor / SSO

- [ ] If MFA: backup codes single-use, stored hashed.
- [ ] If TOTP: window ≤ ±1 step; secret regenerated on reset.
- [ ] If OAuth/OIDC: state + nonce + PKCE used. `redirect_uri` matched exactly (no wildcard / substring).
- [ ] If SAML: signature verification on assertion; signing cert pinned; replay protection (assertion ID + NotOnOrAfter).

## Logs & observability

- [ ] No passwords / full tokens / session IDs in logs. Mask after first 4 chars or omit entirely.
- [ ] Auth failures logged with: timestamp, IP, account-name, reason class (not full reason). Auth successes also logged for audit.
- [ ] Alerting on auth failure spike (rate-of-change), repeat failures from one IP, unusual geo.

## Testing

- [ ] Test for token-without-signature (forge attempt) — must reject.
- [ ] Test for expired token — must reject, not accept-and-renew.
- [ ] Test for wrong-user resource access (IDOR) — must reject.
- [ ] Test for unauthenticated access to privileged route — must reject (401, not 200).
- [ ] Test for SQL injection in login fields (`' OR 1=1 --`).

## When in doubt

Lean toward stricter — overly cautious auth is a UX issue you can fix; overly permissive auth is a breach.

If this checklist surfaces an issue, fix it before re-running `ortim execute <id> <task> --human-reviewed`.
