# SPDX-License-Identifier: FSL-1.1-Apache-2.0
# Copyright (c) 2026 ortim.dev
"""File-write sandbox for Worker output.

The Worker emits `FileChange` objects with workspace-relative paths. The
sandbox enforces three structural defenses (independent of the Worker's
system prompt):

  1. Path stays under the task's `module_scope` (string-prefix match after
     POSIX normalization).
  2. No `..` traversal, no absolute paths, no empty path segments.
  3. After resolving symlinks, the absolute path stays inside the workspace
     root.

A misbehaving LLM cannot bypass any of these — if it tries, the executor
raises `SandboxViolation` and the task fails or retries without writing.
"""

from __future__ import annotations

import re
from pathlib import Path, PurePosixPath


class SandboxViolation(Exception):
    pass


_WINDOWS_DRIVE = re.compile(r"^[A-Za-z]:")


def normalize_relative(raw: str) -> PurePosixPath:
    """Reject absolute paths, `..` escapes, empty paths.

    Returns a clean POSIX-style relative path with `.` segments stripped.
    `PurePosixPath.is_absolute()` only catches `/...`-style absolutes, so we
    explicitly reject Windows drive letters (`C:\\...`, `D:/...`) up front.
    """
    if not raw or not raw.strip():
        raise SandboxViolation("empty path")
    if _WINDOWS_DRIVE.match(raw):
        raise SandboxViolation(f"absolute path forbidden (windows drive): {raw}")
    p = PurePosixPath(raw.replace("\\", "/"))
    if p.is_absolute():
        raise SandboxViolation(f"absolute path forbidden: {raw}")
    parts = [part for part in p.parts if part not in ("", ".")]
    if any(part == ".." for part in parts):
        raise SandboxViolation(f"parent traversal forbidden: {raw}")
    if not parts:
        raise SandboxViolation(f"path resolves to nothing: {raw}")
    return PurePosixPath(*parts)


def check_in_scope(path: PurePosixPath, module_scope: str) -> None:
    """`path` must lie under `module_scope`; both are workspace-relative."""
    scope = normalize_relative(module_scope)
    scope_parts = scope.parts
    path_parts = path.parts
    if len(path_parts) <= len(scope_parts):
        raise SandboxViolation(
            f"path {path} is not strictly inside module_scope {module_scope}"
        )
    if path_parts[: len(scope_parts)] != scope_parts:
        raise SandboxViolation(
            f"path {path} is not under module_scope {module_scope}"
        )


def resolve_in_workspace(workspace_root: Path, rel: PurePosixPath) -> Path:
    """Resolve to absolute path; raise if symlink/escape pulls it outside `workspace_root`."""
    abs_path = (workspace_root / rel).resolve()
    workspace_resolved = workspace_root.resolve()
    try:
        abs_path.relative_to(workspace_resolved)
    except ValueError as e:
        raise SandboxViolation(
            f"resolved path {abs_path} escapes workspace {workspace_resolved}"
        ) from e
    return abs_path


_BASE_EXTS = frozenset({
    # Docs / text — used in every app class
    ".md", ".rst", ".txt", ".adoc",
    # Config — used everywhere
    ".json", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".env", ".lock",
    # Scripts — every project may want them
    ".sh", ".bash", ".zsh", ".ps1", ".bat", ".cmd",
    # Data / schema
    ".sql", ".proto", ".graphql", ".gql", ".csv", ".tsv",
    # Python — ubiquitous (build scripts, mobile native helpers, devops)
    ".py", ".pyi",
})

_WEB_EXTS = frozenset({
    # JS / TS / web frontends
    ".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs",
    ".html", ".htm", ".css", ".scss", ".sass", ".less", ".vue", ".svelte",
    # Server backends — Python lives in BASE; the rest belong to web tier scope
    ".go", ".rs", ".java", ".rb", ".cs",
    ".cpp", ".cc", ".c", ".h", ".hpp", ".hxx", ".scala",
})

_MOBILE_EXTS = frozenset({
    ".dart",
    ".swift", ".kt", ".kts", ".gradle",
    ".plist", ".xcconfig", ".pbxproj",
    ".m", ".mm", ".java",
})

_DESKTOP_EXTS = frozenset({
    ".rs",
    ".swift", ".cs",
    ".cpp", ".cc", ".c", ".h", ".hpp",
    ".xaml", ".icns", ".ico", ".rc",
})

# app_class → allowed extension set. Mobile/desktop deliberately exclude the
# full web set so a hallucinated `lib.rs` in a Flutter project is rejected.
_EXT_BY_APP_CLASS: dict[str, frozenset[str]] = {
    "web": _BASE_EXTS | _WEB_EXTS,
    "mobile": _BASE_EXTS | _MOBILE_EXTS,
    "desktop": _BASE_EXTS | _DESKTOP_EXTS,
    "mixed": _BASE_EXTS | _WEB_EXTS | _MOBILE_EXTS | _DESKTOP_EXTS,
}

_ALLOWED_BASENAMES = frozenset({
    "Dockerfile", "Makefile", "Procfile", "Rakefile", "Gemfile",
    "LICENSE", "README", "CHANGELOG", "CONTRIBUTING",
    ".gitignore", ".gitattributes", ".gitkeep",
    ".dockerignore", ".editorconfig",
    ".env.example", ".env.template",
})


def check_extension(path: PurePosixPath, app_class: str = "web") -> None:
    """Reject file types outside the source-code / docs / config whitelist.

    `app_class` partitions the whitelist: web tier projects cannot write
    `.dart`, mobile cannot write `.rs`, etc. Default `"web"` keeps pre-M1
    callers backward-compatible; brownfield projects pass the detected
    `CodebaseSummary.app_class_hint` so a hallucinated extension fails fast.
    """
    name = path.name
    if name in _ALLOWED_BASENAMES:
        return
    if "." not in name:
        raise SandboxViolation(
            f"unknown file type (no extension and not a known basename): {name}"
        )
    allowed = _EXT_BY_APP_CLASS.get(app_class)
    if allowed is None:
        raise SandboxViolation(
            f"unknown app_class {app_class!r}; "
            f"valid: {sorted(_EXT_BY_APP_CLASS)}"
        )
    ext = "." + name.rsplit(".", 1)[-1].lower()
    if ext not in allowed:
        raise SandboxViolation(
            f"file extension {ext!r} not in {app_class} whitelist; "
            f"allowed: {sorted(allowed)}"
        )
