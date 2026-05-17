"""Item 45 empirical determinism check.

Runs Architect.extract_inputs() N times against the v4 baseline PRD
(single-user browser todo) and reports the variance across runs.

Decision rule for Item 45 closure:
- All N runs produce identical `expected_scale`, `team_size`, `ops_capacity` =
  ("small", "solo", "low") → fix works, Item 45 closes without RAG.
- Any run produces "unknown" for those fields → fix didn't fully address the
  drift; M5 RAG value claim retains weight.

One-off script. Not part of the test suite (would burn $ on every pytest run).
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from dotenv import load_dotenv  # noqa: E402
load_dotenv(REPO_ROOT / ".env")

from ortim.agents.architect import ArchitectAgent  # noqa: E402
from ortim.audit import AuditLogger  # noqa: E402
from ortim.llm.router import client_for  # noqa: E402
from ortim.memory import MemoryLoader  # noqa: E402

N = 5
PRD_PATH = REPO_ROOT / "workspaces" / "66244246c339" / "PRD.md"


def main() -> int:
    prd = PRD_PATH.read_text(encoding="utf-8")

    audit_dir = tempfile.mkdtemp(prefix="item45-empirical-")
    audit = AuditLogger(path=Path(audit_dir) / "audit.jsonl")
    memory = MemoryLoader(REPO_ROOT)
    llm = client_for("architect")
    agent = ArchitectAgent(llm, memory, audit)

    results = []
    for i in range(N):
        print(f"  call {i + 1}/{N} ... ", end="", flush=True)
        try:
            inputs = agent.extract_inputs(
                prd_markdown=prd,
                project_id=f"item45-empirical-{i}",
                codebase=None,
            )
            d = inputs.model_dump()
            scale = d.get("expected_scale")
            team = d.get("team_size")
            ops = d.get("ops_capacity")
            results.append((scale, team, ops, d))
            print(f"scale={scale!r}, team={team!r}, ops={ops!r}")
        except Exception as e:
            results.append(("ERROR", str(e), None, {}))
            print(f"ERROR: {e}")

    print("\nSummary:")
    triples = [(r[0], r[1], r[2]) for r in results]
    canonical = ("small", "solo", "low")
    canonical_count = triples.count(canonical)
    distinct = len(set(triples))

    print(f"  canonical (small/solo/low): {canonical_count}/{N}")
    print(f"  distinct triple combinations: {distinct}")
    for triple in sorted(set(triples)):
        count = triples.count(triple)
        marker = " ✓" if triple == canonical else ""
        print(f"    {triple!r}: {count}{marker}")

    # Decision
    print()
    if canonical_count == N:
        print("DECISION: Item 45 prompt fix WORKS — all runs deterministic + correct.")
        return 0
    elif canonical_count >= N - 1:
        print(f"DECISION: PARTIAL — {canonical_count}/{N} canonical. Marginal improvement.")
        return 1
    else:
        print(f"DECISION: Item 45 prompt fix INSUFFICIENT — only {canonical_count}/{N} canonical.")
        return 2


if __name__ == "__main__":
    sys.exit(main())
