# T2 — BaaS-Backed App

> **Picked when** persistence + auth are needed but the team is small and time-to-first-feature matters more than infrastructure control.

## When to use
- Solo / small team (≤ 3 engineers).
- Standard SaaS shape: users, organizations, basic CRUD, file uploads, email.
- KVKK is acceptable as long as the BaaS provider is in-region.
- A working product needed in weeks, not months.

## When NOT to use
- HIPAA / PCI-DSS in scope → T4 with audited components.
- Schema control / audit trail must be yours end-to-end → T4.
- Lock-in cost worries the founders → T4.
- Team has Postgres ops capacity already → T4 isn't slower at this size.

## Architecture
- Frontend (React / Svelte / Vue) talks directly to the BaaS over its SDK.
- BaaS handles: auth, DB rows + RLS, file storage, edge functions for things SDK can't do.
- Tiny edge functions (Cloudflare Workers / Supabase Edge Functions) for secrets-bearing work (email, payment webhooks).

## Canonical Tech Stack
| BaaS | Frontend | Edge functions | Auth |
|------|----------|----------------|------|
| Supabase | Next.js / SvelteKit | Supabase Edge Functions (Deno) | Supabase Auth |
| Firebase | Next.js | Cloud Functions (Node) | Firebase Auth |
| Pocketbase (self-hosted) | any SPA | embedded JS hooks | built-in |
| Appwrite | any SPA | Appwrite Functions | built-in |

Choose one and stay there. Mixing two BaaS = T4 by stealth, more painful than just choosing T4 up front.

## Cross-Cutting Concerns
- **Auth:** BaaS-provided. JWT in httpOnly cookie. Roles via row-level security policies (Supabase) or custom claims (Firebase).
- **Authorization:** RLS / security rules are the contract — version them like code.
- **Logging:** BaaS dashboard for short-term; export to your archive for retention.
- **Observability:** BaaS metrics + Sentry on frontend.
- **Secrets:** in BaaS env vars + edge functions only. Frontend has only the public anon key.
- **Migrations:** BaaS schema migrations as code (Supabase: SQL migrations directory; Firebase: a manual discipline).

## Blocker conditions
- HIPAA, PCI level 1, FedRAMP → blocks T2.
- "We need to leave $BAAS in 6 months" — already in trouble.
- Ops_capacity = high (you have a platform team) — T2 is a downgrade; pick T4.

## Migration to T4
Triggers:
1. RLS policies start exceeding what's expressible declaratively.
2. You need a long-running job (BaaS edge functions are time-capped).
3. Schema changes start needing transactions across tables in ways the BaaS doesn't expose.
4. Compliance scope changes.

Migration order:
1. Stand up Postgres in your control (Supabase has self-hosted; you can clone the schema).
2. Front the frontend with your own API gateway translating SDK calls.
3. Re-implement auth with the same JWT shape so frontend doesn't need rewrites.
4. Cut over per-module.

## Notes
- "We'll write a tiny backend just for this one webhook" — that's the slope.
  Either keep the webhook in an edge function or migrate the whole project.
- Vendor lockin is real. Document everything you depend on the BaaS for.
- Read the RLS policies in code review like you'd read SQL — same rigor.
