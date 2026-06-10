# D0 — Native Desktop (SwiftUI / WinUI / GTK)

> Pick when single-platform focus, OS integration depth, or performance ceiling justifies the platform-specific cost.

## When to use
- Single platform decision (macOS-only studio app, Windows-only enterprise tool)
- Deep OS integration: Finder/Quick Look extensions, Windows shell handlers, system services, status menu apps
- Performance-sensitive workload: DAW, video editor, 3D viewer, latency-critical pro tools
- HIG fidelity matters — power users notice the gaps a WebView leaves

## When NOT to use
- Cross-platform reach is required → D1 (Tauri/Electron)
- Standard CRUD app or dashboard → D1, every time
- Web app already exists, mobile is a secondary surface → not D0; reconsider whether desktop is needed at all

## Architecture
Single platform → single codebase. No cross-platform abstraction; native APIs directly.

## Canonical Tech Stack

| Layer | macOS | Windows | Linux |
|---|---|---|---|
| Language | Swift 5.x | C# (.NET 8+) / C++ | C/C++/Rust + GTK4 |
| UI | SwiftUI + AppKit interop | WinUI 3 / WPF (legacy) | GTK4 / Qt |
| State | Combine / Swift Concurrency | INotifyPropertyChanged + MVVM | Manual via callbacks |
| Persistence | Core Data / SwiftData | SQLite + EF Core | sqlite3 / libpq |
| Auto-update | Sparkle | Squirrel / MSIX deployment | flatpak / native package manager |
| Distribution | Mac App Store / direct DMG | Microsoft Store / signed MSI | flatpak / .deb / .rpm |

Pick **one** column based on the chosen platform. Don't multi-target at this tier — that's D1's job.

## Layout (SwiftUI / macOS example)

```
MyApp/
├── MyApp.xcodeproj
├── App/
│   └── MyAppApp.swift           # @main entry
├── Features/
│   ├── Library/
│   │   ├── LibraryStore.swift   # Observable
│   │   ├── LibraryView.swift
│   │   └── LibraryDetailView.swift
│   └── Settings/
└── Core/
    ├── APIClient.swift
    ├── Persistence.swift
    └── Theme.swift
```

## Cross-Cutting
- **OS extension points**: Quick Look, Spotlight, Share extensions on macOS; Shell handlers and Power Toys-style services on Windows. These are exactly why D0 exists; document each per release.
- **Sandboxing**: macOS App Sandbox + entitlements explicit; Mac App Store distribution requires it. Direct DMG distribution can opt out but loses Spotlight indexing benefits.
- **Code signing & notarization**: paid certificates mandatory. Apple Developer Program $99/year; Windows EV cert ~$300/year and up.
- **Accessibility**: VoiceOver, Narrator, AT-SPI — first-class on this tier; tests below.

## Test Strategy
- **Unit**: ≥70% coverage on domain layer
- **UI snapshot**: SwiftUI ViewInspector or Xcode preview snapshots
- **Accessibility**: automated audit on critical flows (`accessibilityIdentifier`, label coverage)
- **Performance**: instruments time profile baseline per release; fail CI if regression > 10% on a hot path benchmark

## CI
- macOS GitHub Actions runner; Xcode + Fastlane for build, sign, notarize.
- App Store Connect upload via altool or xcrun notarytool; staged release default.
- Windows: GitHub Actions Windows runner; signtool sign + Squirrel package.

## Risks
| Risk | Impact | Mitigation |
|---|---|---|
| OS major upgrade (macOS / Windows) | API deprecations every 12 months | Sprint-per-major dedicated to upgrade |
| Notarization service downtime | Ship blocked | Build in CI continuously, not only on release |
| Signing certificate expiry | Updates blocked | Calendar reminder 90 days before expiry |
| Single-platform lock-in | Pivot cost grows over time | Repository pattern keeps domain logic portable |
| Mac App Store rejection over sandbox entitlements | App-store ship blocked | Document each entitlement's justification |

## Migration paths
- **D0 → D1** — when the second platform becomes a requirement. Migration is non-trivial; budget at least 2 sprints of rewrite. Keep domain layer portable to ease this.
- **D0 (one platform) → D0 (different platform)** — equivalent to a rewrite; evaluate D1 first.

## Anti-patterns
1. Bundling Electron-style behavior into a native app to "share with the team" — defeats the tier.
2. Skipping accessibility because "users won't need it" — accessibility is also a contract for review.
3. Hard-coding paths to system locations — use the OS-provided directory APIs.
