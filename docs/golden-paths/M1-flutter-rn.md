# M1 — Cross-platform Mobile (Flutter / React Native)

> **The default mobile tier.** Never blocked. Picked when no other mobile tier strongly out-scores it.

## When to use
- Cross-platform reach (iOS + Android) is required
- Solo or small team, mobile-first product
- Standard app surface: lists, forms, navigation, network, offline-first
- Time-to-market matters; one codebase, one CI
- Push, biometric, camera, deep links — all available via well-maintained packages

## When NOT to use
- Hardware-bound or hardware-deep workload (BLE-heavy, AR/ARKit specific, pro audio) → M0
- High-FPS games or complex 3D — Skia render path caps it; use M0 with native/Unity/Unreal
- Existing mature web app, mobile is a thin wrap → M2
- Single platform only with deep OS integration — M0 may be cheaper

## Architecture
Single Flutter (or RN) codebase, two CI lanes (iOS + Android), shared business logic and UI.

**Default stack (this is the canonical choice):** Flutter. RN is acceptable but only when the team already has a JS/React stack and wants identifier-level reuse with web.

## Canonical Tech Stack

| Layer | Flutter (default) | React Native (alt.) |
|---|---|---|
| Language | Dart 3.x | TypeScript |
| State management | Riverpod (default) / Bloc | Zustand / Redux Toolkit |
| HTTP | dio + interceptors | axios / fetch + tanstack-query |
| Navigation | go_router | React Navigation |
| Local storage | drift (SQLite) / isar | WatermelonDB / MMKV |
| Secure storage | flutter_secure_storage | react-native-keychain |
| Push | firebase_messaging | @react-native-firebase/messaging |
| Crash reporting | Sentry / Firebase Crashlytics | same |
| CI | Codemagic / GitHub Actions + Fastlane | EAS Build / GitHub Actions |
| Distribution | TestFlight (iOS), internal track (Android) | same |

## Module Layout (Flutter)

```
lib/
├── main.dart                         # entry point — runs the bootstrap
├── core/
│   ├── api_client.dart               # dio instance, interceptors, auth header
│   ├── app_router.dart               # go_router config + guards
│   ├── theme.dart
│   └── env.dart                      # const-fold environment knobs
├── features/
│   ├── auth/
│   │   ├── auth_repository.dart      # PUBLIC: only file other features import
│   │   ├── auth_controller.dart      # Riverpod notifier
│   │   ├── login_page.dart
│   │   └── widgets/
│   ├── home/
│   │   ├── home_repository.dart
│   │   ├── home_controller.dart
│   │   ├── home_page.dart
│   │   └── widgets/
│   └── ...
└── shared/
    ├── widgets/                      # truly shared widgets only
    └── models/                       # pure value objects, no IO
```

**Module boundary rule:** every `features/<X>/` exports exactly one `*_repository.dart` (the public type-checked surface). Other features import that file only — never `*_controller.dart` or pages.

## State Management — Decision Matrix

| Scenario | Pick |
|---|---|
| New project, solo / small team | Riverpod |
| Team already on Bloc | Bloc |
| Heavy form/wizard interactions | Riverpod (better local-scope) |
| Complex async state machines | Bloc (better state→state contracts) |
| Avoid both: never use setState beyond a single widget |

## Cross-Cutting

- **Offline-first**: drift (SQL, type-safe migrations) for relational; isar for object/document. Cache layer between repository and API; conflict resolution explicit.
- **Secure storage**: `flutter_secure_storage` for tokens. Never plain `SharedPreferences`.
- **Deep links**: `app_links` package; `iOS Universal Links` + `Android App Links` configured per release lane.
- **Push**: Firebase Cloud Messaging both platforms. iOS APNS auth key stored in keychain on the build server, not in repo.
- **Localization**: `flutter_localizations` + `intl`; ARB files under `lib/l10n/`.
- **Theming**: light + dark mandatory; Material 3 default.

## Test Strategy

| Layer | Tool | Floor |
|---|---|---|
| Unit (pure Dart) | `package:test` + `mocktail` | 70% line coverage on `core/` and repositories |
| Widget | `flutter_test` | every page has at least one render+tap test |
| Integration | `integration_test` | one happy-path per critical feature; one offline path |
| Golden | `golden_toolkit` | optional; if visual regression matters |

**Hard gates**: integration test for login + main flow; widget test for any screen with non-trivial state.

## CI

- **GitHub Actions or Codemagic.** PR pipeline: `flutter analyze` → `flutter test` → integration emulator (Android) — iOS integration only on `main` due to runner cost.
- **Fastlane** for store upload. `fastlane/Appfile` and `fastlane/Fastfile` checked in. Secrets via env / keychain.
- **Versioning:** semantic version + monotonic `buildNumber`; CI bumps automatically on `main`.
- **Distribution:** TestFlight + Firebase App Distribution for testers; staged rollout for production.

## Risks

| Risk | Impact | Mitigation |
|---|---|---|
| Flutter major version churn | Breaking changes every 12–18 months | Pin SDK in `pubspec.yaml`; track release notes per upgrade |
| iOS native plugin breakage | App rejected at review | CI runs iOS build + smoke daily |
| Android background limits (Doze, App Standby) | Background-sync flakiness | Use WorkManager via `workmanager` package; document constraints |
| Apple Privacy Manifest changes | Submission rejected | Maintain `PrivacyInfo.xcprivacy`; update on each iOS major |
| Skia → Impeller transition (iOS) | Render regressions | Test on `--enable-impeller` and `--no-enable-impeller` for one release after a major Flutter upgrade |
| Flutter ↔ native bridge channel | Memory leaks via stream subscriptions | Audit MethodChannel/EventChannel disposal; use `AppLifecycleListener` |

## Migration Paths

- **M1 → M0 (native)** — when one of: single platform decision, heavy hardware workload, perf ceiling hit. Step 1: extract repository interfaces. Step 2: rewrite UI in SwiftUI / Compose. Step 3: keep one Dart/RN codebase per platform if cost-justified, else delete.
- **M1 → M2 (PWA wrapper)** — almost never. The reverse direction (M2 → M1) is far more common.
- **M1 → server tier upgrade** — when the API needs T5 microservices, the mobile tier doesn't move; the API does.

## Anti-patterns (avoid)
1. Cross-feature imports of internal files — only `*_repository.dart` is public.
2. Top-level singletons — use Riverpod providers.
3. Synchronous network calls in `build()` — use `FutureProvider` / `StreamProvider`.
4. Handwritten platform channel code without dispose handling — leak risk.
5. Mixing Bloc and Riverpod in one project — pick one.
