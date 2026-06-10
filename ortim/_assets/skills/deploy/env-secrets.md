---
name: deploy-env-secrets
description: Secrets (API keys, DB passwords, tokens) come from runtime env vars or a secret manager, never from a committed file. The repo carries a `.env.example` with placeholders; `.env` is gitignored; the app loads env vars at startup and fails fast when a required one is missing.
audience: [worker, reviewer]
triggers:
  keywords: [env, secret, secrets, credentials, .env, api-key, api_key, password, token, config, dotenv, environment variable]
---

# Environment variables and secrets

Secrets do not live in the repo. The Worker must not write a literal API key, password, or token into any file that will be committed. The pattern is the same across stacks: a checked-in `.env.example` with placeholder names; a runtime `.env` that's gitignored; a startup loader that validates the required keys exist and aborts with a clear error if not.

## Hard rules

- **Never** write a real secret into `.env`, `config.json`, `settings.py`, or any source file. Even temporarily. Even "for testing". The file ends up in `git log` and grep-able forever.
- The repo carries `.env.example` with placeholder values. Real values go into an untracked `.env` (or a secret manager).
- `.gitignore` lists `.env`, `.env.*`, **except** `.env.example` (`!.env.example`).
- The application loads env vars at startup and **fails fast** when a required one is missing. Don't paper over `os.getenv("X") or "default"` for production-required values — that hides config errors until runtime.
- Container images (`Dockerfile`) must not `COPY .env` in. Secrets enter the container via `-e` flags, `--env-file`, or a secret manager.

## `.env.example` shape

```
# .env.example — checked in. Real values live in .env (untracked) or a secret manager.

DATABASE_URL=postgres://user:pass@localhost:5432/dbname
JWT_SECRET=replace-with-32-byte-random
STRIPE_API_KEY=sk_test_replace_me
OPENAI_API_KEY=sk-replace
SMTP_PASSWORD=replace
```

Names must match what the loader expects. Values are obviously fake / placeholder so a search for the literal text returns the example, not a real key.

## `.gitignore` block

```
.env
.env.*
!.env.example
```

The `!.env.example` allowlist is required — otherwise a contributor running `cp .env.example .env.local` accidentally commits the local file.

## Loader (Python)

```python
# config.py
import os

REQUIRED = ("DATABASE_URL", "JWT_SECRET")

def load_config() -> dict[str, str]:
    missing = [k for k in REQUIRED if not os.getenv(k)]
    if missing:
        raise RuntimeError(
            f"Missing required env vars: {', '.join(missing)}. "
            f"Copy .env.example to .env and fill in real values."
        )
    return {k: os.environ[k] for k in REQUIRED}
```

## Loader (Node / TypeScript)

```ts
// config.ts
const REQUIRED = ["DATABASE_URL", "JWT_SECRET"] as const;

export function loadConfig() {
  const missing = REQUIRED.filter((k) => !process.env[k]);
  if (missing.length) {
    throw new Error(
      `Missing required env vars: ${missing.join(", ")}. ` +
      `Copy .env.example to .env and fill in real values.`,
    );
  }
  return Object.fromEntries(
    REQUIRED.map((k) => [k, process.env[k] as string]),
  ) as Record<typeof REQUIRED[number], string>;
}
```

## What "fail fast" buys

A deployment that boots without `JWT_SECRET` is a deployment that signs every token with `undefined` until the first request crashes — and now the error is a stack trace 200 calls deep from the actual misconfiguration. Refusing to start in `load_config()` keeps the error at the only place a human can fix it: the launch command.

## Detection during review

If the Reviewer sees any of these in the diff, the task does not pass:

- A literal-looking secret (matches `sk_live_`, `sk_test_[a-z0-9]{20,}`, AWS `AKIA[A-Z0-9]{16}`, a 40-hex-char string, `Bearer ey...`)
- `.env` checked in
- `.env.example` containing what looks like a real value (not a placeholder)
- `os.getenv("X") or "<something that looks real>"`
- Default values that bypass validation for a required secret
