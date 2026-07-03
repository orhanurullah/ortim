# Security Policy

## Reporting a vulnerability

Email **contact@ortim.dev** with `[SECURITY]` in the subject. Include a
reproduction if you can. You'll get an acknowledgement within 72 hours and
a fix-or-mitigation plan within 14 days for confirmed issues. Please don't
open a public GitHub issue for anything exploitable before we've shipped a
fix — coordinated disclosure is appreciated and will be credited in the
changelog unless you prefer otherwise.

Only the latest released minor version is supported with security fixes.

## Threat model (short form)

Ortim is a **local-first** pipeline: your brief, PRD, RFC, task DAG,
generated code, and audit log all live on your machine. There is no
server in the loop unless you explicitly opt into `ortim cloud`.

**What leaves your machine:**

| Channel | Data | When |
|---|---|---|
| LLM provider (BYO key: Anthropic / DeepSeek / your Ollama host) | Prompts built from your brief and pipeline artifacts | Every agent call — this is inherent to using a hosted LLM; use `--provider ollama` for a fully local run |
| `ortim cloud sync` (opt-in) | Redacted audit **metadata only** — event names, chain hashes, token counts, derived USD cost. A recursive denylist strips `code`, `diff`, `patch`, `prompt`, `response` and every other code-bearing key before anything is sent; the server independently rejects payloads containing them | Only when you run it, on a linked workspace |
| `ortim demo` (keyless replay) | Nothing — recorded responses are bundled with the package and replayed offline | — |

The exact sync payload schema is documented field-by-field in
[docs/cloud.md](docs/cloud.md).

**Key handling.** API keys are read from your shell env, `.env`, or
`~/.ortim/config.toml` — never written to workspaces, audit logs, or the
cloud. The cloud access token is stored in `~/.ortim/cloud.toml`
(chmod 600 on POSIX).

**Execution sandbox.** Each generated task carries a `module_scope`; the
executor rejects writes outside it. Generated code runs your local test
suite and hooks — treat a workspace like any codebase you'd run `npm
install` in: review before executing beyond the sandbox.

**Audit chain: evidence, not prevention.** The hash-chained audit log
(`.ortim/audit.jsonl`) is tamper-*evident*, not tamper-*proof*. An
attacker with write access to the file can rewrite a consistent chain;
what the chain guarantees is that `ortim audit-verify` (and the control
plane's independent linkage check, if you sync) can detect edits after
the fact. PII redaction runs at write time — redacted fields are hashed
before they ever reach disk.

**Not in scope:** vulnerabilities in the LLM providers themselves,
prompt-injection producing *bad code* that the mandatory human gates
(G1/G2) and reviewer chain exist to catch, and DoS against your own
machine by your own brief.

## License note

Ortim's core is **source-available** under
[FSL-1.1-Apache-2.0](LICENSE) — not OSI open source until each release's
two-year Apache-2.0 conversion. Security researchers may read, build, and
test the code freely; the FSL restriction only covers offering a
competing commercial service.
