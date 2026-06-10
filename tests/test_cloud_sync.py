# SPDX-License-Identifier: FSL-1.1-Apache-2.0
# Copyright (c) 2026 ortim.dev
"""Task 5: cloud sync payload builder — chain_hash parity, redaction, cursor."""

from __future__ import annotations

import json
from pathlib import Path

from ortim.audit.verify import GENESIS_HASH, event_hash
from ortim.cloud import sync as cloud_sync


def _write_chain(path: Path, records: list[dict]) -> None:
    """Write records as a proper prev_hash chain (mirrors AuditLogger)."""
    prev = GENESIS_HASH
    lines = []
    for body in records:
        record = {"prev_hash": prev, **body}
        lines.append(json.dumps(record, ensure_ascii=False))
        prev = event_hash(record)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_build_events_chain_hash_matches_verifier(tmp_path: Path) -> None:
    audit = tmp_path / "audit.jsonl"
    _write_chain(audit, [
        {"timestamp": "2026-06-03T10:00:00+00:00", "event": "project_init", "category": "project"},
        {"timestamp": "2026-06-03T10:01:00+00:00", "event": "gate_prd_approved", "category": "gate"},
    ])

    events, total = cloud_sync.build_events(audit)

    assert total == 2
    assert len(events) == 2
    # First event chains from genesis; seq is 1-based.
    assert events[0]["seq"] == 1
    assert events[0]["prevHash"] == GENESIS_HASH
    assert events[0]["eventType"] == "project_init"
    assert events[0]["occurredAt"] == "2026-06-03T10:00:00+00:00"
    # Second event's prevHash must equal the first event's chainHash (linkage).
    assert events[1]["prevHash"] == events[0]["chainHash"]


def test_build_events_strips_forbidden_code_keys(tmp_path: Path) -> None:
    audit = tmp_path / "audit.jsonl"
    _write_chain(audit, [
        {
            "timestamp": "2026-06-03T10:00:00+00:00",
            "event": "worker_attempt",
            "category": "worker",
            "task_id": "T-001",
            "diff": "secret patch contents",
            "files": ["a.py"],
            "nested": {"code": "rm -rf /", "tokens": 12},
        },
    ])

    events, _ = cloud_sync.build_events(audit)
    meta = events[0]["payloadMeta"]

    assert "diff" not in meta
    assert "files" not in meta
    assert "code" not in meta["nested"]
    # Non-forbidden siblings survive.
    assert meta["task_id"] == "T-001"
    assert meta["nested"]["tokens"] == 12


def test_build_events_enriches_token_events_with_cost(tmp_path: Path) -> None:
    audit = tmp_path / "audit.jsonl"
    _write_chain(audit, [
        {
            "timestamp": "2026-06-03T10:00:00+00:00",
            "event": "worker_llm_call",
            "category": "worker",
            "provider": "anthropic",
            "model": "claude",
            "tokens": {"in": 1000, "out": 500},
        },
    ])

    events, _ = cloud_sync.build_events(audit)
    meta = events[0]["payloadMeta"]

    # tokens survive (not code-bearing) and cost is derived client-side.
    assert meta["tokens"] == {"in": 1000, "out": 500}
    assert isinstance(meta["cost_usd"], float)
    assert meta["cost_usd"] > 0


def test_build_events_no_cost_when_no_tokens(tmp_path: Path) -> None:
    audit = tmp_path / "audit.jsonl"
    _write_chain(audit, [
        {"timestamp": "2026-06-03T10:00:00+00:00", "event": "project_init", "category": "project"},
    ])

    events, _ = cloud_sync.build_events(audit)
    assert "cost_usd" not in events[0]["payloadMeta"]


def test_cursor_only_returns_new_events(tmp_path: Path) -> None:
    audit = tmp_path / "audit.jsonl"
    _write_chain(audit, [
        {"timestamp": "2026-06-03T10:00:00+00:00", "event": "a", "category": "project"},
        {"timestamp": "2026-06-03T10:01:00+00:00", "event": "b", "category": "project"},
        {"timestamp": "2026-06-03T10:02:00+00:00", "event": "c", "category": "project"},
    ])

    events, total = cloud_sync.build_events(audit, after_seq=2)

    assert total == 3
    assert [e["seq"] for e in events] == [3]
    assert events[0]["eventType"] == "c"


def test_build_payload_sets_head_and_cursor(tmp_path: Path) -> None:
    audit = tmp_path / "audit.jsonl"
    _write_chain(audit, [
        {"timestamp": "2026-06-03T10:00:00+00:00", "event": "a", "category": "project"},
    ])

    payload, cursor = cloud_sync.build_payload(audit, current_state="done")

    assert cursor == 1
    assert payload["currentState"] == "done"
    assert payload["auditChainHeadHash"] == payload["events"][-1]["chainHash"]


def test_missing_audit_file_is_empty(tmp_path: Path) -> None:
    events, total = cloud_sync.build_events(tmp_path / "nope.jsonl")
    assert events == []
    assert total == 0


def test_link_state_roundtrip(tmp_path: Path) -> None:
    state = cloud_sync.LinkState(org_id="org-1", project_id="proj-1", synced_seq=5)
    cloud_sync.save_link_state(tmp_path, state)
    loaded = cloud_sync.load_link_state(tmp_path)
    assert loaded is not None
    assert loaded.org_id == "org-1"
    assert loaded.project_id == "proj-1"
    assert loaded.synced_seq == 5
