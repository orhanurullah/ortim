# M0 — Native Mobile (Swift / Kotlin)

> Pick when single-platform focus or hardware-deep workload makes the cross-platform tax indefensible.

## When to use
- BLE-heavy or hardware integration (audio, sensors, ARKit/ARCore)
- High-FPS games, complex 3D, pro audio/video pipelines
- Single platform decision (iOS-only or Android-only product)
- Native SDK depth genuinely required (e.g. SiriKit, Health, HomeKit, Android Auto)
- Apple/Google design language fidelity is a product requirement (full HIG, not 95%)

## When NOT to use
- Cross-platform reach is required → M1 (Flutter)
- Existing web app needs a thin mobile wrap → M2 (PWA)
- Standard CRUD app with no hardware needs → M1, every time

## Architecture
Two codebases (one per platform), independent CI lanes, shared API contract via OpenAPI/protobuf.

## Canonical Tech Stack

| Layer | iOS | Android |
|---|---|---|
| Language | Swift 5.x | Kotlin 1.9+ |
| UI | SwiftUI (primary) + UIKit interop | Jetpack Compose |
| Architecture | MV-style (Composable / TCA) | MVI / MVVM |
| State / DI | Swift Concurrency + Observation | Hilt + Coroutines + StateFlow |
| HTTP | URLSession + async/await | Retrofit + OkHttp |
| Persistence | Core Data / SwiftData | Room |
| Secure storage | Keychain | EncryptedSharedPreferences / Keystore |
| Push | APNs (UserNotifications) | FCM (firebase-messaging) |
| Test | XCTest + Snapshot | JUnit + Espresso + Compose Test |
| Build / Distrib | Xcode + Fastlane → TestFlight | Gradle + Fastlane → Play Internal |

## Module Layout (Swift example)

```
ios/
├── App/
│   └── AppEntry.swift
├── Features/
│   ├── Auth/
│   │   ├── AuthRepository.swift     # PUBLIC
│   │   ├── AuthViewModel.swift
│   │   └── LoginView.swift
│   └── Home/
└── Core/
    ├── APIClient.swift
    ├── Routing.swift
    └── Theme.swift
```

Same layout shape mirrored on Android (`app/src/main/kotlin/.../features/...`).

## Cross-Cutting
- **Hardware workflows**: Native API surfaces directly; no bridge overhead. Document permissions in Info.plist and AndroidManifest.xml at module boundary.
- **Background work**: BackgroundTasks framework (iOS) / WorkManager (Android). Must be explicit; OS limits documented per OS major.
- **Privacy**: Apple Privacy Manifest mandatory; Android Data Safety form synced from a single source-of-truth.

## Test Strategy
- **Unit**: 80% coverage floor on view-models and repositories
- **Snapshot / screenshot**: every reusable view component
- **UI test**: critical flows (login, primary feature happy path)
- **Device matrix**: 1 small + 1 large iPhone, 1 iPad if iPad-supported; 1 entry + 1 flagship Android per major OS version supported

## CI
- iOS: GitHub Actions on macOS runners; Fastlane match for code signing; TestFlight upload on `main`.
- Android: GitHub Actions on Linux; Fastlane supply for Play Console; staged rollout default 10%.
- Both platforms must pass before tagging a release.

## Risks
| Risk | Impact | Mitigation |
|---|---|---|
| Two codebases drift | Feature parity breaks | Shared OpenAPI/protobuf contract; integration tests on both |
| Apple review velocity | Release cadence variability | Build a 7-day buffer into release planning |
| Native API deprecation each OS major | Code rot | One sprint per OS major dedicated to upgrades |
| Team scaling cost | 2x engineering for parity work | Hard look at M1 every 6 months |

## Migration paths
- **M0 → M1 (cross-platform)** — when feature parity work outpaces feature work. Migrate one feature at a time using Flutter add-to-app; rewrite the rest opportunistically.
- **M0 → M0 (different platform)** — if the second platform becomes a requirement, evaluate M1 first; resist the temptation to "add Android" without considering the cross-platform option.

## Anti-patterns
1. Sharing platform-specific code via copy-paste — extract a shared backend contract instead.
2. Hand-rolling networking layers — Retrofit and URLSession suffice; concurrency wrappers should be thin.
3. Skipping snapshot tests because "the design will change" — they are also a contract for review diffs.
