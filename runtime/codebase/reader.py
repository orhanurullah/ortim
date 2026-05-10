# SPDX-License-Identifier: FSL-1.1-Apache-2.0
# Copyright (c) 2026 ortim.dev
"""Codebase scanner — gitignore-aware walk + mtime+sha1 cache.

Cold scan target: <3s for ~1000 files. Warm scan (no changes): <200ms.
Warm scan (a handful of changes): <500ms. Cache lives at the path the
caller supplies (typically `<workspace>/.cache/codebase.json`).

The scanner is tier-agnostic: it reports what it finds, the Architect's
deterministic scorer decides what to do with the signals.
"""

from __future__ import annotations

import ast
import hashlib
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path

import pathspec

from runtime.codebase import frameworks
from runtime.codebase.schema import (
    CodebaseSummary,
    FileEntry,
    FrameworkHint,
    ModuleSymbols,
    ScanStats,
)

# Default byte budget for read_related — tuned so a Worker prompt with the
# fixed ~10KB header (system + L1 + RFC + retry) plus related_files stays
# under ~50KB total. Override via `ORTIM_RELATED_FILES_BYTES` /
# `AI_FACTORY_RELATED_FILES_BYTES`.
_DEFAULT_RELATED_BYTES = 30_000

# read_related ranking weights — tunable, but tests pin behavior.
_W_DIRECT_MATCH = 100
_W_DESCRIPTION_MATCH = 50
_W_IMPORT_NEIGHBOR = 20
_W_SIZE_PENALTY_PER_KB = 10
_W_STALE_PENALTY = 1000  # effectively elimination

# Hard skips — applied even when no .gitignore is present, because these
# directories produce massive false-positive walks on Python/JS/Flutter
# repos and never contain user-authored source code.
_HARD_SKIP_DIRS = frozenset({
    ".git",
    ".venv",
    "venv",
    "node_modules",
    "build",
    ".dart_tool",
    ".next",
    "dist",
    "target",
    ".cache",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".idea",
    ".vscode",
    ".gradle",
    "Pods",
})

# Manifest filenames the framework detector cares about. Read once and
# passed to `frameworks.detect`.
_MANIFEST_NAMES = frozenset({
    "pubspec.yaml",
    "pyproject.toml",
    "requirements.txt",
    "package.json",
    "Cargo.toml",
    "go.mod",
})

_LANG_BY_EXT: dict[str, str] = {
    ".py": "python",
    ".pyi": "python",
    ".dart": "dart",
    ".js": "javascript",
    ".mjs": "javascript",
    ".cjs": "javascript",
    ".jsx": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".go": "go",
    ".rs": "rust",
    ".java": "java",
    ".kt": "kotlin",
    ".kts": "kotlin",
    ".swift": "swift",
    ".rb": "ruby",
    ".cs": "csharp",
    ".cpp": "cpp",
    ".c": "c",
    ".h": "c",
    ".hpp": "cpp",
    ".html": "html",
    ".css": "css",
    ".scss": "css",
    ".vue": "vue",
    ".svelte": "svelte",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".toml": "toml",
    ".json": "json",
    ".md": "markdown",
    ".sql": "sql",
    ".sh": "shell",
    ".bash": "shell",
    ".ps1": "powershell",
    ".gradle": "gradle",
    ".plist": "plist",
}

# Files large enough that we skip hashing/parsing — they're treated as
# opaque assets. 200KB cap covers >99% of source files we care about.
_DEFAULT_MAX_BYTES_PER_FILE = 200_000

# Languages whose top-level public symbols we extract.
_SYMBOL_LANGS = {"python", "dart", "typescript", "javascript"}


# ---- Public API -------------------------------------------------------------


def scan_codebase(
    root: Path,
    max_files: int = 2000,
    max_bytes_per_file: int = _DEFAULT_MAX_BYTES_PER_FILE,
    cache_path: Path | None = None,
) -> CodebaseSummary:
    """Walk `root`, build a CodebaseSummary, optionally read/write a cache.

    The cache file is JSON serialization of a previous CodebaseSummary. We
    use it to skip re-reading and re-parsing files whose (path, mtime, size)
    tuple is unchanged. Files removed from disk are removed from the new
    summary; new files are parsed fresh.

    Raises FileNotFoundError if `root` does not exist.
    """
    if not root.exists():
        raise FileNotFoundError(f"Codebase root not found: {root}")
    if not root.is_dir():
        raise NotADirectoryError(f"Codebase root is not a directory: {root}")

    started_ns = time.perf_counter_ns()
    root_resolved = root.resolve()

    # 1. Build the gitignore matcher. Hard skips apply on top of whatever
    #    .gitignore declares.
    spec = _load_gitignore(root_resolved)

    # 2. Load any prior cache. Mismatched root → ignored (different repo).
    cache_index: dict[str, FileEntry] = {}
    cache_modules: dict[str, ModuleSymbols] = {}
    if cache_path and cache_path.exists():
        try:
            cached = CodebaseSummary.model_validate_json(
                cache_path.read_text(encoding="utf-8")
            )
            if cached.root == str(root_resolved):
                cache_index = {fe.path: fe for fe in cached.files}
                cache_modules = {ms.path: ms for ms in cached.modules}
        except (ValueError, OSError):
            # Corrupt cache → silently ignore, the rescan will recreate it.
            pass

    # 3. Walk filesystem. Stop when max_files cap is reached.
    truncated = False
    walked_paths: list[Path] = []
    for path in _walk(root_resolved, spec):
        if len(walked_paths) >= max_files:
            truncated = True
            break
        walked_paths.append(path)

    # 4. For each file: try cache first. Record stats.
    files: list[FileEntry] = []
    modules: list[ModuleSymbols] = []
    languages: dict[str, int] = {}
    manifest_contents: dict[str, str] = {}
    files_parsed_fresh = 0
    files_parsed_from_cache = 0
    fresh_content: dict[str, str] = {}  # rel_path -> text, for framework code-match

    for abs_path in walked_paths:
        try:
            stat = abs_path.stat()
        except OSError:
            continue
        rel = abs_path.relative_to(root_resolved).as_posix()
        size = stat.st_size
        mtime_ns = stat.st_mtime_ns
        ext = abs_path.suffix.lower()
        languages[ext] = languages.get(ext, 0) + 1

        cached_entry = cache_index.get(rel)
        if (
            cached_entry is not None
            and cached_entry.mtime_ns == mtime_ns
            and cached_entry.size_bytes == size
        ):
            files.append(cached_entry)
            files_parsed_from_cache += 1
            cached_module = cache_modules.get(rel)
            if cached_module is not None:
                modules.append(cached_module)
            # Manifests still need their content for framework detection.
            if abs_path.name in _MANIFEST_NAMES and rel == abs_path.name:
                manifest_contents[abs_path.name] = _read_text(abs_path)
            continue

        # Fresh parse path
        files_parsed_fresh += 1
        if size > max_bytes_per_file:
            files.append(
                FileEntry(
                    path=rel,
                    size_bytes=size,
                    mtime_ns=mtime_ns,
                    sha1="",
                    language=_LANG_BY_EXT.get(ext),
                    role=_role_for(rel),
                )
            )
            continue

        text = _read_text(abs_path)
        sha = hashlib.sha1(text.encode("utf-8", errors="replace")).hexdigest()
        lang = _LANG_BY_EXT.get(ext)
        files.append(
            FileEntry(
                path=rel,
                size_bytes=size,
                mtime_ns=mtime_ns,
                sha1=sha,
                language=lang,
                role=_role_for(rel),
            )
        )
        fresh_content[rel] = text

        if abs_path.name in _MANIFEST_NAMES and "/" not in rel:
            manifest_contents[abs_path.name] = text

        if lang in _SYMBOL_LANGS:
            mod = _extract_module(rel, lang, text)
            if mod is not None:
                modules.append(mod)

    # 5. Framework detection. The detector wants a callable that returns
    #    file content; we serve from the fresh-content map first, falling
    #    back to disk for cached files.
    file_paths = [fe.path for fe in files]

    def _content_reader(rel_path: str) -> str:
        if rel_path in fresh_content:
            return fresh_content[rel_path]
        try:
            return _read_text(root_resolved / rel_path)
        except OSError:
            return ""

    framework_hints = frameworks.detect(
        root=root_resolved,
        manifest_contents=manifest_contents,
        file_paths=file_paths,
        file_reader=_content_reader,
    )
    app_class = frameworks.derive_app_class(framework_hints)

    elapsed_ms = (time.perf_counter_ns() - started_ns) // 1_000_000

    summary = CodebaseSummary(
        root=str(root_resolved),
        scanned_at=datetime.now(timezone.utc).isoformat(),
        file_count=len(files),
        truncated=truncated,
        files=files,
        languages=languages,
        frameworks=framework_hints,
        modules=modules,
        deps_manifests=manifest_contents,
        app_class_hint=app_class,
        last_scan_stats=ScanStats(
            files_walked=len(walked_paths),
            files_parsed_fresh=files_parsed_fresh,
            files_parsed_from_cache=files_parsed_from_cache,
            elapsed_ms=elapsed_ms,
        ),
    )

    # 6. Persist cache (best-effort).
    if cache_path is not None:
        try:
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            cache_path.write_text(
                summary.model_dump_json(indent=2), encoding="utf-8"
            )
        except OSError:
            pass

    return summary


# ---- Helpers ----------------------------------------------------------------


def _load_gitignore(root: Path) -> pathspec.PathSpec:
    patterns: list[str] = []
    gi = root / ".gitignore"
    if gi.exists():
        try:
            patterns = gi.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            patterns = []
    return pathspec.PathSpec.from_lines("gitignore", patterns)


def _walk(root: Path, spec: pathspec.PathSpec):
    """Yield absolute Path objects under `root`, gitignore + hard-skip filtered.

    Implemented as iterative DFS to give predictable order and let us prune
    directory subtrees cheaply.
    """
    stack: list[Path] = [root]
    while stack:
        current = stack.pop()
        try:
            entries = list(current.iterdir())
        except OSError:
            continue
        # Sort for deterministic test output.
        entries.sort(key=lambda p: p.name)
        for entry in entries:
            name = entry.name
            try:
                rel = entry.relative_to(root).as_posix()
            except ValueError:
                continue
            if entry.is_dir():
                if name in _HARD_SKIP_DIRS:
                    continue
                if spec.match_file(rel + "/") or spec.match_file(rel):
                    continue
                stack.append(entry)
            elif entry.is_file():
                if spec.match_file(rel):
                    continue
                yield entry


def _read_text(path: Path) -> str:
    try:
        with path.open("r", encoding="utf-8", errors="replace") as f:
            return f.read()
    except OSError:
        return ""


def _role_for(rel_path: str) -> str:
    parts = rel_path.split("/")
    name = parts[-1]
    # Test files
    if any(seg in {"tests", "test", "__tests__"} for seg in parts):
        return "test"
    if name.startswith("test_") or name.endswith("_test.py") or name.endswith(".test.ts"):
        return "test"
    # Build / generated
    if any(seg in {"build", "dist", "target", ".dart_tool"} for seg in parts):
        return "build"
    # Documentation
    if name.lower() in {"readme.md", "license", "notice", "changelog"}:
        return "doc"
    if name.endswith(".md") or name.endswith(".rst"):
        return "doc"
    # Config (root-level manifests + dotfiles)
    if name in _MANIFEST_NAMES or name.startswith("."):
        return "config"
    if name.endswith((".toml", ".yaml", ".yml", ".ini", ".cfg")):
        return "config"
    # Source — anything under lib/ or src/ or with a known source extension
    if any(seg in {"lib", "src", "app"} for seg in parts):
        return "source"
    ext = "." + name.rsplit(".", 1)[-1].lower() if "." in name else ""
    if ext in _LANG_BY_EXT and _LANG_BY_EXT[ext] in {
        "python", "dart", "typescript", "javascript", "go", "rust", "java",
        "kotlin", "swift", "ruby", "csharp", "cpp", "c",
    }:
        return "source"
    return None  # unknown


def _extract_module(rel_path: str, lang: str, text: str) -> ModuleSymbols | None:
    if lang == "python":
        names, imports = _extract_python(text)
    elif lang == "dart":
        names, imports = _extract_dart(text)
    elif lang in {"typescript", "javascript"}:
        names, imports = _extract_ts_js(text)
    else:
        return None
    if not names and not imports:
        return None
    return ModuleSymbols(path=rel_path, public_names=names, imports=imports)


def _extract_python(text: str) -> tuple[list[str], list[str]]:
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return ([], [])
    names: list[str] = []
    imports: list[str] = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if not node.name.startswith("_"):
                names.append(node.name)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                imports.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imports.append(node.module)
    return (names, imports)


_DART_TYPE_RE = re.compile(
    r"^(?:abstract\s+)?(?:class|enum|mixin|extension)\s+(\w+)",
    re.MULTILINE,
)
# Top-level Dart functions: optional return type, function name, paren list,
# then `=>` or `{`. Excludes lines starting with whitespace (those are methods).
_DART_FUNC_RE = re.compile(
    r"^(?:[\w<>?,\s]+\s+)?(\w+)\s*\([^)]*\)\s*(?:async\s*)?(?:=>|\{)",
    re.MULTILINE,
)
_DART_IMPORT_RE = re.compile(r"""^\s*import\s+['"]([^'"]+)['"]""", re.MULTILINE)


def _extract_dart(text: str) -> tuple[list[str], list[str]]:
    names: list[str] = []
    seen: set[str] = set()
    for m in _DART_TYPE_RE.finditer(text):
        n = m.group(1)
        if n not in seen:
            seen.add(n)
            names.append(n)
    for m in _DART_FUNC_RE.finditer(text):
        n = m.group(1)
        if n[0].isupper():
            continue  # constructor / type call false-positive
        if n.startswith("_"):
            continue
        if n in {"if", "for", "while", "switch", "return", "main"}:
            if n != "main":
                continue
        if n not in seen:
            seen.add(n)
            names.append(n)
    imports = [m.group(1) for m in _DART_IMPORT_RE.finditer(text)]
    return (names, imports)


_TS_EXPORT_RE = re.compile(
    r"^export\s+(?:default\s+)?(?:async\s+)?"
    r"(?:class|function|const|let|var|interface|type|enum)\s+(\w+)",
    re.MULTILINE,
)
_TS_IMPORT_RE = re.compile(
    r"""^\s*import\s+(?:[^'"]+\s+from\s+)?['"]([^'"]+)['"]""", re.MULTILINE
)


def _extract_ts_js(text: str) -> tuple[list[str], list[str]]:
    names = [m.group(1) for m in _TS_EXPORT_RE.finditer(text)]
    imports = [m.group(1) for m in _TS_IMPORT_RE.finditer(text)]
    return (names, imports)


# ---- read_related ----------------------------------------------------------


def read_related(
    summary: CodebaseSummary,
    root: Path,
    module_scope: list[str] | str,
    task_description: str,
    max_total_bytes: int = _DEFAULT_RELATED_BYTES,
) -> dict[str, str]:
    """Return a budgeted map of {posix_path: file_content} for Worker prompts.

    Selection is a triage, not a complete read. Three signals contribute to
    a per-file score:

      * Direct match — file path lies under any path in `module_scope`.
      * Description match — file's module exports a public name that appears
        as a token in `task_description` (CamelCase identifiers in
        TR/EN free text).
      * Import-graph 1-hop — file is imported by a direct-match file (Dart
        relative paths and Python dotted modules are resolved).

    Files with empty sha1 (large/binary) or that no longer exist on disk
    are filtered with a near-infinite penalty. After scoring, candidates
    are filled greedily until `max_total_bytes` is exhausted.

    `module_scope` accepts a list (M2 schema) or a single string (M1 schema)
    — internally normalized to a list.
    """
    scope = [module_scope] if isinstance(module_scope, str) else list(module_scope)
    scope = [s.strip("/") for s in scope if s.strip("/")]

    file_by_path = {fe.path: fe for fe in summary.files}
    module_by_path = {ms.path: ms for ms in summary.modules}
    all_paths = set(file_by_path)

    # Direct matches first — these seed the description/import sets.
    direct: set[str] = set()
    for path in all_paths:
        if any(_under_scope(path, s) for s in scope):
            direct.add(path)

    described = _description_matches(task_description, summary.modules)
    neighbors = _import_neighbors(direct, module_by_path, all_paths)

    # Score every file in the union of (direct ∪ described ∪ neighbors).
    candidates = direct | described | neighbors
    scored: list[tuple[int, str]] = []  # (score, path), highest first
    for path in candidates:
        fe = file_by_path.get(path)
        if fe is None:
            continue
        score = 0
        if path in direct:
            score += _W_DIRECT_MATCH
        if path in described:
            score += _W_DESCRIPTION_MATCH
        if path in neighbors:
            score += _W_IMPORT_NEIGHBOR

        # Size penalty: -10 per 1KB, rounded.
        score -= (fe.size_bytes // 1024) * _W_SIZE_PENALTY_PER_KB

        # Stale: file dropped off disk since last scan, or content was never
        # captured (large/binary). Either way: not safe to ship.
        abs_path = root / path
        if not fe.sha1 or not abs_path.exists():
            score -= _W_STALE_PENALTY

        scored.append((score, path))

    scored.sort(key=lambda pair: (-pair[0], pair[1]))

    # Greedy fill under the byte budget. We re-read content from disk
    # (the cache holds metadata only). Files that fail to read are skipped.
    out: dict[str, str] = {}
    used_bytes = 0
    for score, path in scored:
        if score <= -_W_STALE_PENALTY // 2:  # eliminated by stale or huge size
            continue
        try:
            text = (root / path).read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        encoded_size = len(text.encode("utf-8"))
        if used_bytes + encoded_size > max_total_bytes:
            continue  # skip this one; later smaller files may still fit
        out[path] = text
        used_bytes += encoded_size

    return out


def _under_scope(path: str, scope: str) -> bool:
    """True if `path` is the same as `scope` or lives under `scope/`."""
    if path == scope:
        return True
    return path.startswith(scope + "/")


# CamelCase identifiers found in free text — these are the description tokens
# we cross-reference against module public_names.
_IDENT_RE = re.compile(r"\b[A-Z][A-Za-z0-9]+\b")


def _description_matches(
    task_description: str,
    modules: list[ModuleSymbols],
) -> set[str]:
    """Return module paths whose public_names appear as tokens in the description."""
    if not task_description:
        return set()
    tokens = set(_IDENT_RE.findall(task_description))
    if not tokens:
        return set()
    matched: set[str] = set()
    for mod in modules:
        if any(name in tokens for name in mod.public_names):
            matched.add(mod.path)
    return matched


def _import_neighbors(
    direct_paths: set[str],
    module_by_path: dict[str, ModuleSymbols],
    all_paths: set[str],
) -> set[str]:
    """Resolve each direct-match file's imports to other files in the summary."""
    neighbors: set[str] = set()
    for src in direct_paths:
        mod = module_by_path.get(src)
        if mod is None:
            continue
        for imp in mod.imports:
            resolved = _resolve_import(src, imp, all_paths)
            if resolved and resolved != src:
                neighbors.add(resolved)
    return neighbors - direct_paths


def _resolve_import(
    file_path: str,
    import_str: str,
    all_paths: set[str],
) -> str | None:
    """Resolve an import string to a file in `all_paths`, or None.

    Handles three common cases:

      * Dart relative imports: `'foo_controller.dart'` from
        `lib/features/foo/foo_page.dart` → `lib/features/foo/foo_controller.dart`.
      * Dart project package imports: `package:my_app/x/y.dart` → `lib/x/y.dart`
        (best-effort; we don't read pubspec.yaml's package name, we just try
        `lib/<rest>`).
      * Python dotted modules: `runtime.executor.worker` → `runtime/executor/worker.py`.

    External package imports (`package:flutter/material.dart`,
    `dart:async`, third-party Python packages) return None.
    """
    if not import_str:
        return None

    # Dart `package:` imports — only project-internal `lib/` ones useful.
    if import_str.startswith("package:"):
        rest = import_str[len("package:") :]
        # `package:my_app/foo/bar.dart` → strip the package name, prefix with lib/
        if "/" in rest:
            after_pkg = rest.split("/", 1)[1]
            candidate = "lib/" + after_pkg
            if candidate in all_paths:
                return candidate
        return None

    # Dart `dart:` core libraries — never local.
    if import_str.startswith("dart:"):
        return None

    # Dart relative imports (end in .dart, may contain `../`).
    if import_str.endswith(".dart"):
        base = file_path.rsplit("/", 1)[0] if "/" in file_path else ""
        candidate = _normalize_relative(base, import_str)
        if candidate in all_paths:
            return candidate
        return None

    # Python dotted form. Heuristic: contains `.`, no `/`, no extension.
    if "." in import_str and "/" not in import_str:
        candidate = import_str.replace(".", "/") + ".py"
        if candidate in all_paths:
            return candidate
        # Package import: try `<dotted>/__init__.py`
        pkg = import_str.replace(".", "/") + "/__init__.py"
        if pkg in all_paths:
            return pkg
        return None

    # JS/TS relative imports (`./foo`, `../bar/baz`) — extension may be omitted.
    if import_str.startswith(("./", "../")):
        base = file_path.rsplit("/", 1)[0] if "/" in file_path else ""
        for ext in (".ts", ".tsx", ".js", ".jsx", ".mjs", "/index.ts", "/index.js"):
            candidate = _normalize_relative(base, import_str + ext)
            if candidate in all_paths:
                return candidate

    return None


def _normalize_relative(base: str, ref: str) -> str:
    """Resolve a POSIX-relative import path against a base directory."""
    parts = (base.split("/") if base else []) + ref.split("/")
    out: list[str] = []
    for part in parts:
        if part in ("", "."):
            continue
        if part == "..":
            if out:
                out.pop()
            continue
        out.append(part)
    return "/".join(out)
