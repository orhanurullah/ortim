# SPDX-License-Identifier: FSL-1.1-Apache-2.0
# Copyright (c) 2026 ortim.dev
"""Copy a workspace's artifacts into `tests/e2e/fixtures/<name>/`.

Use when adding a new baseline or re-recording an existing one after
an intentional behavior change.

Usage:
    python scripts/record_e2e_fixture.py <workspace-id> [<fixture-name>]

If `<fixture-name>` is omitted, the workspace ID is reused. Re-recording
overwrites the existing fixture in place — commit the diff so future
runs use the new baseline.
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
WORKSPACES = REPO_ROOT / "workspaces"
FIXTURES = REPO_ROOT / "tests" / "e2e" / "fixtures"

ARTIFACTS = (
    "state.json",
    "PRD.md",
    "RFC.md",
    "task_dag.json",
    "task_status.json",
    "stack.json",
    "golden_path_inputs.json",
    "intent.json",
)


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__, file=sys.stderr)
        return 2

    workspace_id = argv[1]
    fixture_name = argv[2] if len(argv) >= 3 else workspace_id

    src = WORKSPACES / workspace_id
    if not src.exists():
        print(f"ERROR: workspace {src} not found", file=sys.stderr)
        return 1

    dst = FIXTURES / fixture_name
    dst.mkdir(parents=True, exist_ok=True)

    copied = []
    skipped = []
    for name in ARTIFACTS:
        sp = src / name
        if sp.exists():
            shutil.copy2(sp, dst / name)
            copied.append(name)
        else:
            skipped.append(name)

    print(f"Recorded {fixture_name} → {dst}")
    print(f"  copied:  {', '.join(copied)}")
    if skipped:
        print(f"  skipped: {', '.join(skipped)} (not present in workspace)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
