# SPDX-License-Identifier: FSL-1.1-Apache-2.0
# Copyright (c) 2026 ortim.dev
"""M3 Skills — project-specific patterns injected into Worker/Reviewer prompts.

Each skill is a markdown file with a small YAML-like frontmatter block. The
loader walks `<repo_root>/skills/**/*.md`, parses each file, and the
resolver matches the right subset against (tier, app_class, locked_stack,
task description) per call site.

See `M3-design.md` for the full design rationale.
"""

from runtime.skills.loader import load_all_skills
from runtime.skills.resolver import format_skills_block, resolve_for_task
from runtime.skills.schema import Skill, SkillTriggers

__all__ = [
    "Skill",
    "SkillTriggers",
    "format_skills_block",
    "load_all_skills",
    "resolve_for_task",
]
