# SPDX-License-Identifier: FSL-1.1-Apache-2.0
# Copyright (c) 2026 ortim.dev
"""Append-only structured audit log (JSONL).

Every agent decision, every state transition, every LLM call should land here.
This is the source-of-truth for cost reporting, drift detection, and debugging.

Compliance posture (M1 — Gun 0):

  * Strings are PII-redacted before serialization (email, T.C. Kimlik, phone,
    credit-card, IPv4). Bypass with `ORTIM_AUDIT_RAW=1` for debug only.
  * Each event carries a `prev_hash` field that chains to the previous event,
    enabling tamper-evidence detection via `ortim.audit.verify.verify_chain`.
  * Every event is tagged with a `category` field (architect, worker, …) for
    compliance/consultancy reporting filters.

Thread-safe: a per-instance `threading.Lock` serializes writes so concurrent
Workers in `run-all --parallel` cannot interleave bytes within a single
record. The lock also protects the `_last_hash` cache used to chain events.
"""

from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ortim.audit.redact import redact_value, redaction_enabled
from ortim.audit.verify import GENESIS_HASH, event_hash

# Map event-name prefixes to taxonomy categories. Anything that doesn't match
# falls into "other"; tests assert that the production code paths all hit a
# known category, so "other" should not appear in real runs.
_CATEGORY_PREFIXES: tuple[tuple[str, str], ...] = (
    ("architect_", "architect"),
    ("orchestrator_", "orchestrator"),
    ("analyst_", "analyst"),
    ("intent_analyst_", "analyst"),
    ("stack_analyst_", "analyst"),
    ("prd_analyst_", "analyst"),
    ("babel_", "babel"),
    ("worker_", "worker"),
    ("reviewer_", "reviewer"),
    ("security_reviewer_", "reviewer"),
    ("test_reviewer_", "reviewer"),
    ("perf_reviewer_", "reviewer"),
    ("executor_", "executor"),
    ("hook_", "executor"),
    ("workspace_", "executor"),
    ("documenter_", "documenter"),
    ("extend_", "extender"),
    ("drift_", "drift"),
    ("budget_", "budget"),
    ("gate_", "gate"),
    ("project_", "project"),
    ("intake_", "intake"),
)


def _derive_category(event: str) -> str:
    for prefix, category in _CATEGORY_PREFIXES:
        if event.startswith(prefix):
            return category
    return "other"


class AuditLogger:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or Path(
            os.getenv("AUDIT_LOG_PATH", "./ortim/audit/decisions.jsonl")
        )
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._write_lock = threading.Lock()
        self._last_hash: str | None = None  # populated lazily on first log

    def _load_last_hash(self) -> str:
        """Read the tail of the JSONL to seed the hash chain.

        Called under `_write_lock`. Returns GENESIS_HASH if the file is empty
        or missing. If a line is corrupt, the most recent valid record wins;
        the chain verifier will flag any discontinuity at read time.
        """
        if not self.path.exists():
            return GENESIS_HASH
        last_record: dict[str, Any] | None = None
        try:
            with self.path.open("r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        last_record = json.loads(line)
                    except json.JSONDecodeError:
                        continue
        except OSError:
            return GENESIS_HASH
        if last_record is None:
            return GENESIS_HASH
        return event_hash(last_record)

    def log(self, event: str, **fields: Any) -> None:
        category = fields.pop("category", None) or _derive_category(event)
        bypassed = not redaction_enabled()

        # Timestamp is system-generated (UTC ISO 8601) and contains no PII,
        # but the date portion (`YYYY-MM-DD`) trips the phone regex because
        # `-` is one of its digit-grouping indicators — producing absurd
        # `[PHONE]T13:00:53...` strings that break any downstream consumer
        # parsing wall time (e.g. `ortim retro` latency rollup). Keep the
        # timestamp out of the redaction pass; redact the rest of the body.
        timestamp = datetime.now(timezone.utc).isoformat()
        body: dict[str, Any] = {
            "event": event,
            "category": category,
            **fields,
        }
        if bypassed:
            body["redaction_bypassed"] = True
        else:
            body = redact_value(body)  # type: ignore[assignment]
        body = {"timestamp": timestamp, **body}

        with self._write_lock:
            if self._last_hash is None:
                self._last_hash = self._load_last_hash()
            record = {"prev_hash": self._last_hash, **body}
            line = json.dumps(record, ensure_ascii=False) + "\n"
            with self.path.open("a", encoding="utf-8") as f:
                f.write(line)
            self._last_hash = event_hash(record)
