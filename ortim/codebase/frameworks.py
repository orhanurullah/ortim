# SPDX-License-Identifier: FSL-1.1-Apache-2.0
# Copyright (c) 2026 ortim.dev
"""Framework detection for the codebase reader.

Each rule has up to three signals:

  1. Manifest presence — file at the workspace root (`pubspec.yaml`,
     `pyproject.toml`, `package.json`, etc.).
  2. Manifest content match — a regex inside the manifest (e.g. the line
     `flutter:` directly under `dependencies:` for Flutter).
  3. Code import match — at least one source file under a glob whose
     content matches an import pattern.

Confidence = (signals_matched / signals_defined). A rule with two of three
signals scores 0.66.

Adding a framework: append a `FrameworkRule` entry. Keep rules small and
specific — false positives in this layer cascade into wrong tier choices.

M1 scope (Day 1): Flutter, FastAPI. Other frameworks (Next.js, Tauri,
Electron, React, Vue) added incrementally as M1+ exit criteria require.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from ortim.codebase.schema import FrameworkHint


@dataclass(frozen=True)
class FrameworkRule:
    name: str
    app_class: str  # "web" | "mobile" | "desktop"
    manifest: str  # filename relative to root
    manifest_match: str | None = None  # regex against manifest content
    code_globs: tuple[str, ...] = field(default_factory=tuple)
    code_match: str | None = None  # regex against any file matching code_globs
    version_pattern: str | None = None  # regex with one capture group
    parse_version: Callable[[str], str | None] | None = None


def _read_text_safe(path: Path, max_bytes: int = 50_000) -> str:
    try:
        with path.open("r", encoding="utf-8", errors="replace") as f:
            return f.read(max_bytes)
    except OSError:
        return ""


# ---- Rule registry ----------------------------------------------------------

FLUTTER = FrameworkRule(
    name="flutter",
    app_class="mobile",
    manifest="pubspec.yaml",
    # `flutter:` block under `dependencies:` — the canonical Flutter signal.
    # We match a relaxed pattern: `flutter:` line followed (within ~3 lines)
    # by `sdk: flutter`. This avoids false-positives on packages that just
    # declare a `flutter` key in their pubspec.
    manifest_match=r"flutter:\s*\n\s*sdk:\s*flutter",
    code_globs=("lib/**/*.dart", "lib/*.dart"),
    code_match=r"import\s+['\"]package:flutter/",
    version_pattern=r"sdk:\s*['\"]?\s*[>=^~]*\s*([\d.]+)",
)

FASTAPI = FrameworkRule(
    name="fastapi",
    app_class="web",
    manifest="pyproject.toml",
    manifest_match=r"fastapi\s*[=>~]",
    code_globs=("**/*.py",),
    code_match=r"^\s*from\s+fastapi\s+import|^\s*import\s+fastapi",
    version_pattern=r"fastapi\s*[=><~^]+\s*['\"]?([\d.]+)",
)

# requirements.txt fallback for FastAPI projects that don't use pyproject
FASTAPI_REQUIREMENTS = FrameworkRule(
    name="fastapi",
    app_class="web",
    manifest="requirements.txt",
    manifest_match=r"^fastapi\b",
    code_globs=("**/*.py",),
    code_match=r"^\s*from\s+fastapi\s+import|^\s*import\s+fastapi",
    version_pattern=r"^fastapi[=><~]+([\d.]+)",
)

# Pytest — used to drive baseline test command auto-detection in M1.
PYTEST = FrameworkRule(
    name="pytest",
    app_class="web",  # tooling, not a UI framework; doesn't affect app_class
    manifest="pyproject.toml",
    manifest_match=r"\[tool\.pytest\.ini_options\]|pytest\s*[=>~]",
    code_globs=("tests/**/*.py", "test/**/*.py"),
    code_match=r"^\s*def\s+test_|^\s*import\s+pytest|^\s*from\s+pytest\s+import",
    version_pattern=r"pytest\s*[=><~^]+\s*['\"]?([\d.]+)",
)

# ---- JS / TS web ----------------------------------------------------------

NEXTJS = FrameworkRule(
    name="nextjs",
    app_class="web",
    manifest="package.json",
    # `"next"` as a top-level dependency or devDependency. We accept either
    # a direct match in the dependencies block or `next.config.*` later via
    # code_match, but at the manifest level `"next":` is the canonical signal.
    manifest_match=r'"next"\s*:\s*"',
    code_globs=("pages/**/*", "app/**/*", "next.config.*"),
    code_match=r"^\s*import\s+.*['\"]next/|from\s+['\"]next/",
    version_pattern=r'"next"\s*:\s*"([^"]+)"',
)

REACT = FrameworkRule(
    name="react",
    app_class="web",
    manifest="package.json",
    manifest_match=r'"react"\s*:\s*"',
    code_globs=("src/**/*.tsx", "src/**/*.jsx", "src/**/*.ts", "src/**/*.js"),
    code_match=r"^\s*import\s+(?:React|\{[^}]*\}|\*)\s+from\s+['\"]react['\"]",
    version_pattern=r'"react"\s*:\s*"([^"]+)"',
)

VUE = FrameworkRule(
    name="vue",
    app_class="web",
    manifest="package.json",
    manifest_match=r'"vue"\s*:\s*"',
    code_globs=("src/**/*.vue", "src/**/*.ts", "src/**/*.js"),
    code_match=r"from\s+['\"]vue['\"]|<template>",
    version_pattern=r'"vue"\s*:\s*"([^"]+)"',
)

SVELTE = FrameworkRule(
    name="svelte",
    app_class="web",
    manifest="package.json",
    manifest_match=r'"svelte"\s*:\s*"',
    code_globs=("src/**/*.svelte", "src/**/*.ts"),
    code_match=r"<script\s+lang=['\"]ts['\"]>|from\s+['\"]svelte['\"]",
    version_pattern=r'"svelte"\s*:\s*"([^"]+)"',
)

# ---- Desktop ---------------------------------------------------------------

TAURI = FrameworkRule(
    name="tauri",
    app_class="desktop",
    manifest="package.json",
    manifest_match=r'"@tauri-apps/(?:api|cli)"\s*:\s*"',
    code_globs=("src-tauri/**/*.rs", "src-tauri/Cargo.toml", "src-tauri/tauri.conf.json"),
    code_match=r"^\s*use\s+tauri::|tauri\.conf\.json",
    version_pattern=r'"@tauri-apps/api"\s*:\s*"([^"]+)"',
)

ELECTRON = FrameworkRule(
    name="electron",
    app_class="desktop",
    manifest="package.json",
    manifest_match=r'"electron"\s*:\s*"',
    code_globs=("src/**/*.ts", "src/**/*.js", "main.js", "main.ts"),
    code_match=r"^\s*(?:import|require\().*['\"]electron['\"]",
    version_pattern=r'"electron"\s*:\s*"([^"]+)"',
)

ALL_RULES: tuple[FrameworkRule, ...] = (
    FLUTTER,
    FASTAPI,
    FASTAPI_REQUIREMENTS,
    PYTEST,
    # JS/TS web (order matters — more specific first since rules dedupe by name)
    NEXTJS,
    REACT,
    VUE,
    SVELTE,
    # Desktop
    TAURI,
    ELECTRON,
)

# Tooling rules contribute to detection breadth but should not influence
# `app_class` derivation. Pytest is the obvious one; testing libraries and
# linters will land here as we add them.
_TOOLING_NAMES: frozenset[str] = frozenset({"pytest"})


# ---- Detection driver -------------------------------------------------------


def detect(
    root: Path,
    manifest_contents: dict[str, str],
    file_paths: list[str],
    file_reader: Callable[[str], str] | None = None,
) -> list[FrameworkHint]:
    """Scan a codebase and return framework hints.

    Parameters
    ----------
    root :
        Absolute workspace root. Used only to emit evidence paths.
    manifest_contents :
        Pre-read map of `manifest_filename -> contents`. The reader passes
        this in once so we don't re-read the same `pubspec.yaml` per rule.
    file_paths :
        POSIX-relative paths of all files in the scan (post-gitignore).
    file_reader :
        Callable that returns file content given a POSIX-relative path.
        If None, code-match checks are skipped (manifest-only mode).

    Returns
    -------
    Hints sorted by confidence descending. Rules that scored 0 (no signals
    matched) are dropped. Duplicates by `name` are deduped, keeping the
    higher-confidence hit.
    """
    hits: dict[str, FrameworkHint] = {}

    for rule in ALL_RULES:
        signals_defined = 1  # manifest presence is always one signal
        if rule.manifest_match:
            signals_defined += 1
        if rule.code_match:
            signals_defined += 1

        signals_matched = 0
        evidence: list[str] = []

        manifest_text = manifest_contents.get(rule.manifest)
        if manifest_text is None:
            continue  # no manifest, no rule activation
        signals_matched += 1
        evidence.append(rule.manifest)

        if rule.manifest_match:
            if re.search(rule.manifest_match, manifest_text, re.MULTILINE):
                signals_matched += 1
                evidence.append(f"{rule.manifest}:match")
            else:
                continue  # manifest_match required if defined

        version: str | None = None
        if rule.version_pattern:
            m = re.search(rule.version_pattern, manifest_text, re.MULTILINE)
            if m:
                version = m.group(1)

        if rule.code_match and file_reader is not None:
            # Find at least one file matching any code_glob, then test code_match.
            matched_file = _find_first_code_match(
                rule.code_globs, rule.code_match, file_paths, file_reader
            )
            if matched_file:
                signals_matched += 1
                evidence.append(matched_file)

        confidence = signals_matched / signals_defined
        hint = FrameworkHint(
            name=rule.name,
            confidence=round(confidence, 2),
            evidence=evidence,
            version=version,
        )
        existing = hits.get(rule.name)
        if existing is None or hint.confidence > existing.confidence:
            hits[rule.name] = hint

    return sorted(hits.values(), key=lambda h: -h.confidence)


def _find_first_code_match(
    globs: tuple[str, ...],
    pattern: str,
    file_paths: list[str],
    file_reader: Callable[[str], str],
) -> str | None:
    """Return the first POSIX path whose content matches `pattern`.

    Glob matching is via `Path.match` semantics on POSIX-style paths.
    Capped at 30 files inspected per rule for performance.
    """
    from fnmatch import fnmatchcase

    rgx = re.compile(pattern, re.MULTILINE)
    inspected = 0
    for path in file_paths:
        if inspected >= 30:
            return None
        if not any(fnmatchcase(path, g) for g in globs):
            continue
        inspected += 1
        text = file_reader(path)
        if rgx.search(text):
            return path
    return None


def derive_app_class(hints: list[FrameworkHint]) -> str | None:
    """Pick the app_class from the highest-confidence non-tooling framework.

    Tooling frameworks (pytest, lint/test libraries) are excluded — a Python
    project that's only pytest doesn't have a known app_class. If Flutter +
    Pytest co-exist, Flutter wins → mobile.

    When multiple non-tooling frameworks span different app classes
    (e.g. FastAPI + Flutter monorepo), result is "mixed" and the Architect
    is expected to resolve by explicit input.
    """
    rule_by_name = {r.name: r for r in ALL_RULES}
    contributing = [
        h for h in hints
        if rule_by_name.get(h.name) and h.name not in _TOOLING_NAMES
    ]
    if not contributing:
        return None
    classes = {rule_by_name[h.name].app_class for h in contributing}
    if len(classes) == 1:
        return next(iter(classes))
    return "mixed"
