# SPDX-License-Identifier: FSL-1.1-Apache-2.0
# Copyright (c) 2026 ortim.dev
"""Tamper-evidence verifier for audit JSONL.

Each event written by `AuditLogger.log` carries a `prev_hash` field whose
value is the SHA-256 of the previous event's canonical JSON (excluding the
`prev_hash` field itself). The first event uses a sentinel of 64 zeros.

If anyone removes, edits, or reorders an event in the JSONL, the chain
breaks at that point and `verify_chain` returns the offending line.

This is *evidence* not *prevention*: a sufficiently determined attacker
with write access can rewrite the entire chain. But for compliance and
post-hoc audit, "we can prove the log was not tampered with after the
fact" is the threat model that matters.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

GENESIS_HASH = "0" * 64


def event_hash(record: dict) -> str:
    """SHA-256 over the canonical JSON of `record` minus its `prev_hash` field.

    Canonicalization: sorted keys, no whitespace, ensure_ascii=False so the
    hash is stable across Python versions and platforms.
    """
    payload = {k: v for k, v in record.items() if k != "prev_hash"}
    canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class VerifyResult:
    ok: bool
    total_events: int
    broken_at_line: int | None = None
    reason: str | None = None


def verify_chain(audit_path: Path) -> VerifyResult:
    """Walk the JSONL, recomputing each event's expected `prev_hash`.

    Returns ok=True if the chain is intact, otherwise points to the first
    line where the expected hash diverged from the recorded `prev_hash`.
    """
    if not audit_path.exists():
        return VerifyResult(ok=True, total_events=0)

    expected_prev = GENESIS_HASH
    line_no = 0
    with audit_path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            line_no += 1
            try:
                record = json.loads(line)
            except json.JSONDecodeError as e:
                return VerifyResult(
                    ok=False,
                    total_events=line_no - 1,
                    broken_at_line=line_no,
                    reason=f"invalid JSON: {e}",
                )
            recorded_prev = record.get("prev_hash")
            if recorded_prev is None:
                return VerifyResult(
                    ok=False,
                    total_events=line_no - 1,
                    broken_at_line=line_no,
                    reason="event missing prev_hash field",
                )
            if recorded_prev != expected_prev:
                return VerifyResult(
                    ok=False,
                    total_events=line_no - 1,
                    broken_at_line=line_no,
                    reason=(
                        f"chain broken: expected prev_hash={expected_prev[:12]}…, "
                        f"got {recorded_prev[:12]}…"
                    ),
                )
            expected_prev = event_hash(record)

    return VerifyResult(ok=True, total_events=line_no)
