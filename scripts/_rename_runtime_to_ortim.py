"""R2 helper: rename `runtime.*` references to `ortim.*` across the codebase.

Safe scope:
  - .py files: import statements + string-based module paths (monkeypatch etc.)
  - selected .md files: README + agents/architect.md (current code paths)

Excluded (historical / planning):
  - tespit.md, M*-plan.md, M*-design.md, M5-premortem.md
  - docs/plans/*, docs/backlog.md, 16-05-2026_app-state.md
  - any dir under .venv / .pytest_cache / *.egg-info / __pycache__ / .worktrees
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

PY_PATTERNS = [
    (re.compile(r"\bfrom runtime(\.|\s)"), r"from ortim\1"),
    (re.compile(r"\bfrom runtime$", re.MULTILINE), "from ortim"),
    (re.compile(r"\bimport runtime(\.|\s)"), r"import ortim\1"),
    (re.compile(r"\bimport runtime$", re.MULTILINE), "import ortim"),
    # Module-path references in docstrings/comments/quoted strings.
    # Only when followed by an identifier char (to avoid matching the English
    # word "runtime." at end of sentence).
    (re.compile(r"\bruntime\.(?=[a-zA-Z_])"), "ortim."),
    # Path references in docstrings (e.g., `ortim/executor/worker.py`).
    (re.compile(r"\bruntime/"), "ortim/"),
]

MD_PATTERNS = [
    (re.compile(r"\bruntime/"), "ortim/"),
    (re.compile(r"\bruntime\."), "ortim."),
]

EXCLUDE_DIR_NAMES = {
    ".venv",
    ".pytest_cache",
    "__pycache__",
    ".worktrees",
    ".git",
    "node_modules",
    "workspaces",
}

MD_ALLOWLIST = {
    "README.md",
    "agents/architect.md",
}


def is_excluded(path: Path) -> bool:
    parts = path.relative_to(ROOT).parts
    if any(p in EXCLUDE_DIR_NAMES for p in parts):
        return True
    if any(p.endswith(".egg-info") for p in parts):
        return True
    return False


def apply_patterns(text: str, patterns: list[tuple[re.Pattern[str], str]]) -> tuple[str, int]:
    new_text = text
    total = 0
    for rx, repl in patterns:
        new_text, n = rx.subn(repl, new_text)
        total += n
    return new_text, total


def process_py_files() -> dict[Path, int]:
    changed: dict[Path, int] = {}
    for path in ROOT.rglob("*.py"):
        if is_excluded(path):
            continue
        text = path.read_text(encoding="utf-8")
        new_text, n = apply_patterns(text, PY_PATTERNS)
        if n > 0 and new_text != text:
            path.write_text(new_text, encoding="utf-8", newline="\n")
            changed[path.relative_to(ROOT)] = n
    return changed


def process_md_files() -> dict[Path, int]:
    changed: dict[Path, int] = {}
    for rel in MD_ALLOWLIST:
        path = ROOT / rel
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8")
        new_text, n = apply_patterns(text, MD_PATTERNS)
        if n > 0 and new_text != text:
            path.write_text(new_text, encoding="utf-8", newline="\n")
            changed[path.relative_to(ROOT)] = n
    return changed


def main() -> int:
    print("=== .py file replacement ===")
    py_changed = process_py_files()
    for p, n in sorted(py_changed.items()):
        print(f"  {p}: {n} replacement(s)")
    print(f"Total py files changed: {len(py_changed)} / total replacements: {sum(py_changed.values())}")

    print("\n=== .md file replacement (allowlist) ===")
    md_changed = process_md_files()
    for p, n in sorted(md_changed.items()):
        print(f"  {p}: {n} replacement(s)")
    print(f"Total md files changed: {len(md_changed)} / total replacements: {sum(md_changed.values())}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
