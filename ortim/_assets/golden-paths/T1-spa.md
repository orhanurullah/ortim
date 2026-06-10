# T1 — Single-Page App (no own backend)

> **Picked when** the app is meaningfully interactive but talks to *someone else's* backend (third-party SaaS API, public data sources). No backend code in this repo.

## When to use
- Read-only dashboards over a public/third-party API (Stripe public, GitHub, Open Data).
- Internal tools that proxy through a hosted gateway.
- Embedded widgets that live inside a parent app.
- "Frontend-only" exercises where the backend is genuinely out of scope.

## When NOT to use
- The "backend" is yours and you just don't want to write it yet → T2/T4. Don't.
- Auth requires a server-side session → T4. Pure-SPA auth is brittle.
- Compliance requires per-user audit trail you control → T4 or T6.

## Architecture
- React/Vue/Svelte/Solid client.
- API calls go directly from the browser to the third-party service (with their CORS/auth).
- No server-side rendering of user-specific content.
- Build artifact deployed exactly like T0 (CDN).

## Canonical Tech Stack
| Framework | State | Hosting |
|-----------|-------|---------|
| React + Vite + TanStack Query | Zustand / Redux Toolkit | Vercel / Cloudflare Pages |
| SvelteKit (`adapter-static`) | Svelte stores | same |
| Vue + Pinia | Pinia | same |
| Solid | Solid stores | same |

Plus: TypeScript (mandatory), one component library (Radix / shadcn / Headless UI), one styling system (Tailwind / CSS-in-JS — pick one).

## Cross-Cutting Concerns
- **Auth:** delegate to the third-party (OAuth PKCE, Auth0, Clerk in pure-frontend mode). Tokens in `httpOnly` cookies if at all possible; otherwise short-lived in memory.
- **Logging:** browser-side errors → Sentry/Bugsnag; access analytics → Plausible/PostHog.
- **Error handling:** every fetch wrapped with retry + user-visible fallback. Network is a feature path, not an exception.
- **Secrets:** none in the bundle. Anything secret must move the project to T4.
- **Performance budget:** initial JS ≤ 200KB gzipped; LCP ≤ 2.5s on 4G.

## Blocker conditions
- `has_auth: true` AND no third-party identity provider → blocks T1.
- Any "user generates content that other users see" → not safely T1.
- `compliance` includes anything stricter than KVKK basics → blocks T1.

## Migration to T2
A single AC that needs a server-owned record (e.g., per-user settings persisted across devices) → migrate to T2.

## Migration to T4
The day you write the second backend feature, you're already in T4 territory; cut over before the first feature lands.

## Notes
- "We'll just use Firebase Auth and direct Firestore" → that's T2, not T1.
- LocalStorage is not a database; treat it as cache only.
- Bundle hygiene matters here more than anywhere else — every dependency review is mandatory.
