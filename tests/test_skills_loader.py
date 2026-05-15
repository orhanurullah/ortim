# SPDX-License-Identifier: FSL-1.1-Apache-2.0
# Copyright (c) 2026 ortim.dev
"""Skill loader + frontmatter parser unit tests.

Six guarantees:
  - frontmatter parses flat keys and dotted nested keys
  - list values `[a, b, c]` parse as lists; scalars parse as strings
  - missing frontmatter (no `---` block) still loads but applies universally
  - audience field defaults to [worker, reviewer]
  - bad frontmatter (unclosed `---`) is skipped, doesn't kill the loader
  - filename without `name:` field falls back to the file stem
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from runtime.skills.loader import load_all_skills  # noqa: E402


def _make_skill_repo(files: dict[str, str]) -> Path:
    root = Path(tempfile.mkdtemp())
    (root / "skills").mkdir()
    for rel, body in files.items():
        target = root / "skills" / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(body, encoding="utf-8")
    return root


def test_loader_parses_flat_and_nested_keys() -> None:
    repo = _make_skill_repo(
        {
            "typescript/module-boundaries.md": (
                "---\n"
                "name: ts-modules\n"
                "description: barrel imports only\n"
                "audience: [worker]\n"
                "triggers:\n"
                "  language: [TypeScript]\n"
                "  app_class: [web]\n"
                "---\n\n"
                "# Body\n\nUse barrel imports.\n"
            )
        }
    )
    skills = load_all_skills(repo)
    assert len(skills) == 1
    s = skills[0]
    assert s.name == "ts-modules"
    assert s.description == "barrel imports only"
    assert s.audience == ["worker"]
    assert s.triggers.language == ["TypeScript"]
    assert s.triggers.app_class == ["web"]
    assert s.triggers.tier == []
    assert "Use barrel imports." in s.body


def test_loader_handles_scalar_audience() -> None:
    """`audience: worker` (no brackets) should normalize to a 1-element list."""
    repo = _make_skill_repo(
        {
            "x/scalar.md": (
                "---\n"
                "name: scalar-audience\n"
                "description: test\n"
                "audience: worker\n"
                "---\n\nbody"
            )
        }
    )
    skills = load_all_skills(repo)
    assert skills[0].audience == ["worker"]


def test_loader_missing_frontmatter_uses_filename_as_name() -> None:
    repo = _make_skill_repo({"misc/no-fm.md": "Just a body without frontmatter.\n"})
    skills = load_all_skills(repo)
    assert len(skills) == 1
    assert skills[0].name == "no-fm"
    assert "Just a body" in skills[0].body
    # No triggers means universal
    assert skills[0].triggers.is_universal()
    # Default audience is both
    assert set(skills[0].audience) == {"worker", "reviewer"}


def test_loader_audience_defaults_to_both() -> None:
    repo = _make_skill_repo(
        {
            "x/default-aud.md": (
                "---\nname: default-aud\ndescription: t\n---\n\nbody"
            )
        }
    )
    skills = load_all_skills(repo)
    assert set(skills[0].audience) == {"worker", "reviewer"}


def test_loader_skips_malformed_file_without_killing_others() -> None:
    repo = _make_skill_repo(
        {
            "good/ok.md": "---\nname: ok\ndescription: t\n---\n\nbody",
            "bad/broken.md": "---\nname: broken\ndescription: t\n# never closed\n",
        }
    )
    skills = load_all_skills(repo)
    names = [s.name for s in skills]
    assert "ok" in names
    assert "broken" not in names


def test_loader_list_values_strip_quotes_and_whitespace() -> None:
    repo = _make_skill_repo(
        {
            "x/lists.md": (
                "---\n"
                "name: list-quotes\n"
                "description: t\n"
                "triggers:\n"
                '  tier: ["T1", "T2", T3]\n'
                "  keywords: [test, import, module]\n"
                "---\n\nbody"
            )
        }
    )
    skills = load_all_skills(repo)
    assert skills[0].triggers.tier == ["T1", "T2", "T3"]
    assert skills[0].triggers.keywords == ["test", "import", "module"]
