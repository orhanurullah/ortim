# SPDX-License-Identifier: FSL-1.1-Apache-2.0
# Copyright (c) 2026 ortim.dev
"""Community skills resolver tests (Roadmap 2.4).

Pins on-disk loading + resolver fire/non-fire for the two skills
introduced alongside the skill authoring guide:
  - python-fastapi-async-patterns
  - deploy-env-secrets
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from ortim.architecture import LockedStack  # noqa: E402
from ortim.orchestrator import TaskSpec  # noqa: E402
from ortim.skills import load_all_skills  # noqa: E402
from ortim.skills.resolver import resolve_for_task  # noqa: E402


def _stack(language: str, *, tier: str = "T2", framework: str = "FastAPI") -> LockedStack:
    return LockedStack(
        tier=tier,
        app_class="web",
        language=language,
        primary_framework=framework,
        package_manager="pip" if language == "Python" else "npm",
        test_cmd="pytest" if language == "Python" else "npx vitest run",
        run_cmd="uvicorn app.main:app" if language == "Python" else "npm start",
    )


def _task(
    description: str,
    *,
    title: str = "Implement",
    module_scope: str = "core",
) -> TaskSpec:
    return TaskSpec(
        id="T-050",
        title=title,
        description=description,
        module_scope=module_scope,
        rfc_section="§7",
        acceptance_criteria=["does the thing"],
        estimated_tokens=1200,
    )


# ---------------------------------------------------------------------------
# python-fastapi-async-patterns
# ---------------------------------------------------------------------------


def test_fastapi_skill_loads_from_disk() -> None:
    skills = load_all_skills(REPO_ROOT)
    assert "python-fastapi-async-patterns" in {s.name for s in skills}


def test_fastapi_skill_resolves_for_python_endpoint_task() -> None:
    skills = load_all_skills(REPO_ROOT)
    out = resolve_for_task(
        skills=skills,
        task=_task(
            "Add a FastAPI endpoint /users/{uid} that returns user data "
            "from the database",
            module_scope="users",
        ),
        tier="T2",
        app_class="web",
        locked_stack=_stack("Python"),
        audience="worker",
    )
    assert "python-fastapi-async-patterns" in {s.name for s in out}


def test_fastapi_skill_does_not_resolve_for_typescript_stack() -> None:
    """Language filter must hold — TS project doesn't get the Python skill
    even with `endpoint` and `route` in the description."""
    skills = load_all_skills(REPO_ROOT)
    out = resolve_for_task(
        skills=skills,
        task=_task("Add an Express route /users/:uid for the API endpoint"),
        tier="T2",
        app_class="web",
        locked_stack=_stack("TypeScript", framework="Express"),
        audience="worker",
    )
    assert "python-fastapi-async-patterns" not in {s.name for s in out}


def test_fastapi_skill_does_not_resolve_for_python_data_pipeline_task() -> None:
    """Without any FastAPI/endpoint signal in the brief, the skill stays
    out. Catches the over-broad-keyword failure mode."""
    skills = load_all_skills(REPO_ROOT)
    out = resolve_for_task(
        skills=skills,
        task=_task(
            "Implement a CSV parser that normalises customer records",
            module_scope="etl",
        ),
        tier="T2",
        app_class="web",
        locked_stack=_stack("Python", framework="pandas"),
        audience="worker",
    )
    assert "python-fastapi-async-patterns" not in {s.name for s in out}


def test_fastapi_skill_is_worker_only_not_reviewer() -> None:
    skills = load_all_skills(REPO_ROOT)
    out = resolve_for_task(
        skills=skills,
        task=_task("Add a FastAPI async endpoint /users for the API"),
        tier="T2",
        app_class="web",
        locked_stack=_stack("Python"),
        audience="reviewer",
    )
    assert "python-fastapi-async-patterns" not in {s.name for s in out}


# ---------------------------------------------------------------------------
# deploy-env-secrets
# ---------------------------------------------------------------------------


def test_env_secrets_skill_loads_from_disk() -> None:
    skills = load_all_skills(REPO_ROOT)
    assert "deploy-env-secrets" in {s.name for s in skills}


def test_env_secrets_skill_resolves_for_config_task_any_language() -> None:
    """No language filter — env/secrets pattern applies to every stack."""
    skills = load_all_skills(REPO_ROOT)
    for language in ("Python", "TypeScript", "Go"):
        out = resolve_for_task(
            skills=skills,
            task=_task(
                "Load DATABASE_URL and JWT_SECRET from environment variables "
                "at startup, validate they exist",
                module_scope="config",
            ),
            tier="T2",
            app_class="web",
            locked_stack=_stack(language, framework="generic"),
            audience="worker",
        )
        resolved = {s.name for s in out}
        assert "deploy-env-secrets" in resolved, (
            f"Expected deploy-env-secrets to fire for {language}, "
            f"got {resolved}"
        )


def test_env_secrets_skill_is_available_to_reviewer_audience() -> None:
    """Contract test: env-secrets carries audience=[worker, reviewer] so
    the Reviewer also gets the rule (e.g. flag a literal-looking secret
    in the diff). `applies_to` is the right level for this — resolver
    budget can drop a universal skill on a heavily-TS task by design."""
    skills = load_all_skills(REPO_ROOT)
    env_secrets = next(s for s in skills if s.name == "deploy-env-secrets")
    assert env_secrets.applies_to(
        audience="reviewer",
        tier="T2",
        app_class="web",
        language="TypeScript",
        description=(
            "Add Stripe API key handling; load token from environment "
            "at startup"
        ),
    )


def test_env_secrets_skill_does_not_resolve_for_pure_ui_task() -> None:
    """A task that doesn't mention env / config / secrets shouldn't pull
    in the skill."""
    skills = load_all_skills(REPO_ROOT)
    out = resolve_for_task(
        skills=skills,
        task=_task(
            "Render the user-profile page with name, email, avatar",
            module_scope="user-ui",
        ),
        tier="T2",
        app_class="web",
        locked_stack=_stack("TypeScript"),
        audience="worker",
    )
    assert "deploy-env-secrets" not in {s.name for s in out}
