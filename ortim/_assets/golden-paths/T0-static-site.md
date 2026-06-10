# T0 — Static Site

> **Picked when** there is no persistent server-side state, no auth (or only public-edge auth), no per-user data.

## When to use
- Marketing sites, landing pages, documentation portals.
- Blogs (with the corpus committed to source control or pulled at build).
- Public dashboards rendered from a snapshot.
- Anything you'd otherwise serve from a CDN with no compute behind it.

## When NOT to use
- Any user-specific data → T1 (SPA against a BaaS) or higher.
- Authenticated content → T2 minimum.
- Anything you'd be embarrassed to lose if the build cache vanished — see L1 #1.

## Architecture
- Build-time HTML/CSS/JS generation; no runtime server.
- Asset pipeline produces an immutable artifact per commit.
- CDN serves the artifact globally; routes resolve to static files.
- (Optional) edge functions for redirects / A-B / geo — keep stateless.

## Canonical Tech Stack
| Generator | Hosting | CDN | CI/CD |
|-----------|---------|-----|-------|
| Next.js (`output: 'export'`) | Vercel / Cloudflare Pages / Netlify | included | Git push → preview → prod |
| Astro | same as above | included | same |
| Hugo / Eleventy | S3 + CloudFront / Cloudflare | included | GitHub Actions |
| MkDocs / Docusaurus | GitHub Pages / Cloudflare Pages | included | same |

Image optimization runs at build, not request time. Sitemap, robots.txt, RSS — generate at build.

## Cross-Cutting Concerns
- **Auth:** none, or public CDN signed URLs for paywalled assets.
- **Logging:** rely on CDN access logs; ship to a log archive if compliance needs it.
- **Observability:** RUM (web-vitals) only; no server metrics.
- **Secrets:** none in the artifact. If a build-time API key is needed, it must NOT end up in client JS.
- **Performance budget:** Lighthouse score ≥ 90 (perf, a11y, SEO) — CI-gated.

## Blocker conditions
- `has_persistent_state: true` → fail T0; pick T2 or T4.
- Any AC that says "user can save/edit/upload" → fail T0.
- KVKK/GDPR if any per-user processing happens — even cookies — re-evaluate.

## Migration to T1
Add a thin SPA on the same hosting — keeps deploy story identical.
The trigger: a single AC that needs client-side state beyond ephemeral UI.

## Migration to T2 / T4
Add a BaaS (T2) the moment a single user-owned record needs to persist. Skip
straight to T4 if compliance, audit, or schema control matter from day 1.

## Notes
- Do not introduce a backend "for one tiny feature" — re-tier the project.
  Every "tiny" backend is a maintenance burden the static-site author rarely
  has staffing for.
- Forms: use a no-backend form provider (Formspree, Cloudflare) before
  spinning up server compute.
