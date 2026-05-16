# SPDX-License-Identifier: FSL-1.1-Apache-2.0
# Copyright (c) 2026 ortim.dev
"""Skill loader — walks `<repo_root>/skills/**/*.md` and parses each file.

Each skill is a markdown file with a small YAML-like frontmatter block at
the top, delimited by `---` lines. The parser is deliberately small (no
PyYAML dep): only `key: value` and `key: [a, b, c]` are supported. Nested
keys (`triggers.tier`) collapse to dotted notation: `triggers.tier: [T1, T2]`.

Malformed individual files are skipped with a stderr warning so a typo
in one skill never breaks the loader for the rest.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

from runtime.skills.schema import Skill, SkillTriggers

_FRONTMATTER_DELIM = "---"


def load_all_skills(repo_root: Path) -> list[Skill]:
    """Discover every `*.md` under `<repo_root>/skills/` and load it.

    Returns the skills in alphabetical order by `name` for deterministic
    iteration. Files that fail to parse are skipped with a stderr
    warning — never raises.
    """
    skills_dir = repo_root / "skills"
    if not skills_dir.exists():
        return []
    out: list[Skill] = []
    for path in sorted(skills_dir.rglob("*.md")):
        rel = path.relative_to(repo_root).as_posix()
        try:
            skill = _parse_skill_file(path, rel_path=rel)
        except Exception as exc:  # narrow tracebacks aren't useful to operators
            print(
                f"[ortim] WARNING: skill {rel} failed to parse: {exc}",
                file=sys.stderr,
            )
            continue
        out.append(skill)
    out.sort(key=lambda s: s.name)
    return out


def _parse_skill_file(path: Path, rel_path: str) -> Skill:
    text = path.read_text(encoding="utf-8")
    frontmatter, body = _split_frontmatter(text)
    fm = _parse_frontmatter(frontmatter)

    name = fm.get("name") or path.stem
    description = fm.get("description") or ""
    audience_raw = fm.get("audience")
    audience: list[str]
    if isinstance(audience_raw, list):
        audience = [a.strip() for a in audience_raw if a.strip()]
    elif isinstance(audience_raw, str) and audience_raw.strip():
        audience = [audience_raw.strip()]
    else:
        audience = ["worker", "reviewer"]

    triggers = SkillTriggers(
        tier=_as_list(fm.get("triggers.tier")),
        app_class=_as_list(fm.get("triggers.app_class")),
        language=_as_list(fm.get("triggers.language")),
        keywords=_as_list(fm.get("triggers.keywords")),
        keywords_blocklist=_as_list(fm.get("triggers.keywords_blocklist")),
    )

    return Skill(
        name=name,
        description=description,
        audience=audience,
        triggers=triggers,
        body=body.strip(),
        path=rel_path,
    )


def _split_frontmatter(text: str) -> tuple[str, str]:
    stripped = text.lstrip("﻿")  # tolerate BOM
    lines = stripped.splitlines()
    if not lines or lines[0].strip() != _FRONTMATTER_DELIM:
        # No frontmatter at all — treat the whole file as body. The skill
        # will have a generated name from the filename and apply
        # universally.
        return "", stripped
    end_idx: int | None = None
    for i in range(1, len(lines)):
        if lines[i].strip() == _FRONTMATTER_DELIM:
            end_idx = i
            break
    if end_idx is None:
        raise ValueError("frontmatter opened with '---' but never closed")
    fm = "\n".join(lines[1:end_idx])
    body = "\n".join(lines[end_idx + 1:])
    return fm, body


_LIST_RE = re.compile(r"^\[(.*)\]$")
_KV_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_.-]*)\s*:\s*(.*)$")
_INDENTED_NESTED_RE = re.compile(r"^\s{2,}([A-Za-z_][A-Za-z0-9_-]*)\s*:\s*(.*)$")
_BULLET_RE = re.compile(r"^\s+-\s+(.+)$")


def _parse_frontmatter(text: str) -> dict[str, object]:
    """Lightweight subset of YAML. Supports:
      key: value
      key: [a, b, c]
      key:
        - item
        - item
      key:
        nested_key: value
        nested_key: [a, b]
        nested_key:
          - item
          - item
    Nested keys are exposed as dotted names: `triggers.tier`.
    """
    out: dict[str, object] = {}
    current_parent: str | None = None
    pending_bullet_key: str | None = None
    for raw in text.splitlines():
        line = raw.rstrip()
        if not line.strip() or line.lstrip().startswith("#"):
            continue

        bullet = _BULLET_RE.match(line)
        if bullet:
            if pending_bullet_key is None:
                raise ValueError(
                    f"unexpected bullet — no preceding key with empty value: {line!r}"
                )
            item = bullet.group(1).strip().strip('"').strip("'")
            existing = out.get(pending_bullet_key)
            if isinstance(existing, list):
                existing.append(item)
            else:
                out[pending_bullet_key] = [item]
            continue

        nested = _INDENTED_NESTED_RE.match(line)
        if nested and current_parent is not None:
            key = f"{current_parent}.{nested.group(1)}"
            value = nested.group(2).strip()
            if value == "":
                # Either a deeper nested object (not supported beyond
                # one level) or a bullet list belonging to this key.
                pending_bullet_key = key
            else:
                pending_bullet_key = None
                out[key] = _parse_scalar_or_list(value)
            continue

        # Fresh top-level key — any pending bullet collection is closed.
        pending_bullet_key = None

        m = _KV_RE.match(line)
        if not m:
            raise ValueError(f"frontmatter line not understood: {line!r}")
        key = m.group(1)
        value = m.group(2).strip()
        if value == "":
            # The next indented lines belong to this parent — could be a
            # nested object (sets current_parent) OR a flat bullet list
            # (sets pending_bullet_key). Arm both; whichever shape the
            # next line takes wins.
            current_parent = key
            pending_bullet_key = key
            continue
        out[key] = _parse_scalar_or_list(value)
        current_parent = None
    return out


def _parse_scalar_or_list(value: str) -> object:
    value = value.strip()
    list_match = _LIST_RE.match(value)
    if list_match:
        inner = list_match.group(1).strip()
        if not inner:
            return []
        return [item.strip().strip('"').strip("'") for item in inner.split(",")]
    # Strip inline trailing comments + surrounding quotes.
    if "#" in value:
        value = value.split("#", 1)[0].strip()
    return value.strip('"').strip("'")


def _as_list(value: object) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(x).strip() for x in value if str(x).strip()]
    s = str(value).strip()
    return [s] if s else []
