# SPDX-License-Identifier: FSL-1.1-Apache-2.0
# Copyright (c) 2026 ortim.dev
"""Hash-chain tamper-evidence tests for the audit log."""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from runtime.audit import (  # noqa: E402
    GENESIS_HASH,
    AuditLogger,
    event_hash,
    verify_chain,
)


def test_chain_built_correctly() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "audit.jsonl"
        logger = AuditLogger(path=path)
        logger.log("intake_evt_a", project_id="p", value=1)
        logger.log("intake_evt_b", project_id="p", value=2)
        logger.log("intake_evt_c", project_id="p", value=3)

        lines = path.read_text(encoding="utf-8").splitlines()
        recs = [json.loads(line) for line in lines]
        # First event chains to genesis
        assert recs[0]["prev_hash"] == GENESIS_HASH
        # Each subsequent event chains to the previous event's hash
        for i in range(1, len(recs)):
            assert recs[i]["prev_hash"] == event_hash(recs[i - 1])


def test_verify_chain_intact() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "audit.jsonl"
        logger = AuditLogger(path=path)
        for i in range(5):
            logger.log("worker_step", project_id="p", task_id=f"T-{i}")
        result = verify_chain(path)
        assert result.ok, f"Expected intact chain; got {result}"
        assert result.total_events == 5


def test_verify_detects_tampering() -> None:
    """Edit one event's payload; the next event's prev_hash no longer matches."""
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "audit.jsonl"
        logger = AuditLogger(path=path)
        logger.log("worker_step", project_id="p", task_id="T-1", value=10)
        logger.log("worker_step", project_id="p", task_id="T-2", value=20)
        logger.log("worker_step", project_id="p", task_id="T-3", value=30)

        # Tamper: swap T-1's value from 10 to 999
        lines = path.read_text(encoding="utf-8").splitlines()
        first = json.loads(lines[0])
        first["value"] = 999
        lines[0] = json.dumps(first, ensure_ascii=False)
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")

        result = verify_chain(path)
        assert not result.ok, "Tampering should have been detected"
        assert result.broken_at_line == 2, (
            f"Expected break at line 2 (next event's prev_hash mismatch), "
            f"got {result.broken_at_line}; reason: {result.reason}"
        )


if __name__ == "__main__":
    tests = [
        test_chain_built_correctly,
        test_verify_chain_intact,
        test_verify_detects_tampering,
    ]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"PASS  {t.__name__}")
        except Exception as e:
            failed += 1
            print(f"FAIL  {t.__name__}: {e}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
