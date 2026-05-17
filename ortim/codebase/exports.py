# SPDX-License-Identifier: FSL-1.1-Apache-2.0
# Copyright (c) 2026 ortim.dev
"""Export-shape extraction for the M4 cross-task visibility layer.

The brownfield reader already extracts top-level public *names* (see
`reader._extract_ts_js`, `_extract_python_symbols`, etc.) into
`ModuleSymbols` for `read_related`. M4 needs more: a Worker writing
task T-N must see **signatures** of prior tasks' exports so it can
write a correct import — names alone don't reveal that `task-service`
exposes a factory `createTaskService(db)` rather than bare CRUD
functions.

This module produces `ExportSignature` records keyed by file, designed
for prompt injection rather than analysis. Regex-based for TS/TSX/JS;
`ast`-based for Python. Other languages return `[]` — adding them is
mechanical.
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass
from pathlib import Path

_TS_EXTS = frozenset({".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs"})
_PY_EXTS = frozenset({".py"})


@dataclass(frozen=True)
class ExportSignature:
    """One exported symbol's prompt-ready summary.

    `signature` is the one-line text the Worker actually sees; the Worker
    is expected to mirror its shape when writing imports. `kind` lets
    the renderer group exports by category (functions before types,
    etc.) and lets future readers query the surface programmatically.
    """

    kind: str
    """One of: function, class, interface, type, const, default,
    re_export. Free-form — not a Literal — so adding a language later
    can introduce new kinds without breaking pydantic-style validation."""

    name: str
    """Symbol name. `"default"` when `export default` was anonymous."""

    signature: str
    """Single-line, ≤ 200 chars. Trailing `{` or `;` stripped."""


# ---- TS / TSX / JS extraction --------------------------------------------

# Lines we capture, with the symbol name as group(1). The regex is
# intentionally permissive — we DON'T try to parse TypeScript, just to
# find the first line of each export. We then carry that whole line over
# to the signature.
_TS_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    (
        "function",
        re.compile(
            r"^\s*export\s+(?:default\s+)?(?:async\s+)?function\s*\*?\s*(\w+)",
            re.MULTILINE,
        ),
    ),
    (
        "class",
        re.compile(
            r"^\s*export\s+(?:default\s+)?(?:abstract\s+)?class\s+(\w+)",
            re.MULTILINE,
        ),
    ),
    (
        "interface",
        re.compile(r"^\s*export\s+interface\s+(\w+)", re.MULTILINE),
    ),
    (
        "type",
        re.compile(r"^\s*export\s+type\s+(\w+)", re.MULTILINE),
    ),
    (
        "const",
        re.compile(
            r"^\s*export\s+(?:default\s+)?(?:const|let|var)\s+(\w+)",
            re.MULTILINE,
        ),
    ),
    (
        "enum",
        re.compile(r"^\s*export\s+(?:const\s+)?enum\s+(\w+)", re.MULTILINE),
    ),
]

# `export default <expression>` (no class/function keyword) — e.g.
# `export default TaskForm;` or `export default function () { ... }`.
# Captured separately because the name is the expression after `default`.
_TS_DEFAULT_RE = re.compile(
    r"^\s*export\s+default\s+(?!(?:async\s+)?function|class|interface|type|const|let|var|enum)(\w+)",
    re.MULTILINE,
)

# `export { foo, bar as baz } [from '...']` — surface as `re_export`.
_TS_REEXPORT_RE = re.compile(
    r"^\s*export\s+\{([^}]+)\}\s*(?:from\s+['\"][^'\"]+['\"])?\s*;?",
    re.MULTILINE,
)


def _extract_ts(source: str) -> list[ExportSignature]:
    out: list[ExportSignature] = []
    seen_names: set[str] = set()

    for kind, pattern in _TS_PATTERNS:
        for match in pattern.finditer(source):
            name = match.group(1)
            if name in seen_names:
                continue
            seen_names.add(name)
            line = _capture_signature_line(source, match.start())
            out.append(
                ExportSignature(kind=kind, name=name, signature=line)
            )

    for match in _TS_DEFAULT_RE.finditer(source):
        name = match.group(1)
        seen_names.add(name)
        line = _capture_signature_line(source, match.start())
        out.append(ExportSignature(kind="default", name=name, signature=line))

    for match in _TS_REEXPORT_RE.finditer(source):
        body = match.group(1).strip()
        for spec in body.split(","):
            spec = spec.strip()
            if not spec:
                continue
            # `foo as bar` → exported name is `bar`; `foo` → `foo`.
            parts = spec.split(" as ")
            name = parts[-1].strip()
            if name and name not in seen_names:
                seen_names.add(name)
                out.append(
                    ExportSignature(
                        kind="re_export",
                        name=name,
                        signature=f"export {{ {spec} }}",
                    )
                )

    return out


def _capture_signature_line(source: str, start: int) -> str:
    """Return the export line trimmed to one logical signature.

    We extend until the function body opener `{` (or `=>`, `;`,
    end-of-line) so multi-line function declarations and destructured
    parameter lists produce a useful signature. Cap at 200 chars to
    keep prompts bounded.

    Destructured parameters like `function foo({ bar }: BarProps) { ... }`
    contain a `{...}` inside the param list — we balance paren depth
    so the body opener isn't confused with the destructure's inner
    brace.
    """
    # The regex's `\s*` may greedily consume the preceding `\n`, so
    # `start` can point at whitespace rather than the actual `export`
    # keyword. Walk forward to skip leading whitespace, then back up to
    # the start of that line.
    n = len(source)
    while start < n and source[start] in (" ", "\t", "\n", "\r"):
        start += 1
    line_start = source.rfind("\n", 0, start) + 1
    # Walk forward up to 200 chars, tracking paren / bracket depth so
    # we only break on a `{` at depth 0 (the function body opener).
    end = line_start
    max_end = min(line_start + 200, len(source))
    paren_depth = 0
    bracket_depth = 0
    angle_depth = 0
    while end < max_end:
        ch = source[end]
        if ch == "(":
            paren_depth += 1
        elif ch == ")":
            paren_depth = max(0, paren_depth - 1)
        elif ch == "[":
            bracket_depth += 1
        elif ch == "]":
            bracket_depth = max(0, bracket_depth - 1)
        elif ch == "<":
            # Generic type param — `function foo<T extends X>(...)`.
            # Treat as a bracket. The regex may have caught us mid-token,
            # so we only count `<` when followed by a letter or `extends`.
            if end + 1 < max_end and source[end + 1].isalpha():
                angle_depth += 1
        elif ch == ">":
            angle_depth = max(0, angle_depth - 1)
        elif ch == "{":
            if paren_depth == 0 and bracket_depth == 0:
                # Top-level `{` — function body, class body, interface
                # opener, or object literal start. Stop.
                break
            # Otherwise a destructure / nested literal — keep walking.
        elif ch == ";":
            break
        elif ch == "\n":
            # Multi-line function signatures may break naturally. Peek
            # the next char to see if the signature continues.
            if (
                paren_depth > 0
                or bracket_depth > 0
                or angle_depth > 0
                or (end + 1 < max_end and source[end + 1] in (" ", "\t", ")", ","))
            ):
                end += 1
                continue
            break
        end += 1
    line = source[line_start:end].strip()
    if "  " in line:
        # Collapse runs of internal whitespace so the rendered block
        # stays compact.
        line = re.sub(r"\s+", " ", line)
    return line[:200]


# ---- Python extraction ----------------------------------------------------


def _extract_python(source: str) -> list[ExportSignature]:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []

    out: list[ExportSignature] = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name.startswith("_"):
                continue
            sig = _python_function_signature(node)
            out.append(
                ExportSignature(kind="function", name=node.name, signature=sig)
            )
        elif isinstance(node, ast.ClassDef):
            if node.name.startswith("_"):
                continue
            bases = ", ".join(_unparse(b) for b in node.bases)
            sig = f"class {node.name}" + (f"({bases})" if bases else "")
            out.append(
                ExportSignature(kind="class", name=node.name, signature=sig)
            )
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and not target.id.startswith("_"):
                    out.append(
                        ExportSignature(
                            kind="const",
                            name=target.id,
                            signature=f"{target.id} = {_unparse(node.value)[:100]}",
                        )
                    )
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            name = node.target.id
            if name.startswith("_"):
                continue
            ann = _unparse(node.annotation)
            value = (
                f" = {_unparse(node.value)[:80]}" if node.value is not None else ""
            )
            out.append(
                ExportSignature(
                    kind="const",
                    name=name,
                    signature=f"{name}: {ann}{value}",
                )
            )
    return out


def _python_function_signature(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    prefix = "async def" if isinstance(node, ast.AsyncFunctionDef) else "def"
    args = _unparse(node.args)
    returns = f" -> {_unparse(node.returns)}" if node.returns is not None else ""
    return f"{prefix} {node.name}({args}){returns}"[:200]


def _unparse(node: ast.AST | None) -> str:
    if node is None:
        return ""
    try:
        return ast.unparse(node)
    except (AttributeError, ValueError):
        return ""


# ---- public API ----------------------------------------------------------


def extract_exports(path: Path, source: str) -> list[ExportSignature]:
    """Dispatch to the per-language extractor. Returns `[]` for files
    in languages we don't yet support — callers can safely ignore them
    without a branch."""
    ext = path.suffix.lower()
    if ext in _TS_EXTS:
        return _extract_ts(source)
    if ext in _PY_EXTS:
        return _extract_python(source)
    return []
