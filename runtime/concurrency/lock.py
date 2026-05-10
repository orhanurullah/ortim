# SPDX-License-Identifier: FSL-1.1-Apache-2.0
# Copyright (c) 2026 ortim.dev
"""File-based mutex via mkdir atomicity.

mkdir is atomic on every mainstream filesystem (NTFS, ext4, APFS) — if two
processes race, exactly one succeeds and the other gets FileExistsError.
This avoids the OS-specific gymnastics of file-based O_EXCL on Windows.

Used to protect per-workspace operations: state.json writes, task DAG
generation, parallel worker dispatch.
"""

from __future__ import annotations

import os
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


class LockTimeout(Exception):
    pass


@contextmanager
def file_lock(
    target: Path,
    timeout: float = 30.0,
    poll_interval: float = 0.1,
) -> Iterator[None]:
    """Acquire an exclusive lock on `target` (creates `<target>.lock` directory).

    Raises LockTimeout if not acquired within `timeout` seconds.
    Stale locks (older than 2x timeout) are forcibly removed — best-effort
    crash recovery.
    """
    lock_dir = target.parent / f"{target.name}.lock"
    lock_dir.parent.mkdir(parents=True, exist_ok=True)

    deadline = time.time() + timeout
    while True:
        try:
            lock_dir.mkdir()
            break
        except FileExistsError:
            if _is_stale(lock_dir, timeout * 2):
                _force_remove(lock_dir)
                continue
            if time.time() >= deadline:
                raise LockTimeout(f"Could not acquire {lock_dir} within {timeout}s")
            time.sleep(poll_interval)

    pid_file = lock_dir / "pid"
    try:
        pid_file.write_text(str(os.getpid()), encoding="utf-8")
        yield
    finally:
        _force_remove(lock_dir)


def _is_stale(lock_dir: Path, max_age_seconds: float) -> bool:
    try:
        mtime = lock_dir.stat().st_mtime
    except FileNotFoundError:
        return False
    return (time.time() - mtime) > max_age_seconds


def _force_remove(lock_dir: Path) -> None:
    try:
        for child in lock_dir.iterdir():
            try:
                child.unlink()
            except FileNotFoundError:
                pass
        lock_dir.rmdir()
    except FileNotFoundError:
        pass
    except OSError:
        # On Windows, rmdir can race; best-effort
        pass
