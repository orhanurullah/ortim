# SPDX-License-Identifier: FSL-1.1-Apache-2.0
# Copyright (c) 2026 ortim.dev
"""Idempotent appender for PRD.md / RFC.md extension sections.

The ExtenderAgent emits one markdown section per cycle. The runtime
writes those to the existing PRD.md / RFC.md by APPEND-ONLY (never
rewrites the original). Idempotency: a second call with the same cycle
detects the existing `## Extension <N>` header and is a no-op.
"""

from __future__ import annotations

import re
from pathlib import Path

# Header pattern accepts variant forms produced by the LLM:
#   ## Extension 1 — Tagging
#   ## Extension 1 - Tagging       (ascii dash)
#   ## Extension 1: Tagging
#   ## Extension 1
# All are anchored on the cycle integer.
_HEADER_RE = re.compile(
    r"^##\s+Extension\s+(\d+)\b",
    re.MULTILINE,
)


class DeltaSectionMalformed(ValueError):
    """The agent's output didn't begin with `## Extension <cycle>`."""


def section_cycles_in(target_text: str) -> list[int]:
    """Return cycle integers of every existing `## Extension N` header in
    the document. Used to detect idempotent re-appends and to render
    `ortim extensions <id>` history."""
    return [int(m.group(1)) for m in _HEADER_RE.finditer(target_text)]


def append_delta_section(
    target: Path,
    section: str,
    cycle: int,
) -> bool:
    """Append `section` to `target`. Returns True if the file was
    written; False if cycle was already present (no-op).

    Validation:
    - `section` must contain a `## Extension <cycle>` header somewhere
      in its first 200 chars (allows leading whitespace / blank lines).
      Mismatched cycle integer raises DeltaSectionMalformed.
    - If `target` already contains `## Extension <cycle>`, returns False.
    - Otherwise appends with a separating blank line if needed.
    """
    head = section.lstrip()[:200]
    match = _HEADER_RE.search(head)
    if match is None:
        raise DeltaSectionMalformed(
            f"section must begin with '## Extension <cycle>' header; "
            f"got first 80 chars: {head[:80]!r}"
        )
    declared = int(match.group(1))
    if declared != cycle:
        raise DeltaSectionMalformed(
            f"section header declares cycle {declared} but caller "
            f"requested cycle {cycle}"
        )

    if not target.exists():
        # Conservative: a missing PRD/RFC during extend is a runtime bug
        # — the user can't extend a project that has no shipped PRD/RFC.
        # The CLI layer should prevent this; if we still get here, fail
        # loudly rather than silently creating a stub.
        raise FileNotFoundError(
            f"target {target} does not exist; extend cycle requires the "
            f"shipped artifact to be present"
        )

    existing = target.read_text(encoding="utf-8")
    if cycle in section_cycles_in(existing):
        return False

    sep = "\n\n" if not existing.endswith("\n\n") else ""
    if existing and not existing.endswith("\n"):
        sep = "\n\n"
    target.write_text(existing + sep + section.rstrip() + "\n", encoding="utf-8")
    return True
