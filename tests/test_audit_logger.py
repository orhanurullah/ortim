# SPDX-License-Identifier: FSL-1.1-Apache-2.0
# Copyright (c) 2026 ortim.dev
"""Smoke tests for AuditLogger — focuses on JSONL integrity under concurrent writes."""

from __future__ import annotations

import json
import sys
import tempfile
import threading
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from runtime.audit import AuditLogger  # noqa: E402


def test_basic_log_writes_valid_jsonl() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "audit.jsonl"
        logger = AuditLogger(path=path)
        logger.log("evt_a", project_id="p", value=1)
        logger.log("evt_b", project_id="p", value=2)

        lines = path.read_text(encoding="utf-8").splitlines()
        assert len(lines) == 2
        rec0 = json.loads(lines[0])
        assert rec0["event"] == "evt_a" and rec0["value"] == 1
        rec1 = json.loads(lines[1])
        assert rec1["event"] == "evt_b" and rec1["value"] == 2


def test_concurrent_writes_produce_intact_lines() -> None:
    """Many threads logging in parallel — every line must be valid JSON.

    Without the per-instance write lock, interleaved writes on Windows
    can corrupt records (partial line + another thread's prefix).
    """
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "audit.jsonl"
        logger = AuditLogger(path=path)

        thread_count = 8
        per_thread = 50

        def worker(tid: int) -> None:
            for j in range(per_thread):
                logger.log(
                    "stress",
                    thread_id=tid,
                    seq=j,
                    payload="x" * 200,
                )

        threads = [
            threading.Thread(target=worker, args=(i,)) for i in range(thread_count)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)

        lines = path.read_text(encoding="utf-8").splitlines()
        assert len(lines) == thread_count * per_thread, (
            f"Expected {thread_count * per_thread} lines, got {len(lines)}"
        )
        seen: set[tuple[int, int]] = set()
        for line in lines:
            rec = json.loads(line)  # raises if any line is corrupt
            assert rec["event"] == "stress"
            seen.add((rec["thread_id"], rec["seq"]))
        assert len(seen) == thread_count * per_thread


if __name__ == "__main__":
    tests = [
        test_basic_log_writes_valid_jsonl,
        test_concurrent_writes_produce_intact_lines,
    ]
    failed = 0
    for test in tests:
        try:
            test()
            print(f"PASS  {test.__name__}")
        except Exception as e:
            failed += 1
            print(f"FAIL  {test.__name__}: {e}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
