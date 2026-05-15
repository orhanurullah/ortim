# SPDX-License-Identifier: FSL-1.1-Apache-2.0
# Copyright (c) 2026 ortim.dev
"""Deterministic workspace scaffolding.

The Worker is responsible for *feature code inside its module_scope*, never
for repository setup. Module folders, root config files, and tooling
skeletons are written by this layer **once**, before tasking starts, so the
Orchestrator never needs to emit a "scaffold the repo" task (which by
definition would write outside any single module's scope and trip the
sandbox).

Idempotent: every existing file is left alone. Re-running is a no-op.

Currently implemented templates: T2/web (Node + TypeScript). Other tier ×
app_class combinations fall through to the universal default — module
folders + `.gitkeep` placeholders only — until their template is added.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from runtime.architecture.locked_stack import LockedStack

# Universal defaults written for every tier/app_class. Module folders + a
# `.gitkeep` so the directory survives in git, plus a baseline `.gitignore`.
_UNIVERSAL_GITIGNORE = """\
.env
.ai-factory.env
*.log
.DS_Store
"""

# ---- T2/web template (Node + TypeScript + Supabase) ------------------

_T2_WEB_GITIGNORE_EXTRA = """\
node_modules/
dist/
"""

_T2_WEB_TSCONFIG = {
    "compilerOptions": {
        "target": "ES2022",
        "module": "ESNext",
        "moduleResolution": "Bundler",
        "strict": True,
        "esModuleInterop": True,
        "skipLibCheck": True,
        "forceConsistentCasingInFileNames": True,
        "resolveJsonModule": True,
        "outDir": "dist",
    },
    "exclude": ["node_modules", "dist"],
}


def _tsconfig_for_stack(locked_stack: "LockedStack | None") -> dict:
    """Build the tsconfig with stack-aware compilerOptions. When the
    locked stack includes React, `jsx` and `lib` get set so the Worker's
    .tsx files compile without manual intervention — closing one of the
    four item-26 categories (JSX flag missing)."""
    cfg = {
        "compilerOptions": dict(_T2_WEB_TSCONFIG["compilerOptions"]),
        "exclude": list(_T2_WEB_TSCONFIG["exclude"]),
    }
    has_react = locked_stack is not None and any(
        lib.strip().lower() == "react" for lib in locked_stack.key_libraries
    )
    if has_react:
        cfg["compilerOptions"]["jsx"] = "react-jsx"
        cfg["compilerOptions"]["lib"] = ["ES2022", "DOM", "DOM.Iterable"]
    return cfg


# Map of npm package names to (dep_kind, version_spec). `dep_kind` is
# either "dependencies" or "devDependencies". Used by `_t2_web_package_json`
# when a LockedStack is provided so the generated package.json has the
# stack's libraries declared up-front — Worker can rely on them being
# installable instead of writing `npm install` instructions.
_NPM_DEP_REGISTRY: dict[str, tuple[str, str]] = {
    # Frameworks
    "react": ("dependencies", "^18.3.1"),
    "react-dom": ("dependencies", "^18.3.1"),
    "vue": ("dependencies", "^3.4.0"),
    "next": ("dependencies", "^14.2.0"),
    "hono": ("dependencies", "^4.5.0"),
    "express": ("dependencies", "^4.19.0"),
    # Persistence
    "sql.js": ("dependencies", "^1.10.3"),
    "better-sqlite3": ("dependencies", "^11.0.0"),
    # Item 47 — browser-side persistence (surfaced by v4 proof-point after
    # the BaaS-drift fix widened StackAnalyst's autonomous range from sql.js
    # to include idb/dexie/localforage as common browser DB choices).
    "idb": ("dependencies", "^8.0.0"),
    "dexie": ("dependencies", "^4.0.7"),
    "localforage": ("dependencies", "^1.10.0"),
    # Validation
    "zod": ("dependencies", "^3.23.0"),
    # CLI / utils
    "commander": ("dependencies", "^12.1.0"),
    "uuid": ("dependencies", "^10.0.0"),
    # Test + build (dev)
    "vitest": ("devDependencies", "^2.0.0"),
    "vite": ("devDependencies", "^5.4.0"),
    "@vitejs/plugin-react": ("devDependencies", "^4.3.0"),
    "@vitejs/plugin-vue": ("devDependencies", "^5.1.0"),
    "typescript": ("devDependencies", "^5.5.0"),
    "@types/node": ("devDependencies", "^22.0.0"),
    "@types/react": ("devDependencies", "^18.3.0"),
    "@types/react-dom": ("devDependencies", "^18.3.0"),
    "@types/uuid": ("devDependencies", "^10.0.0"),
    "@types/sql.js": ("devDependencies", "^1.4.0"),
    "@types/better-sqlite3": ("devDependencies", "^7.6.0"),
    "@types/commander": ("devDependencies", "^2.12.0"),
    "@types/express": ("devDependencies", "^4.17.0"),
    # Item 41' — React testing-library + jsdom env. Without these, Worker's
    # component-test tasks (e.g. proof-point v2 T-007 App.test.tsx) hit
    # "Cannot find package '@testing-library/react'" at vitest startup.
    "@testing-library/react": ("devDependencies", "^16.0.0"),
    "@testing-library/jest-dom": ("devDependencies", "^6.4.0"),
    "@testing-library/user-event": ("devDependencies", "^14.5.0"),
    "jsdom": ("devDependencies", "^25.0.0"),
    # Item 47b — IndexedDB shim for jsdom test env. Without this, Worker
    # tests for idb/dexie repositories fail with "indexedDB is not defined"
    # (jsdom doesn't ship a real IndexedDB). Proof-point v4 T-002 surfaced
    # this when the Worker correctly imported `fake-indexeddb/auto` after
    # the first attempt failed but `fake-indexeddb` wasn't installed.
    "fake-indexeddb": ("devDependencies", "^6.0.0"),
}

# Item 47b — browser-persistence libs that need `fake-indexeddb` shim for
# jsdom-based test environments. When any of these is in key_libraries,
# bootstrap auto-pulls fake-indexeddb as a devDependency, mirroring the
# react → @vitejs/plugin-react auto-pull pattern.
_INDEXEDDB_PEERS: tuple[str, ...] = ("idb", "dexie", "localforage")

# Item 41: primary_framework → list of npm package names. Proof-point E2E
# (workspace `ed9f6074f1b8`, 2026-05-14) revealed that `_t2_web_package_json`
# only consumed `stack.key_libraries`, so a stack with
# `primary_framework="React + Vite"` and `key_libraries=[sql.js, zod]` produced
# a package.json without `react` or `vite` — tests failed with `Cannot find
# package 'react'` on the very first run.
#
# Keys are lowercased, whitespace-normalized. Multiple variants of the same
# framework (e.g. `"React + Vite"` vs `"react+vite"` vs `"Vite + React"`) are
# listed explicitly rather than parsed by regex — fewer surprises, easier
# to extend.
_REACT_VITE_PACKAGES = [
    "react",
    "react-dom",
    "vite",
    "@vitejs/plugin-react",
    # Item 41' — testing-library + jsdom env. Vitest needs jsdom for
    # `document`/`window` in component tests; testing-library provides the
    # render+query API; jest-dom extends expect with DOM matchers.
    "@testing-library/react",
    "@testing-library/jest-dom",
    "@testing-library/user-event",
    "jsdom",
]

_NEXT_PACKAGES = [
    "next",
    "react",
    "react-dom",
    "@testing-library/react",
    "@testing-library/jest-dom",
    "@testing-library/user-event",
    "jsdom",
]

_FRAMEWORK_PACKAGES: dict[str, list[str]] = {
    # React + Vite (browser SPA — matches what Architect typically picks)
    "react + vite": _REACT_VITE_PACKAGES,
    "react+vite": _REACT_VITE_PACKAGES,
    "vite + react": _REACT_VITE_PACKAGES,
    # Vue + Vite
    "vue + vite": ["vue", "vite", "@vitejs/plugin-vue"],
    "vue+vite": ["vue", "vite", "@vitejs/plugin-vue"],
    # Next.js (Vite not needed — Next has its own bundler)
    "next.js": _NEXT_PACKAGES,
    "nextjs": _NEXT_PACKAGES,
    "next": _NEXT_PACKAGES,
    # Single-name frameworks
    "react": ["react", "react-dom"],
    "vue": ["vue"],
    "vite": ["vite"],
    # Server-side (Node)
    "hono": ["hono"],
    "node + hono": ["hono"],
    "node.js + hono": ["hono"],
    "express": ["express", "@types/express"],
    "node + express": ["express", "@types/express"],
    "node.js + express": ["express", "@types/express"],
    # Python frameworks — no npm deps. Listed so the lookup succeeds (returns
    # empty list, no warning) rather than logging a false-positive warning
    # for Python workspaces that happen to share the bootstrap path.
    "fastapi": [],
    "django": [],
    "flask": [],
}


# Item 41' — vite.config.ts content for React + Vite stacks. Wires the
# React plugin for dev server + vitest jsdom env + setupFiles. Without this
# file, vitest defaults to node env and component tests fail with
# `document is not defined` despite testing-library being installed.
_VITE_CONFIG_REACT = """\
/// <reference types="vitest" />
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: './setupTests.ts',
  },
});
"""

# Pulled into vitest at startup. `@testing-library/jest-dom` extends `expect`
# with DOM matchers like `toBeInTheDocument`, `toHaveTextContent`.
_SETUP_TESTS_REACT = """\
import '@testing-library/jest-dom';
"""


def _is_react_stack(locked_stack: "LockedStack | None") -> bool:
    """Return True when the locked stack's primary_framework normalizes to a
    React-based entry in `_FRAMEWORK_PACKAGES`. Used to gate the
    vite.config.ts + setupTests.ts writers."""
    if locked_stack is None:
        return False
    normalized = (locked_stack.primary_framework or "").strip().lower()
    pkgs = _FRAMEWORK_PACKAGES.get(normalized, [])
    return "react" in pkgs


def _is_browser_framework_stack(locked_stack: "LockedStack | None") -> bool:
    """Return True when the locked stack's primary_framework resolves to a
    browser-side framework (React, Vue, Vite, Next.js).

    Item 46: bootstrap's T1/T2/T3-only gate for the web template misses
    valid cases where the deterministic tier scorer picks T4 (Modular
    Monolith) but the user-locked stack is a browser SPA. Proof-point v3
    surfaced this: IntentAnalyst extracted minimal `GoldenPathInputs` from
    the same brief that gave T2 in v2; scorer fell back to T4; bootstrap
    saw `tier="T4"` and skipped writing package.json / tsconfig.json /
    vite.config.ts. Worker then crashed on `Cannot find package 'sql.js'`.

    The locked stack is the user's explicit contract; honor it over the
    heuristic tier when it points at a browser framework.
    """
    if locked_stack is None:
        return False
    normalized = (locked_stack.primary_framework or "").strip().lower()
    pkgs = _FRAMEWORK_PACKAGES.get(normalized, [])
    # Any of these in the package list = it's a browser SPA stack.
    return any(p in pkgs for p in ("react", "vue", "vite", "next"))


def _framework_to_packages(primary_framework: str | None) -> list[str]:
    """Translate `stack.primary_framework` into npm package names.

    Returns the empty list when `primary_framework` is None, empty, or
    unrecognized. Unrecognized strings emit a one-line warning to stderr so
    the operator sees the gap immediately — silently skipping was the
    proof-point's failure mode (item 41).
    """
    if not primary_framework:
        return []
    normalized = primary_framework.strip().lower()
    if normalized in _FRAMEWORK_PACKAGES:
        return list(_FRAMEWORK_PACKAGES[normalized])
    print(
        f"[ortim] WARNING: bootstrap doesn't recognize "
        f"primary_framework={primary_framework!r}; falling back to "
        f"key_libraries-only deps. Add the framework to "
        f"_FRAMEWORK_PACKAGES in runtime/architecture/bootstrap.py.",
        file=sys.stderr,
    )
    return []

# Runtime packages that ship without their own .d.ts and need a matching
# `@types/*` companion in devDependencies. Adding the runtime package
# auto-pulls in the types peer so `tsc --noEmit` doesn't trip on
# implicit-any imports — closes the last face of item 26 ("missing
# declaration for 'sql.js'") that the M4 web-todo-m2 re-run surfaced.
_NPM_TYPES_PEERS: dict[str, str] = {
    "sql.js": "@types/sql.js",
    "better-sqlite3": "@types/better-sqlite3",
    "uuid": "@types/uuid",
    "commander": "@types/commander",
}


def _t2_web_package_json(
    name: str,
    locked_stack: "LockedStack | None" = None,
) -> dict:
    """Build the T2/web package.json. When a LockedStack is provided, the
    stack's `key_libraries` are resolved through `_NPM_DEP_REGISTRY` and
    written into `dependencies` / `devDependencies` so the workspace is
    `npm install`-able without further intervention — closing the
    remaining "missing dependencies" face of item 26.

    Unknown libraries (not in the registry) are skipped silently rather
    than guessed at, so the Worker can pull them in later via Worker
    output operations. This keeps the deterministic layer narrow.
    """
    deps: dict[str, str] = {}
    dev_deps: dict[str, str] = {
        # The bootstrap scripts already assume tsc and vitest are
        # available, so always include their dev deps.
        "typescript": _NPM_DEP_REGISTRY["typescript"][1],
        "vitest": _NPM_DEP_REGISTRY["vitest"][1],
    }
    if locked_stack is not None:
        # Item 41 fix: merge primary_framework packages with key_libraries
        # before resolving. Framework packages come first; key_libraries
        # may add or override (later wins on the same key, but versions are
        # registry-driven so the net effect is dedupe).
        framework_pkgs = _framework_to_packages(locked_stack.primary_framework)
        all_libs: list[str] = list(
            dict.fromkeys([*framework_pkgs, *locked_stack.key_libraries])
        )
        for lib in all_libs:
            normalized = lib.strip().lower()
            entry = _NPM_DEP_REGISTRY.get(normalized)
            if entry is None:
                # Item 47 — surface the silent drop. Pre-fix this branch
                # silently skipped unregistered key_libraries (proof-point
                # v4 hit this when StackAnalyst autonomously picked `idb`,
                # which wasn't in the registry, so package.json shipped
                # without IndexedDB deps even though stack.json listed it).
                print(
                    f"[ortim] WARNING: bootstrap doesn't recognize "
                    f"key_library={lib!r}; not adding to package.json. "
                    f"Add it to _NPM_DEP_REGISTRY in "
                    f"runtime/architecture/bootstrap.py.",
                    file=sys.stderr,
                )
                continue
            kind, version = entry
            (deps if kind == "dependencies" else dev_deps)[normalized] = version
            # React needs react-dom + @types/react peers; Vite needs the
            # React plugin when paired with React. Surface the most common
            # peers so `npm install` doesn't immediately complain.
            if normalized == "react":
                deps["react-dom"] = _NPM_DEP_REGISTRY["react-dom"][1]
                dev_deps["@types/react"] = _NPM_DEP_REGISTRY["@types/react"][1]
                dev_deps["@types/react-dom"] = _NPM_DEP_REGISTRY["@types/react-dom"][1]
            if normalized == "vite" and "react" in deps:
                dev_deps["@vitejs/plugin-react"] = _NPM_DEP_REGISTRY["@vitejs/plugin-react"][1]
            # Item 47b — browser persistence needs an IndexedDB shim for
            # jsdom-based tests. Without this, repository tests fail with
            # `indexedDB is not defined` (jsdom 25 still lacks IndexedDB).
            if normalized in _INDEXEDDB_PEERS:
                dev_deps["fake-indexeddb"] = _NPM_DEP_REGISTRY["fake-indexeddb"][1]
            # Pull in the typed peer if this runtime package needs one.
            types_peer = _NPM_TYPES_PEERS.get(normalized)
            if types_peer is not None:
                peer_entry = _NPM_DEP_REGISTRY.get(types_peer)
                if peer_entry is not None:
                    dev_deps[types_peer] = peer_entry[1]

    pkg: dict = {
        "name": name,
        "version": "0.1.0",
        "private": True,
        "type": "module",
        "scripts": {
            "build": "tsc -p .",
            "test": "vitest run",
            "lint": "eslint .",
        },
        "engines": {"node": ">=20"},
    }
    if deps:
        pkg["dependencies"] = dict(sorted(deps.items()))
    pkg["devDependencies"] = dict(sorted(dev_deps.items()))
    return pkg


def _t2_web_env_example() -> str:
    return (
        "# Copy to .env and fill in real values (.env is gitignored).\n"
        "SUPABASE_URL=\n"
        "SUPABASE_ANON_KEY=\n"
    )


# (tier, app_class) → suggested test command. None means "no default; user
# must set AI_FACTORY_TEST_CMD explicitly". Phase 0 (9c): bootstrap writes
# this into `.ai-factory.env` so the test runner has a fallback when the
# user hasn't exported the env var. Reviewer rubric (9a) marks
# test-dependent criteria as `unverifiable` whenever the runner is skipped,
# so leaving this empty is a real cost — the task escalates to HITL.
_TEST_CMD_BY_TIER_APP: dict[tuple[str, str], str] = {
    ("T1", "web"): "npx vitest run",
    ("T2", "web"): "npx vitest run",
    ("T3", "web"): "npx vitest run",
    ("T1", "mobile"): "flutter test",
    ("T2", "mobile"): "flutter test",
    ("T1", "desktop"): "cargo test",
    ("T2", "desktop"): "cargo test",
}


# Language → canonical test command. Used as a stack-aware fallback when
# (tier, app_class) has no matrix entry — observed in `todo-greenfield-4`
# (T0/web), where every test-shaped acceptance criterion turned
# `unverifiable` because the runner was unset, even though Worker had
# emitted a real Go test file. Item 18 genişlemesi.
_LANG_TEST_CMD: list[tuple[str, str]] = [
    # Order matters: more-specific tokens first to avoid false positives
    # ("rust" matches "rustic"; "go" must not match "good"). We anchor with
    # word-boundary-ish substrings drawn from Tech-Stack-section vocabulary.
    ("flutter", "flutter test"),
    ("dart", "flutter test"),
    ("rust", "cargo test"),
    ("cargo", "cargo test"),
    ("typescript", "npx vitest run"),
    ("node.js", "npx vitest run"),
    ("nodejs", "npx vitest run"),
    ("npm", "npx vitest run"),
    ("python", "pytest"),
    ("fastapi", "pytest"),
    ("go ", "go test ./..."),  # trailing space avoids matching "good", "going"
    ("golang", "go test ./..."),
    ("cobra", "go test ./..."),  # canonical Go CLI library — strong signal
]


def _infer_test_cmd_from_rfc(workspace: Path) -> str | None:
    """Best-effort scan of `<workspace>/RFC.md` § Tech Stack vocabulary to
    pick a test runner when the (tier, app_class) matrix has no entry.

    This is intentionally cheap text matching — not a markdown parser. The
    Architect prompt produces a §4 Tech Stack section with explicit
    language and framework names, so substring checks are reliable enough
    for the greenfield path. Brownfield projects use the codebase reader's
    framework detection instead and don't hit this fallback.

    Returns `None` when the file is missing or no language token matches —
    callers leave `.ai-factory.env` unwritten and the test runner skips,
    which item 9c rubric correctly escalates as `unverifiable`.
    """
    rfc_path = workspace / "RFC.md"
    if not rfc_path.exists():
        return None
    try:
        text = rfc_path.read_text(encoding="utf-8").lower()
    except OSError:
        return None
    for token, cmd in _LANG_TEST_CMD:
        if token in text:
            return cmd
    return None


# (tier, app_class) → language/framework family the Architect Call 2 (RFC
# draft) is allowed to choose. Item 17 fix: thread this into Architect's
# prompt as a HARD constraint so the deterministic scorer's tier and the
# Architect's tech-stack pick stay aligned. Without this, scorer says
# T2/web but Architect freely picks Go+Cobra → bootstrap writes Node/TS
# template → runner missing → tests skip → criteria unverifiable. Observed
# in todo-greenfield-3, 2026-05-08.
#
# Each entry is a one-line, prompt-ready description. The Architect prompt
# quotes it verbatim under "## Tier × Stack Hard Constraint".
_LANG_STACK_BY_TIER_APP: dict[tuple[str, str], str] = {
    ("T0", "web"): "Python single-file CLI, Bash, or Go single-binary",
    ("T1", "web"): "TypeScript + Node (Hono/Express) OR Python + FastAPI",
    ("T2", "web"): "TypeScript + Node (Hono/Express) + Supabase OR Python + FastAPI + Supabase",
    ("T3", "web"): "TypeScript + Node (NestJS/Fastify) OR Python + FastAPI OR Go (per-service language acceptable)",
    ("T1", "mobile"): "Flutter (Dart) OR React Native (TypeScript)",
    ("T2", "mobile"): "Flutter (Dart) + Supabase OR React Native + Supabase",
    ("T1", "desktop"): "Tauri (Rust core + TypeScript UI)",
    ("T2", "desktop"): "Tauri (Rust core + TypeScript UI) OR Electron (TypeScript)",
}


def stack_constraint(tier: str, app_class: str) -> str | None:
    """Returns the prompt-ready language/framework constraint string for a
    (tier, app_class) pair, or `None` if the pair has no constraint defined
    yet (older or experimental tier-app combos). Architect Call 2 falls
    back to free-form selection when `None`.
    """
    return _LANG_STACK_BY_TIER_APP.get((tier, app_class))


# ---- public API ----------------------------------------------------------


def bootstrap_workspace_layout(
    workspace: Path,
    modules: list[str],
    tier: str,
    app_class: str = "web",
    project_name: str = "untitled",
    locked_stack: LockedStack | None = None,
) -> list[Path]:
    """Create module folders + tier/app_class root files. Idempotent.

    Returns the paths actually created (existing files are skipped, not
    listed). The caller decides whether to surface the list to the user or
    pipe it to the audit log.

    `modules` is whatever set the Architect/Orchestrator agreed on for this
    project (e.g. `["cli", "service", "repository", "auth", "shared"]` for a
    todo CLI). `shared` is added implicitly if missing — the prompt
    convention puts cross-cutting resources there.

    `locked_stack` (M2): when present, the test command is read directly
    from `locked_stack.test_cmd` and the tier+app_class heuristic matrices
    (`_TEST_CMD_BY_TIER_APP`, `_infer_test_cmd_from_rfc`) are bypassed.
    This collapses the three previously-decoupled "stack opinion" layers
    (tier scorer, _LANG_STACK_BY_TIER_APP, RFC scan) into a single source
    of truth — closing items 17 + 18a structurally. Greenfield-no-dialog
    flow still falls back to the heuristics.
    """
    workspace.mkdir(parents=True, exist_ok=True)
    created: list[Path] = []

    mods = list(modules)
    if "shared" not in mods:
        mods.append("shared")

    for mod in mods:
        mod_dir = workspace / mod
        mod_dir.mkdir(parents=True, exist_ok=True)
        gitkeep = mod_dir / ".gitkeep"
        if not gitkeep.exists():
            gitkeep.write_text("", encoding="utf-8")
            created.append(gitkeep)

    use_web_template_for_gitignore = (
        (tier in ("T1", "T2", "T3") and app_class == "web")
        or _is_browser_framework_stack(locked_stack)
    )
    gitignore = workspace / ".gitignore"
    if not gitignore.exists():
        body = _UNIVERSAL_GITIGNORE
        if use_web_template_for_gitignore:
            body += _T2_WEB_GITIGNORE_EXTRA
        gitignore.write_text(body, encoding="utf-8")
        created.append(gitignore)

    use_web_template = (
        (tier in ("T1", "T2", "T3") and app_class == "web")
        or _is_browser_framework_stack(locked_stack)
    )
    if use_web_template:
        pkg = workspace / "package.json"
        if not pkg.exists():
            pkg.write_text(
                json.dumps(
                    _t2_web_package_json(project_name, locked_stack=locked_stack),
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
            created.append(pkg)

        tsc = workspace / "tsconfig.json"
        if not tsc.exists():
            cfg = _tsconfig_for_stack(locked_stack)
            cfg["include"] = list(mods)
            tsc.write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")
            created.append(tsc)

        env_example = workspace / ".env.example"
        if not env_example.exists():
            env_example.write_text(_t2_web_env_example(), encoding="utf-8")
            created.append(env_example)

        # Item 41' — when the locked stack is React-based, write a
        # vite.config.ts that wires the React plugin AND configures vitest's
        # jsdom environment + setupFiles. Without this, vitest defaults to a
        # node environment and component tests fail with `document is not
        # defined` even after testing-library is installed.
        if _is_react_stack(locked_stack):
            vite_cfg = workspace / "vite.config.ts"
            if not vite_cfg.exists():
                vite_cfg.write_text(_VITE_CONFIG_REACT, encoding="utf-8")
                created.append(vite_cfg)
            setup_tests = workspace / "setupTests.ts"
            if not setup_tests.exists():
                setup_tests.write_text(_SETUP_TESTS_REACT, encoding="utf-8")
                created.append(setup_tests)

    # `.ai-factory.env`: workspace-scoped fallback for AI_FACTORY_TEST_CMD,
    # so the test runner has a runner to invoke even when the user hasn't
    # exported the env var. Without this, tier ≥ T1 tasks with test-shaped
    # criteria all return `unverifiable` and escalate to HITL.
    #
    # M2 dialog path: `locked_stack.test_cmd` is the single source of
    # truth — heuristics only run when no locked stack exists (legacy
    # AI_FACTORY_DIALOG_MODE=off + brownfield-no-stack flows).
    if locked_stack is not None and locked_stack.test_cmd:
        test_cmd: str | None = locked_stack.test_cmd
    else:
        # Two-tier lookup: tier+app_class matrix first (canonical), RFC scan
        # second (stack-aware fallback for tier/app pairs not in the matrix
        # — e.g. T0/web where the language is whatever Architect Call 2
        # picked).
        test_cmd = _TEST_CMD_BY_TIER_APP.get((tier, app_class))
        if test_cmd is None:
            test_cmd = _infer_test_cmd_from_rfc(workspace)
    if test_cmd is not None:
        ai_env = workspace / ".ai-factory.env"
        if not ai_env.exists():
            ai_env.write_text(
                "# Auto-written by bootstrap. Override via real env vars at runtime.\n"
                f'AI_FACTORY_TEST_CMD="{test_cmd}"\n',
                encoding="utf-8",
            )
            created.append(ai_env)

    return created
