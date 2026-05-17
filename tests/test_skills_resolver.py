# SPDX-License-Identifier: FSL-1.1-Apache-2.0
# Copyright (c) 2026 ortim.dev
"""Skill resolver contract tests.

Five guarantees:
  - tier+language+keyword filters AND-compose (all populated groups
    must match)
  - more-specific skills outrank universal ones when budget is tight
  - locked_stack=None drops language-specific skills entirely
  - max_skills cap is honored even if more would fit char-wise
  - char_budget cap is honored even if more would fit count-wise
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from ortim.architecture import LockedStack  # noqa: E402
from ortim.orchestrator import TaskSpec  # noqa: E402
from ortim.skills.resolver import (  # noqa: E402
    format_skills_block,
    resolve_for_task,
)
from ortim.skills.schema import Skill, SkillTriggers  # noqa: E402


def _skill(
    name: str,
    body: str = "body",
    *,
    audience: list[str] | None = None,
    tier: list[str] | None = None,
    app_class: list[str] | None = None,
    language: list[str] | None = None,
    keywords: list[str] | None = None,
) -> Skill:
    return Skill(
        name=name,
        description=f"desc {name}",
        audience=audience or ["worker", "reviewer"],
        triggers=SkillTriggers(
            tier=tier or [],
            app_class=app_class or [],
            language=language or [],
            keywords=keywords or [],
        ),
        body=body,
    )


def _task(description: str = "do something with imports") -> TaskSpec:
    return TaskSpec(
        id="T-001",
        title="impl",
        description=description,
        module_scope="x",
        rfc_section="§7",
        acceptance_criteria=["does X"],
        estimated_tokens=1000,
    )


def _ts_stack() -> LockedStack:
    return LockedStack(
        tier="T1",
        app_class="web",
        language="TypeScript",
        primary_framework="Vite + React",
        package_manager="npm",
        test_cmd="npx vitest run",
        run_cmd="npm run dev",
    )


def test_resolver_and_combines_trigger_groups() -> None:
    """A skill with both `language=TypeScript` and `keywords=import` requires
    BOTH to match — TS+description-without-import drops it; TS+description-with-import
    keeps it."""
    s = _skill("ts-imports", language=["TypeScript"], keywords=["import"])

    # description does NOT contain 'import' → skill should drop
    out = resolve_for_task(
        skills=[s],
        task=_task("do something else"),
        tier="T1",
        app_class="web",
        locked_stack=_ts_stack(),
        audience="worker",
    )
    assert out == []

    # description contains 'import' → skill should resolve
    out = resolve_for_task(
        skills=[s],
        task=_task("clean up imports"),
        tier="T1",
        app_class="web",
        locked_stack=_ts_stack(),
        audience="worker",
    )
    assert [s.name for s in out] == ["ts-imports"]


def test_resolver_specificity_wins_over_universal() -> None:
    """Specific-language skill sorts ahead of a universal one — same audience,
    same eventual fit, but specificity decides order."""
    specific = _skill("specific", language=["TypeScript"])
    universal = _skill("universal")

    out = resolve_for_task(
        skills=[universal, specific],
        task=_task(),
        tier="T1",
        app_class="web",
        locked_stack=_ts_stack(),
        audience="worker",
    )
    assert [s.name for s in out] == ["specific", "universal"]


def test_resolver_locked_stack_none_drops_language_specific() -> None:
    """Without a LockedStack, the resolver has no language signal — skills
    that demand a specific language are filtered out."""
    specific = _skill("ts-only", language=["TypeScript"])
    universal = _skill("universal-skill")

    out = resolve_for_task(
        skills=[specific, universal],
        task=_task(),
        tier="T1",
        app_class="web",
        locked_stack=None,
        audience="worker",
    )
    assert [s.name for s in out] == ["universal-skill"]


def test_resolver_max_skills_cap_is_enforced() -> None:
    """max_skills=2 → only the top-2 specificity ones resolve, even if
    six universal skills would otherwise all fit."""
    skills = [_skill(f"u{i}") for i in range(6)]
    out = resolve_for_task(
        skills=skills,
        task=_task(),
        tier="T1",
        app_class="web",
        locked_stack=_ts_stack(),
        audience="worker",
        max_skills=2,
    )
    assert len(out) == 2


def test_resolver_char_budget_cap_is_enforced() -> None:
    """char_budget=100 with three 60-char-body skills → only one fits."""
    big_body = "x" * 60
    skills = [
        _skill(f"big{i}", body=big_body, language=["TypeScript"])
        for i in range(3)
    ]
    out = resolve_for_task(
        skills=skills,
        task=_task(),
        tier="T1",
        app_class="web",
        locked_stack=_ts_stack(),
        audience="worker",
        max_skills=10,
        char_budget=100,
    )
    assert len(out) == 1


def test_resolver_audience_filter() -> None:
    """Worker-only skill must not appear in a reviewer call."""
    worker_only = _skill("w-only", audience=["worker"], language=["TypeScript"])
    out = resolve_for_task(
        skills=[worker_only],
        task=_task(),
        tier="T1",
        app_class="web",
        locked_stack=_ts_stack(),
        audience="reviewer",
    )
    assert out == []


def test_format_skills_block_empty_returns_empty_string() -> None:
    assert format_skills_block([], audience="worker") == ""


def test_format_skills_block_worker_header() -> None:
    s = _skill("x", body="rule body")
    rendered = format_skills_block([s], audience="worker")
    assert "## Active Skills" in rendered
    assert "HARD rules" in rendered
    assert "rule body" in rendered
    assert "### x" in rendered


def test_format_skills_block_reviewer_header() -> None:
    s = _skill("x", body="rule body")
    rendered = format_skills_block([s], audience="reviewer")
    assert "Acceptance criteria are interpreted" in rendered
    assert "rule body" in rendered


# ---------------------------------------------------------------------------
# Item 39a — SQL-mock skill. Verifies the on-disk skill file loads and that
# a T-002-shaped task (service that uses db-adapter for persistence) actually
# resolves it. Catches regressions where someone renames a trigger keyword
# or moves the file out of the loader's glob.
# ---------------------------------------------------------------------------


def test_react_di_skill_resolves_for_app_wiring_task() -> None:
    """Item 44 — `skills/react/dependency-injection.md` must fire on App /
    wiring tasks where Worker historically inlined `new ServiceName()`
    inside event handlers (proof-point v2 T-007). Triggers on react
    language + `App`/`wire`/`integrate`/`adapter`/`service`/`context`."""
    from ortim.skills import load_all_skills

    skills = load_all_skills(REPO_ROOT)
    names = {s.name for s in skills}
    assert "react-dependency-injection" in names, (
        "On-disk skill file failed to load — check skills/react/"
        "dependency-injection.md frontmatter."
    )

    # T-007-shape task from proof-point v2
    task = TaskSpec(
        id="T-007",
        title="Wire up App component with TaskService and persistence adapter",
        description=(
            "Integrate the TaskService and SqljsAdapter into the App "
            "component. Pass them to the React component tree. Add "
            "WebAssembly support detection and fallback message."
        ),
        module_scope="task-ui",
        rfc_section="§7",
        acceptance_criteria=["App renders TaskList"],
        estimated_tokens=1500,
    )
    out = resolve_for_task(
        skills=skills,
        task=task,
        tier="T2",
        app_class="web",
        locked_stack=_ts_stack(),
        audience="worker",
    )
    resolved = {s.name for s in out}
    assert "react-dependency-injection" in resolved, (
        f"Expected react-dependency-injection to fire on App wiring task, "
        f"got {resolved}"
    )


def test_sql_mock_skill_resolves_for_service_task_using_db_adapter() -> None:
    from ortim.skills import load_all_skills

    skills = load_all_skills(REPO_ROOT)
    names = {s.name for s in skills}
    assert "typescript-sql-mock-patterns" in names, (
        "On-disk skill file failed to load — check skills/typescript/"
        "sql-mock-patterns.md frontmatter syntax."
    )

    task = TaskSpec(
        id="T-002",
        title="Implement task-service: business logic with Zod validation",
        description=(
            "Create the task-service module with createTask, getAllTasks, "
            "completeTask, deleteTask functions. Use db-adapter for "
            "persistence."
        ),
        module_scope="task-service",
        rfc_section="§7",
        acceptance_criteria=["createTask('Buy milk') returns a Task"],
        estimated_tokens=1500,
    )

    out = resolve_for_task(
        skills=skills,
        task=task,
        tier="T2",
        app_class="web",
        locked_stack=_ts_stack(),
        audience="worker",
    )
    resolved_names = {s.name for s in out}
    assert "typescript-sql-mock-patterns" in resolved_names, (
        f"Expected SQL-mock skill to fire for db-adapter persistence task, "
        f"got {resolved_names}"
    )


def test_ui_text_matching_skill_resolves_for_status_text_task() -> None:
    """UI-text-match fix: `skills/react/ui-test-text-matching.md` must
    fire on UI tasks where Worker historically decorated text nodes with
    emoji/icon prefixes while tests asserted bare strings (proof-point v3
    T-006 — `⚠️ You have over 1000 tasks` vs `getByText('You have over
    1000 tasks')`). Triggers on react + ui keywords like warning, banner,
    notification, empty state.
    """
    from ortim.skills import load_all_skills

    skills = load_all_skills(REPO_ROOT)
    names = {s.name for s in skills}
    assert "react-ui-test-text-matching" in names, (
        "On-disk skill file failed to load — check "
        "skills/react/ui-test-text-matching.md frontmatter."
    )

    # T-006-shape task from proof-point v3
    task = TaskSpec(
        id="T-006",
        title="Add over-1000-tasks warning banner",
        description=(
            "When task count exceeds 1000, render a warning message "
            "suggesting the user archive completed tasks. Add a test that "
            "asserts the message appears."
        ),
        module_scope="task-ui",
        rfc_section="§7",
        acceptance_criteria=[
            "When task count > 1000, banner with text 'You have over 1000 "
            "tasks. Consider archiving.' appears.",
        ],
        estimated_tokens=1500,
    )

    out = resolve_for_task(
        skills=skills,
        task=task,
        tier="T2",
        app_class="web",
        locked_stack=_ts_stack(),
        audience="worker",
    )
    resolved = {s.name for s in out}
    assert "react-ui-test-text-matching" in resolved, (
        f"Expected react-ui-text-matching to fire on warning-banner task, "
        f"got {resolved}"
    )
