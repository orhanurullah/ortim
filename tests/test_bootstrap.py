# SPDX-License-Identifier: FSL-1.1-Apache-2.0
# Copyright (c) 2026 ortim.dev
"""Tests for runtime.architecture.bootstrap.bootstrap_workspace_layout.

Covers the M1.5 architectural fix: scaffolding (module folders + tier-aware
root files) is owned by the system, not the Worker. The Worker therefore
never needs to emit a "scaffold the repo" task that would write outside its
module_scope.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from runtime.architecture import LockedStack, bootstrap_workspace_layout
from runtime.architecture.bootstrap import _framework_to_packages


def test_creates_module_folders_with_gitkeep(tmp_path: Path) -> None:
    bootstrap_workspace_layout(
        tmp_path,
        modules=["cli", "service", "auth"],
        tier="T2",
        app_class="web",
        project_name="todo",
    )
    for mod in ("cli", "service", "auth", "shared"):  # `shared` auto-added
        assert (tmp_path / mod / ".gitkeep").exists(), f"{mod}/.gitkeep missing"


def test_t2_web_writes_tier_root_files(tmp_path: Path) -> None:
    bootstrap_workspace_layout(
        tmp_path,
        modules=["cli", "shared"],
        tier="T2",
        app_class="web",
        project_name="todo",
    )
    pkg = json.loads((tmp_path / "package.json").read_text(encoding="utf-8"))
    assert pkg["name"] == "todo"
    assert "build" in pkg["scripts"]

    tsc = json.loads((tmp_path / "tsconfig.json").read_text(encoding="utf-8"))
    assert tsc["compilerOptions"]["strict"] is True
    assert "cli" in tsc["include"] and "shared" in tsc["include"]

    assert (tmp_path / ".gitignore").read_text(encoding="utf-8").count("node_modules") == 1
    assert (tmp_path / ".env.example").exists()


def test_idempotent_does_not_overwrite_existing(tmp_path: Path) -> None:
    pkg_path = tmp_path / "package.json"
    pkg_path.parent.mkdir(parents=True, exist_ok=True)
    pkg_path.write_text('{"name":"already-here","version":"9.9.9"}\n', encoding="utf-8")

    created = bootstrap_workspace_layout(
        tmp_path,
        modules=["shared"],
        tier="T2",
        app_class="web",
        project_name="todo",
    )

    assert pkg_path not in created
    assert json.loads(pkg_path.read_text(encoding="utf-8"))["name"] == "already-here"


def test_unknown_tier_app_class_falls_back_to_module_layout(tmp_path: Path) -> None:
    bootstrap_workspace_layout(
        tmp_path,
        modules=["lib"],
        tier="T0",
        app_class="mobile",  # mobile template not implemented yet
        project_name="todo",
    )
    assert (tmp_path / "lib" / ".gitkeep").exists()
    assert (tmp_path / "shared" / ".gitkeep").exists()
    assert (tmp_path / ".gitignore").exists()
    assert not (tmp_path / "package.json").exists()
    assert not (tmp_path / "tsconfig.json").exists()


def test_second_call_is_noop(tmp_path: Path) -> None:
    first = bootstrap_workspace_layout(
        tmp_path, modules=["cli"], tier="T2", app_class="web", project_name="todo"
    )
    second = bootstrap_workspace_layout(
        tmp_path, modules=["cli"], tier="T2", app_class="web", project_name="todo"
    )
    assert first  # first run created stuff
    assert second == []  # second run created nothing


def test_t2_web_writes_ai_factory_env_with_vitest_cmd(tmp_path: Path) -> None:
    bootstrap_workspace_layout(
        tmp_path, modules=["cli"], tier="T2", app_class="web", project_name="todo"
    )
    ai_env = tmp_path / ".ai-factory.env"
    assert ai_env.exists()
    body = ai_env.read_text(encoding="utf-8")
    assert "AI_FACTORY_TEST_CMD" in body
    assert "vitest" in body


def test_unknown_tier_app_class_skips_ai_factory_env(tmp_path: Path) -> None:
    bootstrap_workspace_layout(
        tmp_path, modules=["lib"], tier="T0", app_class="mobile", project_name="todo"
    )
    assert not (tmp_path / ".ai-factory.env").exists()


def test_universal_gitignore_includes_ai_factory_env(tmp_path: Path) -> None:
    bootstrap_workspace_layout(
        tmp_path, modules=["cli"], tier="T0", app_class="mobile", project_name="todo"
    )
    body = (tmp_path / ".gitignore").read_text(encoding="utf-8")
    assert ".ai-factory.env" in body


# ---------- Item 18 genişlemesi: stack-aware test cmd fallback ----------


def test_t0_web_falls_back_to_rfc_language_for_test_cmd_go(tmp_path: Path) -> None:
    """T0/web has no matrix entry; bootstrap must read RFC.md and infer
    the test runner from the language mentioned in §4 Tech Stack. Repro
    of `todo-greenfield-4` T-005 failure mode."""
    (tmp_path / "RFC.md").write_text(
        "# RFC\n\n## §4 Tech Stack\n\n- Language: Go (golang) with Cobra CLI\n",
        encoding="utf-8",
    )
    bootstrap_workspace_layout(
        tmp_path, modules=["cmd"], tier="T0", app_class="web", project_name="todo"
    )
    ai_env = tmp_path / ".ai-factory.env"
    assert ai_env.exists()
    body = ai_env.read_text(encoding="utf-8")
    assert "go test" in body, body


def test_t0_web_falls_back_to_rfc_language_for_test_cmd_typescript(
    tmp_path: Path,
) -> None:
    """Same fallback, different language: RFC says TypeScript → vitest."""
    (tmp_path / "RFC.md").write_text(
        "# RFC\n\n## §4 Tech Stack\n\n- TypeScript on Node.js\n",
        encoding="utf-8",
    )
    bootstrap_workspace_layout(
        tmp_path, modules=["cmd"], tier="T0", app_class="web", project_name="todo"
    )
    body = (tmp_path / ".ai-factory.env").read_text(encoding="utf-8")
    assert "vitest" in body, body


def test_t0_web_no_rfc_no_test_cmd_written(tmp_path: Path) -> None:
    """When neither matrix entry nor RFC is available, test-cmd write is
    skipped — Reviewer rubric (item 9a) will mark test-shaped criteria
    `unverifiable` and escalate, which is the correct semantic."""
    bootstrap_workspace_layout(
        tmp_path, modules=["cmd"], tier="T0", app_class="web", project_name="todo"
    )
    assert not (tmp_path / ".ai-factory.env").exists()


def test_matrix_entry_wins_over_rfc_fallback(tmp_path: Path) -> None:
    """When a (tier, app_class) matrix entry exists, the RFC fallback is
    not consulted — explicit canonical mapping beats best-effort scanning."""
    (tmp_path / "RFC.md").write_text(
        "# RFC\n\n## §4 Tech Stack\n\n- Go with Cobra\n", encoding="utf-8"
    )
    bootstrap_workspace_layout(
        tmp_path, modules=["cli"], tier="T2", app_class="web", project_name="todo"
    )
    body = (tmp_path / ".ai-factory.env").read_text(encoding="utf-8")
    assert "vitest" in body, "T2/web matrix entry must beat RFC's Go signal"
    assert "go test" not in body


# ---------------------------------------------------------------------------
# Item 41 — primary_framework deps map. Without this, a stack with
# primary_framework="React + Vite" and key_libraries=[sql.js, zod] produced
# a package.json missing react/react-dom/vite — proof-point E2E hit
# `Cannot find package 'react'` on the very first test run (workspace
# ed9f6074f1b8, 2026-05-14).
# ---------------------------------------------------------------------------


def _ts_react_stack() -> LockedStack:
    """The exact stack shape that surfaced item 41 in the proof-point."""
    return LockedStack(
        tier="T2",
        app_class="web",
        language="TypeScript",
        primary_framework="React + Vite",
        package_manager="npm",
        test_cmd="npx vitest run",
        run_cmd="npm run dev",
        key_libraries=["sql.js", "zod"],
    )


def test_react_vite_framework_pulls_in_react_and_vite_deps(tmp_path: Path) -> None:
    """When key_libraries is [sql.js, zod] but primary_framework='React + Vite',
    package.json must still get react/react-dom/vite installed — otherwise
    `Cannot find package 'react'` at first test run (proof-point E2E).

    Also asserts Item 41' additions: testing-library + jsdom are installed so
    React component tests don't hit `Cannot find package '@testing-library/react'`
    (proof-point v2 T-007).
    """
    bootstrap_workspace_layout(
        tmp_path,
        modules=["shared", "components"],
        tier="T2",
        app_class="web",
        project_name="todo",
        locked_stack=_ts_react_stack(),
    )
    pkg = json.loads((tmp_path / "package.json").read_text(encoding="utf-8"))
    deps = pkg.get("dependencies", {})
    dev_deps = pkg.get("devDependencies", {})

    # Framework-derived (Item 41)
    assert "react" in deps, "primary_framework='React + Vite' must install react"
    assert "react-dom" in deps, "react peer must be installed alongside react"
    assert "vite" in dev_deps, "vite must be installed for React + Vite stack"
    assert "@vitejs/plugin-react" in dev_deps, (
        "React + Vite must install the Vite React plugin"
    )
    assert "@types/react" in dev_deps and "@types/react-dom" in dev_deps

    # Test-tier deps (Item 41')
    assert "@testing-library/react" in dev_deps, (
        "Item 41': React stack must install testing-library/react"
    )
    assert "@testing-library/jest-dom" in dev_deps
    assert "@testing-library/user-event" in dev_deps
    assert "jsdom" in dev_deps, "Item 41': jsdom needed for component test env"

    # key_libraries still respected
    assert "sql.js" in deps
    assert "zod" in deps


def test_react_vite_writes_vite_config_with_jsdom_env(tmp_path: Path) -> None:
    """Item 41' — without vite.config.ts setting `test.environment: 'jsdom'`,
    component tests fail with `document is not defined` even after
    testing-library is installed. Bootstrap writes it deterministically."""
    bootstrap_workspace_layout(
        tmp_path,
        modules=["shared", "components"],
        tier="T2",
        app_class="web",
        project_name="todo",
        locked_stack=_ts_react_stack(),
    )
    vite_cfg = tmp_path / "vite.config.ts"
    assert vite_cfg.exists(), "React + Vite must produce a vite.config.ts"
    body = vite_cfg.read_text(encoding="utf-8")
    assert "environment: 'jsdom'" in body
    assert "@vitejs/plugin-react" in body
    assert "setupFiles" in body

    setup_tests = tmp_path / "setupTests.ts"
    assert setup_tests.exists(), "setupTests.ts must accompany vite config"
    assert "@testing-library/jest-dom" in setup_tests.read_text(encoding="utf-8")


def test_t4_tier_with_locked_react_stack_still_writes_package_json(
    tmp_path: Path,
) -> None:
    """Item 46 — proof-point v3 surfaced this: IntentAnalyst extracted
    minimal inputs from the brief; deterministic scorer fell back to T4
    (Modular Monolith); bootstrap's `tier in T1/T2/T3` gate failed and no
    package.json was written, despite the user having locked a React +
    Vite SPA. Worker crashed on `Cannot find package 'sql.js'`.

    Fix: when locked_stack.primary_framework is a browser framework, run
    the web template regardless of tier."""
    bootstrap_workspace_layout(
        tmp_path,
        modules=["task", "ui"],
        tier="T4",  # The exact tier scorer's v3 fallback
        app_class="web",
        project_name="todo",
        locked_stack=_ts_react_stack(),
    )
    pkg_path = tmp_path / "package.json"
    assert pkg_path.exists(), (
        "Item 46: locked React+Vite stack must produce package.json even "
        "when the deterministic tier scorer says T4"
    )
    pkg = json.loads(pkg_path.read_text(encoding="utf-8"))
    deps = pkg.get("dependencies", {})
    assert "react" in deps and "sql.js" in deps

    # Vite config + setupTests must also fire under the locked-stack gate
    assert (tmp_path / "vite.config.ts").exists()
    assert (tmp_path / "setupTests.ts").exists()


def test_t4_tier_with_hono_locked_stack_does_not_force_web_template(
    tmp_path: Path,
) -> None:
    """Item 46 must not over-trigger: Hono (server framework) on T4 should
    still skip the web template, even though it's also a TypeScript stack."""
    hono_stack = LockedStack(
        tier="T4",
        app_class="web",
        language="TypeScript",
        primary_framework="Hono",
        package_manager="npm",
        test_cmd="npx vitest run",
        run_cmd="npm start",
        key_libraries=["zod"],
    )
    bootstrap_workspace_layout(
        tmp_path,
        modules=["api"],
        tier="T4",
        app_class="web",
        project_name="api",
        locked_stack=hono_stack,
    )
    # T4 + Hono = no T2/web template fires. Tier-app_class gate fails (T4 not
    # in T1/T2/T3). Hono not a browser framework. So no package.json.
    assert not (tmp_path / "package.json").exists()


def test_non_react_stack_does_not_write_vite_config(tmp_path: Path) -> None:
    """Hono / non-React stacks shouldn't be saddled with React-specific
    test scaffolding."""
    hono_stack = LockedStack(
        tier="T2",
        app_class="web",
        language="TypeScript",
        primary_framework="Hono",
        package_manager="npm",
        test_cmd="npx vitest run",
        run_cmd="npm start",
        key_libraries=["zod"],
    )
    bootstrap_workspace_layout(
        tmp_path,
        modules=["api"],
        tier="T2",
        app_class="web",
        project_name="api",
        locked_stack=hono_stack,
    )
    assert not (tmp_path / "vite.config.ts").exists()
    assert not (tmp_path / "setupTests.ts").exists()


def test_hono_primary_framework_installs_hono_package(tmp_path: Path) -> None:
    stack = LockedStack(
        tier="T2",
        app_class="web",
        language="TypeScript",
        primary_framework="Hono",
        package_manager="npm",
        test_cmd="npx vitest run",
        run_cmd="npm start",
        key_libraries=["zod"],
    )
    bootstrap_workspace_layout(
        tmp_path,
        modules=["api"],
        tier="T2",
        app_class="web",
        project_name="api",
        locked_stack=stack,
    )
    deps = json.loads((tmp_path / "package.json").read_text(encoding="utf-8")).get(
        "dependencies", {}
    )
    assert "hono" in deps
    assert "zod" in deps
    # React should NOT leak in for a Hono backend
    assert "react" not in deps


def test_idb_browser_persistence_lib_is_registered(tmp_path: Path) -> None:
    """Item 47 — idb (IndexedDB wrapper) must land in dependencies when
    StackAnalyst autonomously picks it. Proof-point v4 surfaced this: the
    BaaS-drift fix widened the analyst's range to include idb/dexie/
    localforage as browser-persistence picks, but the registry was sized
    to v2/v3 (sql.js only) and silently dropped idb."""
    stack = LockedStack(
        tier="T2",
        app_class="web",
        language="TypeScript",
        primary_framework="React + Vite",
        package_manager="npm",
        test_cmd="npx vitest run",
        run_cmd="npm run dev",
        key_libraries=["idb", "zod"],
    )
    bootstrap_workspace_layout(
        tmp_path,
        modules=["types", "storage", "ui"],
        tier="T2",
        app_class="web",
        project_name="todo-v4",
        locked_stack=stack,
    )
    pkg = json.loads((tmp_path / "package.json").read_text(encoding="utf-8"))
    deps = pkg.get("dependencies", {})
    assert "idb" in deps, "idb must be in dependencies — proof-point v4 regression"
    assert "react" in deps and "vite" in pkg.get("devDependencies", {}), (
        "framework deps must not regress when adding browser-persistence libs"
    )


def test_idb_auto_pulls_fake_indexeddb_test_peer(tmp_path: Path) -> None:
    """Item 47b — bootstrap must auto-add fake-indexeddb when idb is in
    key_libraries because jsdom (used by vitest) doesn't provide a real
    IndexedDB. Proof-point v4 T-002 hit this: Worker correctly imported
    `fake-indexeddb/auto` to make tests run, but the package wasn't
    installed. Mirrors react → @vitejs/plugin-react auto-pull pattern."""
    stack = LockedStack(
        tier="T2",
        app_class="web",
        language="TypeScript",
        primary_framework="React + Vite",
        package_manager="npm",
        test_cmd="npx vitest run",
        run_cmd="npm run dev",
        key_libraries=["idb", "zod"],
    )
    bootstrap_workspace_layout(
        tmp_path,
        modules=["storage"],
        tier="T2",
        app_class="web",
        project_name="todo-idb",
        locked_stack=stack,
    )
    pkg = json.loads((tmp_path / "package.json").read_text(encoding="utf-8"))
    dev_deps = pkg.get("devDependencies", {})
    assert "fake-indexeddb" in dev_deps, (
        "idb in key_libraries must auto-pull fake-indexeddb (jsdom shim)"
    )


def test_dexie_and_localforage_also_pull_fake_indexeddb(tmp_path: Path) -> None:
    """Item 47b — dexie and localforage are both IndexedDB-backed; both
    should trigger the fake-indexeddb auto-pull rule."""
    for lib in ("dexie", "localforage"):
        stack = LockedStack(
            tier="T2",
            app_class="web",
            language="TypeScript",
            primary_framework="React + Vite",
            package_manager="npm",
            test_cmd="npx vitest run",
            run_cmd="npm run dev",
            key_libraries=[lib],
        )
        target = tmp_path / f"peer-{lib}"
        target.mkdir()
        bootstrap_workspace_layout(
            target,
            modules=["storage"],
            tier="T2",
            app_class="web",
            project_name=f"todo-{lib}",
            locked_stack=stack,
        )
        dev_deps = json.loads(
            (target / "package.json").read_text(encoding="utf-8")
        ).get("devDependencies", {})
        assert "fake-indexeddb" in dev_deps, (
            f"{lib} in key_libraries must auto-pull fake-indexeddb shim"
        )


def test_no_browser_persistence_means_no_fake_indexeddb(tmp_path: Path) -> None:
    """Item 47b counter-example: stacks WITHOUT browser persistence must
    NOT get fake-indexeddb installed — it's only relevant when the
    runtime is going to talk to IndexedDB."""
    stack = LockedStack(
        tier="T2",
        app_class="web",
        language="TypeScript",
        primary_framework="React + Vite",
        package_manager="npm",
        test_cmd="npx vitest run",
        run_cmd="npm run dev",
        key_libraries=["zod"],  # No idb/dexie/localforage
    )
    bootstrap_workspace_layout(
        tmp_path,
        modules=["ui"],
        tier="T2",
        app_class="web",
        project_name="todo-no-idb",
        locked_stack=stack,
    )
    dev_deps = json.loads(
        (tmp_path / "package.json").read_text(encoding="utf-8")
    ).get("devDependencies", {})
    assert "fake-indexeddb" not in dev_deps, (
        "fake-indexeddb must only auto-install when an IndexedDB lib is present"
    )


def test_dexie_and_localforage_also_registered(tmp_path: Path) -> None:
    """Item 47 — dexie and localforage are the other two common browser
    persistence libs the analyst might pick; all three should resolve."""
    for lib in ("dexie", "localforage"):
        stack = LockedStack(
            tier="T2",
            app_class="web",
            language="TypeScript",
            primary_framework="React + Vite",
            package_manager="npm",
            test_cmd="npx vitest run",
            run_cmd="npm run dev",
            key_libraries=[lib],
        )
        target = tmp_path / lib
        target.mkdir()
        bootstrap_workspace_layout(
            target,
            modules=["ui"],
            tier="T2",
            app_class="web",
            project_name=f"todo-{lib}",
            locked_stack=stack,
        )
        deps = json.loads((target / "package.json").read_text(encoding="utf-8")).get(
            "dependencies", {}
        )
        assert lib in deps, f"{lib} must be in dependencies"


def test_unknown_key_library_warns_and_is_skipped(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    """Item 47 — when a key_library isn't in `_NPM_DEP_REGISTRY`, the
    bootstrap must emit a stderr warning so the operator sees the silent
    drop. Pre-fix this branch silently `continue`d, producing a broken
    workspace where `npm install` succeeded but the missing lib only
    surfaced at first test run as `Cannot find module 'X'`."""
    stack = LockedStack(
        tier="T2",
        app_class="web",
        language="TypeScript",
        primary_framework="React + Vite",
        package_manager="npm",
        test_cmd="npx vitest run",
        run_cmd="npm run dev",
        key_libraries=["zod", "some-niche-lib-not-registered"],
    )
    bootstrap_workspace_layout(
        tmp_path,
        modules=["ui"],
        tier="T2",
        app_class="web",
        project_name="todo-niche",
        locked_stack=stack,
    )
    deps = json.loads((tmp_path / "package.json").read_text(encoding="utf-8")).get(
        "dependencies", {}
    )
    assert "zod" in deps, "registered libs must still flow through"
    assert "some-niche-lib-not-registered" not in deps

    captured = capsys.readouterr()
    assert "WARNING" in captured.err
    assert "key_library" in captured.err
    assert "some-niche-lib-not-registered" in captured.err


def test_unknown_framework_warns_and_falls_back_to_key_libraries_only(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    """Unknown primary_framework string emits a one-line stderr warning so
    the operator sees the gap (rather than silently producing a broken
    workspace, which was the proof-point's failure mode)."""
    stack = LockedStack(
        tier="T2",
        app_class="web",
        language="TypeScript",
        primary_framework="SomeBrandNewFrameworkWeNeverHeardOf",
        package_manager="npm",
        test_cmd="npx vitest run",
        run_cmd="npm start",
        key_libraries=["zod"],
    )
    bootstrap_workspace_layout(
        tmp_path,
        modules=["api"],
        tier="T2",
        app_class="web",
        project_name="api",
        locked_stack=stack,
    )
    deps = json.loads((tmp_path / "package.json").read_text(encoding="utf-8")).get(
        "dependencies", {}
    )
    assert "zod" in deps, "Unknown framework must NOT drop key_libraries"
    assert "react" not in deps and "vite" not in deps

    captured = capsys.readouterr()
    assert "WARNING" in captured.err
    assert "primary_framework" in captured.err
    assert "SomeBrandNewFramework" in captured.err


def test_framework_to_packages_recognizes_common_variants() -> None:
    """Whitespace/case/punctuation variants of the same framework name
    resolve to the same package list. Architect/StackAnalyst output is not
    perfectly canonical — be tolerant about what we accept.

    Item 41' added test-tier deps to the React variants; assert the core
    React+Vite quartet is present without pinning the exact length (so
    future additions don't break this test)."""
    react_vite_a = _framework_to_packages("React + Vite")
    react_vite_b = _framework_to_packages("react+vite")
    react_vite_c = _framework_to_packages("Vite + React")
    assert react_vite_a == react_vite_b == react_vite_c, "variants must align"
    for required in ("react", "react-dom", "vite", "@vitejs/plugin-react"):
        assert required in react_vite_a, f"{required} missing from React+Vite set"
    # 41' additions
    for required in (
        "@testing-library/react",
        "@testing-library/jest-dom",
        "jsdom",
    ):
        assert required in react_vite_a, f"{required} missing (Item 41')"

    # Next.js variants
    next_a = _framework_to_packages("Next.js")
    next_b = _framework_to_packages("nextjs")
    assert next_a == next_b
    for required in ("next", "react", "react-dom"):
        assert required in next_a

    # Python frameworks return [] but do NOT warn
    assert _framework_to_packages("FastAPI") == []
    assert _framework_to_packages("Django") == []

    # Empty/None
    assert _framework_to_packages(None) == []
    assert _framework_to_packages("") == []


# ---------------------------------------------------------------------
# T0/web — single-file CLI tier (C-1 ship)
# ---------------------------------------------------------------------


def _t0_python_stack(test_cmd: str = "pytest") -> LockedStack:
    return LockedStack(
        tier="T0",
        app_class="web",
        language="Python",
        primary_framework="Typer",
        package_manager="pip",
        test_cmd=test_cmd,
        run_cmd="python -m app",
        key_libraries=["typer", "pydantic"],
    )


def _t0_go_stack(test_cmd: str = "go test ./...") -> LockedStack:
    return LockedStack(
        tier="T0",
        app_class="web",
        language="Go",
        primary_framework="Cobra",
        package_manager="go modules",
        test_cmd=test_cmd,
        run_cmd="./bin/app",
        key_libraries=["cobra"],
    )


def test_t0_web_python_writes_pyproject_and_python_gitignore(tmp_path: Path) -> None:
    bootstrap_workspace_layout(
        tmp_path,
        modules=["cli"],
        tier="T0",
        app_class="web",
        project_name="todo-cli",
        locked_stack=_t0_python_stack(),
    )
    pyproject = tmp_path / "pyproject.toml"
    assert pyproject.exists(), "T0/web Python should write pyproject.toml"
    body = pyproject.read_text(encoding="utf-8")
    assert 'name = "todo-cli"' in body
    assert "pytest" in body
    assert 'requires-python = ">=3.11"' in body

    gitignore = (tmp_path / ".gitignore").read_text(encoding="utf-8")
    assert "__pycache__/" in gitignore
    assert ".venv/" in gitignore
    # T0 must NOT pull in the T2 web template
    assert "node_modules/" not in gitignore


def test_t0_web_python_does_not_write_t2_artifacts(tmp_path: Path) -> None:
    """Regression: T0/web Python landed in the T2 branch in an earlier
    sketch (because of overlapping `tier in ("T1","T2","T3")` plus a
    naive fallback). Pin that none of the TypeScript-shaped files leak
    in for a Python T0 project."""
    bootstrap_workspace_layout(
        tmp_path,
        modules=["cli"],
        tier="T0",
        app_class="web",
        project_name="x",
        locked_stack=_t0_python_stack(),
    )
    assert not (tmp_path / "package.json").exists()
    assert not (tmp_path / "tsconfig.json").exists()
    assert not (tmp_path / "vite.config.ts").exists()


def test_t0_web_go_writes_go_mod_and_go_gitignore(tmp_path: Path) -> None:
    bootstrap_workspace_layout(
        tmp_path,
        modules=["cmd"],
        tier="T0",
        app_class="web",
        project_name="todo cli",
        locked_stack=_t0_go_stack(),
    )
    gomod = tmp_path / "go.mod"
    assert gomod.exists()
    body = gomod.read_text(encoding="utf-8")
    assert "module example.com/todo-cli" in body  # name slugified
    assert "go 1.22" in body

    gitignore = (tmp_path / ".gitignore").read_text(encoding="utf-8")
    assert "bin/" in gitignore
    assert "vendor/" in gitignore
    assert "node_modules/" not in gitignore


def test_t0_web_no_locked_stack_no_rfc_skips_language_files(tmp_path: Path) -> None:
    """When neither LockedStack nor RFC signals language, T0/web
    degrades to the universal layout (gitignore + modules only). We do
    NOT guess Python or Go — guessing is what pre-LockedStack drift
    was. Worker writes feature code in the module folder; the project
    can be promoted to LockedStack later via M2 dialog."""
    bootstrap_workspace_layout(
        tmp_path,
        modules=["cmd"],
        tier="T0",
        app_class="web",
        project_name="x",
        locked_stack=None,
    )
    assert not (tmp_path / "pyproject.toml").exists()
    assert not (tmp_path / "go.mod").exists()
    gitignore = (tmp_path / ".gitignore").read_text(encoding="utf-8")
    assert "__pycache__/" not in gitignore
    assert "bin/" not in gitignore


def test_t0_web_rfc_scan_fallback_resolves_python(tmp_path: Path) -> None:
    """Pre-M2 path: no LockedStack but the RFC mentions Python/pytest.
    Bootstrap must still pick up the signal and write pyproject.toml."""
    (tmp_path / "RFC.md").write_text(
        "## 4. Tech Stack\n\n"
        "Language: Python 3.11. Testing via pytest.\n",
        encoding="utf-8",
    )
    bootstrap_workspace_layout(
        tmp_path,
        modules=["cli"],
        tier="T0",
        app_class="web",
        project_name="rfc-python",
        locked_stack=None,
    )
    assert (tmp_path / "pyproject.toml").exists()


def test_t0_web_python_writes_ai_factory_env_with_pytest(tmp_path: Path) -> None:
    """LockedStack.test_cmd is the source of truth for `.ai-factory.env`.
    For a T0 Python stack the locked test_cmd is `pytest`."""
    bootstrap_workspace_layout(
        tmp_path,
        modules=["cli"],
        tier="T0",
        app_class="web",
        project_name="todo-cli",
        locked_stack=_t0_python_stack(),
    )
    ai_env = (tmp_path / ".ai-factory.env").read_text(encoding="utf-8")
    assert 'AI_FACTORY_TEST_CMD="pytest"' in ai_env


def test_rfc_scan_does_not_match_rust_inside_trust(tmp_path: Path) -> None:
    """Regression — surfaced by the C-4 T0/web Python proof-point.
    RFC contained the phrase "internal calls trust types", and the
    `_infer_test_cmd_from_rfc` substring match latched onto `rust`
    inside `trust`, writing `AI_FACTORY_TEST_CMD="cargo test"` to a
    Python project. Word-boundary regex prevents this class entirely."""
    (tmp_path / "RFC.md").write_text(
        "## 4. Tech Stack\n\n"
        "Language: Python. The error handler validates at boundaries; "
        "internal calls trust types.\n",
        encoding="utf-8",
    )
    bootstrap_workspace_layout(
        tmp_path,
        modules=["cli"],
        tier="T0",
        app_class="web",
        project_name="x",
        locked_stack=None,
    )
    ai_env = (tmp_path / ".ai-factory.env").read_text(encoding="utf-8")
    assert "cargo test" not in ai_env, (
        "RFC scan should not match 'rust' inside 'trust' (regression)"
    )
    assert "pytest" in ai_env


def test_rfc_scan_does_not_match_dart_inside_other_words(tmp_path: Path) -> None:
    """Same class as the rust-in-trust regression: 'dart' inside
    'depart', 'regard', 'standard' etc. must not trigger Flutter."""
    (tmp_path / "RFC.md").write_text(
        "## 4. Tech Stack\n\n"
        "Language: Python. The CLI accepts standard input; arguments "
        "depart from convention. Logs follow no particular regard.\n",
        encoding="utf-8",
    )
    bootstrap_workspace_layout(
        tmp_path,
        modules=["cli"],
        tier="T0",
        app_class="web",
        project_name="x",
        locked_stack=None,
    )
    ai_env = (tmp_path / ".ai-factory.env").read_text(encoding="utf-8")
    assert "flutter test" not in ai_env
    assert "pytest" in ai_env


def test_rfc_scan_still_matches_real_language_tokens(tmp_path: Path) -> None:
    """Word boundaries must not break legitimate matches. The fix
    should accept `Rust`, `Cargo`, `Dart` when they appear as standalone
    words (Architect §4 vocabulary), only rejecting collisions inside
    longer words."""
    (tmp_path / "RFC.md").write_text(
        "## 4. Tech Stack\n\n"
        "Language: Rust. Build: cargo build.\n",
        encoding="utf-8",
    )
    bootstrap_workspace_layout(
        tmp_path,
        modules=["cli"],
        tier="T0",
        app_class="web",
        project_name="x",
        locked_stack=None,
    )
    ai_env = (tmp_path / ".ai-factory.env").read_text(encoding="utf-8")
    assert "cargo test" in ai_env


def test_t0_web_python_second_call_is_noop(tmp_path: Path) -> None:
    """Idempotency must hold for T0 too — re-bootstrapping a workspace
    after a manual edit should not clobber pyproject.toml."""
    stack = _t0_python_stack()
    first = bootstrap_workspace_layout(
        tmp_path,
        modules=["cli"],
        tier="T0",
        app_class="web",
        project_name="x",
        locked_stack=stack,
    )
    second = bootstrap_workspace_layout(
        tmp_path,
        modules=["cli"],
        tier="T0",
        app_class="web",
        project_name="x",
        locked_stack=stack,
    )
    assert first  # first run produced something
    assert second == []  # second is no-op
