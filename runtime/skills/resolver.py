# SPDX-License-Identifier: FSL-1.1-Apache-2.0
# Copyright (c) 2026 ortim.dev
"""Skill resolver — pick the right subset for a given call site.

Inputs come from the task spec, the locked stack (M2 LockedStack), and
the audience (`worker` or `reviewer`). Outputs are bounded by both a
max-count cap and a total-body char cap so a runaway skill collection
can't blow up the prompt budget.
"""

from __future__ import annotations

from runtime.architecture import LockedStack
from runtime.orchestrator import TaskSpec
from runtime.skills.schema import Skill

DEFAULT_MAX_SKILLS = 5
DEFAULT_CHAR_BUDGET = 12_000


def resolve_for_task(
    *,
    skills: list[Skill],
    task: TaskSpec,
    tier: str | None,
    app_class: str | None,
    locked_stack: LockedStack | None,
    audience: str,
    max_skills: int = DEFAULT_MAX_SKILLS,
    char_budget: int = DEFAULT_CHAR_BUDGET,
) -> list[Skill]:
    """Return the skills that apply to this call site, ordered by
    specificity (most-specific first) and bounded by `max_skills` +
    `char_budget`.

    `locked_stack`'s `language` field drives the language trigger when
    provided; when `None`, skills with a language trigger are filtered
    out (we can't promise a language match without the stack).
    """
    language = locked_stack.language if locked_stack is not None else None
    description = f"{task.title}\n{task.description}\n{task.module_scope}"

    candidates = [
        s
        for s in skills
        if s.applies_to(
            audience=audience,
            tier=tier,
            app_class=app_class,
            language=language,
            description=description,
        )
    ]
    candidates.sort(key=lambda s: (-s.triggers.specificity(), s.name))

    out: list[Skill] = []
    used_chars = 0
    for skill in candidates:
        if len(out) >= max_skills:
            break
        body_len = len(skill.body)
        if used_chars + body_len > char_budget:
            continue
        out.append(skill)
        used_chars += body_len
    return out


def format_skills_block(
    skills: list[Skill], *, audience: str
) -> str:
    """Render a sequence of resolved skills as a prompt block ready to
    be appended after L1 principles in a Worker or Reviewer system
    prompt. Returns an empty string when no skills resolved — callers
    can append it unconditionally without an extra branch.
    """
    if not skills:
        return ""
    if audience == "worker":
        header = (
            "## Active Skills\n\n"
            "The following project-specific patterns are HARD rules — same "
            "weight as L1 principles. They override any default coding "
            "habits a model may have for this language or framework.\n"
        )
    elif audience == "reviewer":
        header = (
            "## Active Skills\n\n"
            "Acceptance criteria are interpreted in the context of these "
            "project patterns. If the Worker output violates a skill, mark "
            "the relevant criterion `fail` and cite the skill name in the "
            "verdict reason.\n"
        )
    else:
        header = "## Active Skills\n"

    parts: list[str] = [header]
    for skill in skills:
        parts.append(
            f"\n### {skill.name} — {skill.description}\n\n{skill.body}\n"
        )
    return "\n".join(parts).rstrip() + "\n"
