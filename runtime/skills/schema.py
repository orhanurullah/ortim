# SPDX-License-Identifier: FSL-1.1-Apache-2.0
# Copyright (c) 2026 ortim.dev
"""Skill + SkillTriggers pydantic schemas.

The triggers model is deliberately narrow for M3 — `tier`, `app_class`,
`language`, `keywords`. Per-tier-and-app-class combinations are too rare
in practice to warrant a separate axis; the resolver AND-s the four
groups so a skill targeting `(language=TypeScript, app_class=web)` covers
any tier the locked stack happens to pick.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class SkillTriggers(BaseModel):
    tier: list[str] = Field(default_factory=list)
    app_class: list[str] = Field(default_factory=list)
    language: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)

    def is_universal(self) -> bool:
        """A skill is universal iff it has no triggers at all — applies
        anywhere the audience filter allows."""
        return not (self.tier or self.app_class or self.language or self.keywords)

    def specificity(self) -> int:
        """Higher = more specific = preferred when the budget is tight.
        Language match weighs most because the seed skills are
        language-keyed; tier is next; app_class smallest. Universal
        skills score 0 and lose every tiebreak."""
        score = 0
        if self.language:
            score += 4
        if self.tier:
            score += 2
        if self.app_class:
            score += 1
        return score


class Skill(BaseModel):
    name: str
    description: str
    audience: list[str] = Field(default_factory=lambda: ["worker", "reviewer"])
    triggers: SkillTriggers = Field(default_factory=SkillTriggers)
    body: str
    path: str = ""
    """Repo-relative path of the source file; populated by the loader.
    Useful for audit log and `ortim skill show` debug output."""

    def applies_to(
        self,
        *,
        audience: str,
        tier: str | None,
        app_class: str | None,
        language: str | None,
        description: str,
    ) -> bool:
        """Return True iff every populated trigger group has a match.

        Empty trigger groups are treated as "match anything" (the
        universal escape hatch). All populated groups must match — they
        are AND'd at the group level, OR'd within a group.
        """
        if audience not in self.audience:
            return False

        if self.triggers.tier and (tier is None or tier not in self.triggers.tier):
            return False

        if self.triggers.app_class and (
            app_class is None or app_class not in self.triggers.app_class
        ):
            return False

        # Language trigger: when locked_stack is missing, language is
        # None and the skill matches only if it didn't specify a
        # language filter. This is intentional — pre-M2 projects without
        # a locked stack can't be promised a stack-specific skill set.
        if self.triggers.language:
            if language is None:
                return False
            if language not in self.triggers.language:
                return False

        if self.triggers.keywords:
            haystack = description.lower()
            if not any(kw.lower() in haystack for kw in self.triggers.keywords):
                return False

        return True
