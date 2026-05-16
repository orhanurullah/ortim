# SPDX-License-Identifier: FSL-1.1-Apache-2.0
# Copyright (c) 2026 ortim.dev
"""Docker-deploy skill resolver tests (Roadmap 2.1).

Two layers:
  - SkillTriggers.keywords_blocklist contract (schema-level)
  - Three on-disk skill files (deploy/dockerfile-node, dockerfile-python,
    docker-compose-microservices) load and resolve under the right
    (tier, app_class, language, keyword, blocklist) combinations.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from runtime.architecture import LockedStack  # noqa: E402
from runtime.orchestrator import TaskSpec  # noqa: E402
from runtime.skills import load_all_skills  # noqa: E402
from runtime.skills.resolver import resolve_for_task  # noqa: E402
from runtime.skills.schema import Skill, SkillTriggers  # noqa: E402


def _stack(language: str = "TypeScript") -> LockedStack:
    return LockedStack(
        tier="T4",
        app_class="web",
        language=language,
        primary_framework="Express",
        package_manager="npm",
        test_cmd="npx vitest run",
        run_cmd="npm start",
    )


def _task(
    description: str,
    *,
    title: str = "Deploy to production",
    module_scope: str = "deploy",
) -> TaskSpec:
    return TaskSpec(
        id="T-099",
        title=title,
        description=description,
        module_scope=module_scope,
        rfc_section="§7",
        acceptance_criteria=["Dockerfile exists at repo root"],
        estimated_tokens=1200,
    )


# ---------------------------------------------------------------------------
# Schema-level: keywords_blocklist contract
# ---------------------------------------------------------------------------


def test_keywords_blocklist_rejects_skill_when_phrase_present() -> None:
    """Even with every positive trigger matching, a blocklist phrase in the
    haystack pulls the skill out."""
    s = Skill(
        name="docker",
        description="d",
        body="b",
        triggers=SkillTriggers(
            keywords=["docker"],
            keywords_blocklist=["no docker"],
        ),
    )
    assert s.applies_to(
        audience="worker",
        tier="T4",
        app_class="web",
        language="TypeScript",
        description="please add docker for production",
    )
    assert not s.applies_to(
        audience="worker",
        tier="T4",
        app_class="web",
        language="TypeScript",
        description="please add docker but no docker overhead for dev",
    )


def test_keywords_blocklist_case_insensitive() -> None:
    s = Skill(
        name="docker",
        description="d",
        body="b",
        triggers=SkillTriggers(
            keywords=["deploy"],
            keywords_blocklist=["Lokal Kalsın"],
        ),
    )
    assert not s.applies_to(
        audience="worker",
        tier="T4",
        app_class="web",
        language="TypeScript",
        description="deploy yapalım ama lokal kalsın",
    )


def test_keywords_blocklist_empty_means_no_filter() -> None:
    """Backward-compat: existing skills without a blocklist behave the
    same as before."""
    s = Skill(
        name="x",
        description="d",
        body="b",
        triggers=SkillTriggers(keywords=["deploy"]),
    )
    assert s.applies_to(
        audience="worker",
        tier="T4",
        app_class="web",
        language="TypeScript",
        description="deploy this no docker thing",
    )


def test_is_universal_counts_blocklist_as_restriction() -> None:
    """A skill that only has a blocklist still restricts where it
    applies — is_universal must report False."""
    blocklist_only = SkillTriggers(keywords_blocklist=["no docker"])
    assert not blocklist_only.is_universal()

    truly_universal = SkillTriggers()
    assert truly_universal.is_universal()


# ---------------------------------------------------------------------------
# On-disk skill files — three Dockerfile skills load + resolve
# ---------------------------------------------------------------------------


def test_dockerfile_node_skill_loads_from_disk() -> None:
    skills = load_all_skills(REPO_ROOT)
    names = {s.name for s in skills}
    assert "deploy-dockerfile-node" in names
    assert "deploy-dockerfile-python" in names
    assert "deploy-docker-compose-microservices" in names


def test_dockerfile_node_resolves_for_t4_web_typescript_deploy_brief() -> None:
    skills = load_all_skills(REPO_ROOT)
    out = resolve_for_task(
        skills=skills,
        task=_task("Add Dockerfile for production deploy of the API service"),
        tier="T4",
        app_class="web",
        locked_stack=_stack("TypeScript"),
        audience="worker",
    )
    assert "deploy-dockerfile-node" in {s.name for s in out}


def test_dockerfile_python_resolves_for_python_stack() -> None:
    skills = load_all_skills(REPO_ROOT)
    out = resolve_for_task(
        skills=skills,
        task=_task("Containerize FastAPI service for production deploy"),
        tier="T4",
        app_class="web",
        locked_stack=_stack("Python"),
        audience="worker",
    )
    resolved = {s.name for s in out}
    assert "deploy-dockerfile-python" in resolved
    assert "deploy-dockerfile-node" not in resolved


def test_dockerfile_node_does_not_resolve_for_t0_cli() -> None:
    """T0 single-file CLI does not get a Dockerfile skill even when the
    brief literally says 'deploy'."""
    skills = load_all_skills(REPO_ROOT)
    out = resolve_for_task(
        skills=skills,
        task=_task("Ship the CLI for production deploy"),
        tier="T0",
        app_class="web",
        locked_stack=_stack("TypeScript"),
        audience="worker",
    )
    resolved = {s.name for s in out}
    assert "deploy-dockerfile-node" not in resolved
    assert "deploy-dockerfile-python" not in resolved
    assert "deploy-docker-compose-microservices" not in resolved


def test_dockerfile_node_does_not_resolve_when_brief_says_no_docker() -> None:
    skills = load_all_skills(REPO_ROOT)
    out = resolve_for_task(
        skills=skills,
        task=_task(
            "Add a production deploy script — no docker, run on the host directly"
        ),
        tier="T4",
        app_class="web",
        locked_stack=_stack("TypeScript"),
        audience="worker",
    )
    resolved = {s.name for s in out}
    assert "deploy-dockerfile-node" not in resolved


def test_dockerfile_skills_do_not_resolve_without_deploy_keyword() -> None:
    """Default-off: a generic feature task on a T4 web project does NOT
    pull in the Dockerfile skill."""
    skills = load_all_skills(REPO_ROOT)
    out = resolve_for_task(
        skills=skills,
        task=_task(
            "Implement user-service CRUD endpoints",
            title="User CRUD",
            module_scope="user-service",
        ),
        tier="T4",
        app_class="web",
        locked_stack=_stack("TypeScript"),
        audience="worker",
    )
    resolved = {s.name for s in out}
    assert "deploy-dockerfile-node" not in resolved


def test_compose_skill_resolves_for_t5_microservices_deploy() -> None:
    skills = load_all_skills(REPO_ROOT)
    out = resolve_for_task(
        skills=skills,
        task=_task(
            "Add docker-compose for the api + worker microservices, with shared "
            "broker and database for production deploy"
        ),
        tier="T5",
        app_class="web",
        locked_stack=_stack("TypeScript"),
        audience="worker",
    )
    assert "deploy-docker-compose-microservices" in {s.name for s in out}


def test_compose_skill_does_not_resolve_for_t4_monolith() -> None:
    """Microservices compose template stays out of T4 (modular monolith)
    work — even when 'deploy' is in the brief."""
    skills = load_all_skills(REPO_ROOT)
    out = resolve_for_task(
        skills=skills,
        task=_task("Add Dockerfile for production deploy"),
        tier="T4",
        app_class="web",
        locked_stack=_stack("TypeScript"),
        audience="worker",
    )
    resolved = {s.name for s in out}
    assert "deploy-docker-compose-microservices" not in resolved


def test_dockerfile_skills_are_worker_only_not_reviewer() -> None:
    """Worker writes Dockerfiles, Reviewer doesn't need them in its
    context window."""
    skills = load_all_skills(REPO_ROOT)
    out = resolve_for_task(
        skills=skills,
        task=_task("Add Dockerfile for production deploy"),
        tier="T4",
        app_class="web",
        locked_stack=_stack("TypeScript"),
        audience="reviewer",
    )
    resolved = {s.name for s in out}
    assert "deploy-dockerfile-node" not in resolved
    assert "deploy-dockerfile-python" not in resolved
