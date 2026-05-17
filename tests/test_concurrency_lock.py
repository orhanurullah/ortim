# SPDX-License-Identifier: FSL-1.1-Apache-2.0
# Copyright (c) 2026 ortim.dev
"""Tests for the file-based mutex."""

from __future__ import annotations

import sys
import tempfile
import threading
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from ortim.concurrency import LockTimeout, file_lock  # noqa: E402


def test_basic_acquire_and_release() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        target = Path(tmp) / "x"
        with file_lock(target, timeout=1.0):
            assert (target.parent / f"{target.name}.lock").exists()
        assert not (target.parent / f"{target.name}.lock").exists()


def test_serialized_holds_block_each_other() -> None:
    """Two sequential lock acquisitions should both succeed."""
    with tempfile.TemporaryDirectory() as tmp:
        target = Path(tmp) / "x"
        with file_lock(target, timeout=1.0):
            pass
        with file_lock(target, timeout=1.0):
            pass


def test_concurrent_lock_blocks_then_succeeds() -> None:
    """While T1 holds the lock, T2 cannot acquire it; once T1 releases, T2 wins."""
    with tempfile.TemporaryDirectory() as tmp:
        target = Path(tmp) / "x"
        events: list[str] = []
        barrier = threading.Event()

        def holder() -> None:
            with file_lock(target, timeout=2.0):
                events.append("T1-acquired")
                barrier.set()
                time.sleep(0.3)
                events.append("T1-releasing")

        def waiter() -> None:
            barrier.wait()
            with file_lock(target, timeout=2.0):
                events.append("T2-acquired")

        t1 = threading.Thread(target=holder)
        t2 = threading.Thread(target=waiter)
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        assert events == ["T1-acquired", "T1-releasing", "T2-acquired"], events


def test_timeout_raises_when_held() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        target = Path(tmp) / "x"
        held = threading.Event()
        release = threading.Event()

        def holder() -> None:
            with file_lock(target, timeout=2.0):
                held.set()
                release.wait()

        t = threading.Thread(target=holder)
        t.start()
        held.wait()
        try:
            with file_lock(target, timeout=0.3, poll_interval=0.05):
                raise AssertionError("should not have acquired")
        except LockTimeout:
            pass
        finally:
            release.set()
            t.join()


def test_lock_is_per_target_path() -> None:
    """Locks on different targets are independent."""
    with tempfile.TemporaryDirectory() as tmp:
        a = Path(tmp) / "a"
        b = Path(tmp) / "b"
        with file_lock(a, timeout=1.0), file_lock(b, timeout=1.0):
            pass


if __name__ == "__main__":
    tests = [
        test_basic_acquire_and_release,
        test_serialized_holds_block_each_other,
        test_concurrent_lock_blocks_then_succeeds,
        test_timeout_raises_when_held,
        test_lock_is_per_target_path,
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
