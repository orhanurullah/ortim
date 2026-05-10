# SPDX-License-Identifier: FSL-1.1-Apache-2.0
# Copyright (c) 2026 ortim.dev
"""Insert SPDX license headers into all Python source files under given roots.

Idempotent: if a file already has an `SPDX-License-Identifier` line in its
first 5 lines, it is skipped. Otherwise the header is prepended preserving
any leading shebang or encoding declaration.

Usage (from repo root):

    python scripts/add_spdx_headers.py runtime tests scripts

Or with no args, defaults to: runtime, tests, scripts.
"""

from __future__ import annotations

import sys
from pathlib import Path

CORE_HEADER = (
    "# SPDX-License-Identifier: FSL-1.1-Apache-2.0\n"
    "# Copyright (c) 2026 ortim.dev\n"
)
COMMERCIAL_HEADER = (
    "# SPDX-License-Identifier: LicenseRef-Commercial\n"
    "# Copyright (c) 2026 ortim.dev. All rights reserved.\n"
)


def header_for(path: Path) -> str:
    parts = path.parts
    if "enterprise" in parts:
        return COMMERCIAL_HEADER
    return CORE_HEADER


def already_has_header(text: str) -> bool:
    head = "\n".join(text.splitlines()[:5])
    return "SPDX-License-Identifier" in head


def insert_header(text: str, header: str) -> str:
    """Prepend `header` while preserving shebang and encoding cookie lines."""
    lines = text.splitlines(keepends=True)
    insert_at = 0
    if lines and lines[0].startswith("#!"):
        insert_at = 1
    if (
        len(lines) > insert_at
        and lines[insert_at].startswith("#")
        and ("coding" in lines[insert_at] or "encoding" in lines[insert_at])
    ):
        insert_at += 1
    return "".join(lines[:insert_at]) + header + "".join(lines[insert_at:])


def process_file(path: Path) -> bool:
    text = path.read_text(encoding="utf-8")
    if already_has_header(text):
        return False
    new_text = insert_header(text, header_for(path))
    path.write_text(new_text, encoding="utf-8")
    return True


def main(roots: list[str]) -> int:
    if not roots:
        roots = ["runtime", "tests", "scripts"]
    repo_root = Path(__file__).resolve().parent.parent
    total = 0
    modified = 0
    for root_name in roots:
        root = repo_root / root_name
        if not root.exists():
            print(f"skip: {root} does not exist")
            continue
        for py_file in sorted(root.rglob("*.py")):
            total += 1
            if process_file(py_file):
                modified += 1
                print(f"  added: {py_file.relative_to(repo_root)}")
    print(f"\nProcessed {total} file(s); modified {modified}.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
