# Golden Paths — Index

Twelve canonical architectures across three app classes (web, mobile, desktop). The Architect agent does **not** pick a tier directly; an LLM extracts characteristics from the PRD (and optionally the brownfield codebase summary) into `GoldenPathInputs` JSON, then the deterministic scorer in `runtime/architecture/golden_paths.py` selects the tier.

## App Class

The `app_class` field on `GoldenPathInputs` chooses which tier family is scored:

| App Class | Tiers | Default | Source signal |
|---|---|---|---|
| **web** | T0–T6 | T4 (Modular Monolith) | PRD describes a web product, or no class signal |
| **mobile** | M0–M2 | M1 (Flutter / RN) | "mobile app", "iOS/Android", or codebase has Flutter/RN |
| **desktop** | D0–D1 | D1 (Tauri / Electron) | "desktop", "Tauri/Electron/SwiftUI", or codebase has those |
| **mixed** | (none) | n/a — Architect must disambiguate | Monorepo with frameworks across classes |

`MIXED` is intentionally not auto-scored: when a single repo contains both a Flutter app and a FastAPI backend, no single tier rules both halves. The Architect must pick a primary `app_class` for the current task.

## Web Tiers (T0–T6)

| Tier | Name | When to use | Blocked when |
|------|------|------------|--------------|
| **T0** | Static | No state, no auth, content-only | persistent state OR auth required |
| **T1** | SPA / Frontend-only | Client-side state only | backend persistent state OR auth required |
| **T2** | BaaS (Supabase, Firebase) | <10K users, no enterprise compliance | HIPAA/PCI-DSS/SOC2 OR large scale |
| **T3** | Serverless | Bursty workload, low ops capacity | (no hard blockers; cons grow at large scale) |
| **T4** | **Modular Monolith** *(default)* | Standard SaaS — never blocked, often the right answer | (never blocked) |
| **T5** | Microservices | Large team + high ops capacity + independent deploy needs | small team OR low ops capacity |
| **T6** | Event-driven / CQRS | Audit-heavy OR realtime-critical | small team |

## Mobile Tiers (M0–M2)

| Tier | Name | When to use | Blocked when |
|------|------|------------|--------------|
| **M0** | Native (Swift / Kotlin) | Hardware-deep (BLE, AR, high-FPS games), single-platform focus | (never blocked, but score is 0 without a native-feature signal — M1 wins by default) |
| **M1** | **Cross-platform (Flutter / RN)** *(default)* | Cross-platform reach, standard app surface, small/medium team | (never blocked) |
| **M2** | PWA + Wrapper (Capacitor) | Existing web codebase + thin mobile wrap | iOS push required OR BLE on iOS |

## Desktop Tiers (D0–D1)

| Tier | Name | When to use | Blocked when |
|------|------|------------|--------------|
| **D0** | Native (SwiftUI / WinUI / GTK) | Single platform + deep OS integration | cross-platform requested |
| **D1** | **Cross-platform (Tauri / Electron)** *(default)* | Cross-platform desktop, standard surface | (never blocked) |

## Selection Rule
1. Score every tier in the chosen app class (`runtime.architecture.score_all`).
2. Discard any tier with non-empty `blockers`.
3. Pick the highest score among the remainder.
4. If nothing qualifies, fall back to the class default (T4 / M1 / D1).

## Bias toward defaults
T4, M1, and D1 are never blocked and start at base 60. They scale up with small/medium teams. **Other tiers must explicitly out-score the default — not just be plausible.** This is intentional: most projects are over-engineered, not under-engineered.

## Migration Paths
- **Web**: T2 → T4 when BaaS cost crosses break-even; T4 → T5 when team scales past ~10; T4 → T6 when audit log becomes the source of truth.
- **Mobile**: M2 → M1 when WebView gaps or perf ceiling forces it; M1 → M0 when hardware needs or single-platform focus clarify.
- **Desktop**: D1 → D0 when OS depth or perf demands native; D0 → D1 only when a second platform becomes a requirement.

## Detail Docs
**Web:**
- [T0 — Static Site](./T0-static-site.md)
- [T1 — SPA (no own backend)](./T1-spa.md)
- [T2 — BaaS-Backed](./T2-baas.md)
- [T3 — Serverless / Functions-First](./T3-serverless.md)
- [T4 — Modular Monolith](./T4-modular-monolith.md) ← default
- [T5 — Microservices](./T5-microservices.md)
- [T6 — Event-Driven / Audit-Heavy](./T6-event-driven.md)

**Mobile:**
- [M0 — Native Mobile](./M0-native-mobile.md)
- [M1 — Cross-platform Mobile (Flutter / RN)](./M1-flutter-rn.md) ← default
- [M2 — PWA + Wrapper](./M2-pwa-wrapper.md)

**Desktop:**
- [D0 — Native Desktop](./D0-native-desktop.md)
- [D1 — Cross-platform Desktop (Tauri / Electron)](./D1-cross-desktop.md) ← default
