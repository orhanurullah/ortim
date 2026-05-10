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
from pathlib import Path

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


def _t2_web_package_json(name: str) -> dict:
    return {
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
) -> list[Path]:
    """Create module folders + tier/app_class root files. Idempotent.

    Returns the paths actually created (existing files are skipped, not
    listed). The caller decides whether to surface the list to the user or
    pipe it to the audit log.

    `modules` is whatever set the Architect/Orchestrator agreed on for this
    project (e.g. `["cli", "service", "repository", "auth", "shared"]` for a
    todo CLI). `shared` is added implicitly if missing — the prompt
    convention puts cross-cutting resources there.
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

    gitignore = workspace / ".gitignore"
    if not gitignore.exists():
        body = _UNIVERSAL_GITIGNORE
        if tier in ("T1", "T2", "T3") and app_class == "web":
            body += _T2_WEB_GITIGNORE_EXTRA
        gitignore.write_text(body, encoding="utf-8")
        created.append(gitignore)

    if tier in ("T1", "T2", "T3") and app_class == "web":
        pkg = workspace / "package.json"
        if not pkg.exists():
            pkg.write_text(
                json.dumps(_t2_web_package_json(project_name), indent=2) + "\n",
                encoding="utf-8",
            )
            created.append(pkg)

        tsc = workspace / "tsconfig.json"
        if not tsc.exists():
            cfg = dict(_T2_WEB_TSCONFIG)
            cfg["include"] = list(mods)
            tsc.write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")
            created.append(tsc)

        env_example = workspace / ".env.example"
        if not env_example.exists():
            env_example.write_text(_t2_web_env_example(), encoding="utf-8")
            created.append(env_example)

    # `.ai-factory.env`: workspace-scoped fallback for AI_FACTORY_TEST_CMD,
    # so the test runner has a runner to invoke even when the user hasn't
    # exported the env var. Without this, tier ≥ T1 tasks with test-shaped
    # criteria all return `unverifiable` and escalate to HITL.
    #
    # Two-tier lookup: tier+app_class matrix first (canonical), RFC scan
    # second (stack-aware fallback for tier/app pairs not in the matrix —
    # e.g. T0/web where the language is whatever Architect Call 2 picked).
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
