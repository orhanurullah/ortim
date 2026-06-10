# D1 — Cross-platform Desktop (Tauri / Electron)

> **The default desktop tier.** Never blocked. Picked when no other desktop tier strongly out-scores it.

## When to use
- Desktop reach across macOS + Windows (and ideally Linux)
- Solo or small team, single-codebase economics matter
- Web-stack frontend (React / Svelte / Vue) is acceptable
- Standard surface: windows, file IO, system tray, notifications, auto-update

## When NOT to use
- Single platform with deep OS integration (Mac-only Finder extension, Windows shell extension) → D0
- Hard performance ceiling (audio DAW plugin host, video editor render path) → D0
- Pro-grade UX fidelity required — Tauri/Electron WebView gaps are visible to power users

## Architecture
**Default: Tauri.** Smaller binaries, tighter security model (Rust backend, allowlisted commands), modern updater. Pick Electron only when one of:
- Existing Electron codebase
- Heavy reuse of Node-only ecosystem (e.g. native node modules with no Rust equivalent)
- Team has zero Rust appetite and the binary-size tradeoff is acceptable

## Canonical Tech Stack

| Layer | Tauri (default) | Electron (alt.) |
|---|---|---|
| Frontend | React / Svelte / Vue | same |
| Backend | Rust | Node.js |
| IPC | `invoke()` allowlisted commands | `ipcMain` / `ipcRenderer` |
| Auto-update | tauri-updater (signed) | electron-updater |
| Auth (OAuth) | tauri-plugin-deep-link | electron-deep-linking |
| Local storage | rusqlite / sqlx + Tauri APIs | better-sqlite3 / Knex |
| Tray / window | Tauri APIs | Electron Tray + BrowserWindow |
| Bundling | tauri-bundler (.dmg, .msi, .AppImage, .deb) | electron-builder |
| Code signing | Apple notarization + Windows Authenticode | same |

## Layout (Tauri)

```
project/
├── src/                  # frontend (React/Svelte/Vue)
│   ├── features/
│   ├── core/
│   └── main.tsx
├── src-tauri/
│   ├── src/
│   │   ├── main.rs       # Tauri entry; allowlist commands
│   │   ├── commands/
│   │   └── state.rs
│   ├── Cargo.toml
│   ├── tauri.conf.json
│   └── icons/
├── package.json
└── vite.config.ts
```

## Cross-Cutting
- **Updates**: signed updater mandatory. Tauri uses Ed25519; Electron uses code-signing + Squirrel/MSIX. CI must produce signed artifacts; never ship unsigned.
- **Code signing**: Apple Developer ID (paid), Windows EV certificate (paid). Budget for these from day one.
- **Single-instance**: enforce — both Tauri and Electron have plugins.
- **Deep links**: per-OS registration in the bundle config; tested in CI.
- **Logs**: structured logs to `~/Library/Logs/<app>/` (macOS), `%APPDATA%/<app>/logs/` (Windows). Rotate.
- **Crash reports**: Sentry desktop SDK for both.

## Test Strategy
- **Frontend**: standard web test stack (Vitest / Jest / Playwright for E2E).
- **Backend (Tauri)**: Rust unit + integration tests on commands.
- **End-to-end**: Playwright in dev-server mode + manual device-class pass on each platform per release.
- **Signing smoke**: `codesign --verify --deep` (macOS) and `signtool verify` (Windows) in CI.

## CI
- GitHub Actions matrix: macOS, Windows, (optionally) Linux runners.
- Each platform produces its installer artifact.
- Auto-update channel: stable / beta. Beta receives merges first; stable promoted manually.
- Notarization on macOS in CI; secrets via OIDC or GitHub Encrypted Secrets.

## Risks
| Risk | Impact | Mitigation |
|---|---|---|
| Apple notarization rejection | Ship blocked | CI runs notarization on every `main` build, not only release tags |
| Windows SmartScreen warning until reputation accrues | Bad install UX for first ~10K users | Publisher cert, signed installers, document the warning in release notes |
| Tauri 2.x migration | Breaking changes between majors | One sprint per major to migrate |
| WebView discrepancies (WKWebView vs WebView2 vs WebKitGTK) | Visual / behavior bugs cross-platform | Per-platform manual test pass; Playwright cross-platform suite |
| Auto-update signing key loss | Cannot ship updates | Backup keys offline; document recovery procedure |

## Migration paths
- **D1 → D0 (native)** — when OS integration depth or perf ceiling forces it. One platform at a time, repository pattern preserves shared business logic.
- **D1 → web-only** — sometimes a web app suffices; the desktop tier was added for distribution that's no longer needed.
- **Tauri ↔ Electron** within D1 — possible but expensive (different IPC, different update story); only justified by ecosystem dependency.

## Anti-patterns
1. Allowlisting `*` in Tauri command surface — defeats the security model.
2. Embedding secrets in the frontend bundle — bundles are inspectable.
3. Auto-update without signing — supply-chain risk.
4. Skipping Linux because "we'll add it later" — late migration is harder than initial design.
