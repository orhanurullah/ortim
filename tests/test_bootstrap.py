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

from runtime.architecture import bootstrap_workspace_layout


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
