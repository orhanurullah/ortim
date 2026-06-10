# SPDX-License-Identifier: FSL-1.1-Apache-2.0
# Copyright (c) 2026 ortim.dev
"""Build the redacted sync payload from a workspace's audit JSONL.

Maps each `audit.jsonl` record to a control-plane SyncEvent:

  * `chainHash` = `event_hash(record)` — same canonical-JSON+SHA-256 the
    local verifier uses, so the server can verify chain linkage.
  * `payloadMeta` = record minus chain/event/timestamp fields, with any
    code-bearing keys stripped (zero code exposure; mirrors the server's
    `AuditChain` denylist as defense-in-depth).

Offline-safe: callers persist a `synced_seq` cursor in `.ortim/cloud.json`
and only push events past it, so a cloud outage never blocks the pipeline.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from ortim.audit.verify import event_hash
from ortim.llm.providers import pricing_for

# Server-side denylist mirror (ortim-core-backend AuditChain.FORBIDDEN_KEYS).
FORBIDDEN_KEYS = frozenset({
    "code", "source", "source_code", "diff", "patch",
    "content", "file_content", "file_blocks", "files",
    "prompt", "response", "completion", "messages",
})

# Record keys promoted to dedicated SyncEvent fields (excluded from payloadMeta).
_META_EXCLUDE = frozenset({"prev_hash", "event", "timestamp"})


def _strip_forbidden(node: Any, depth: int = 0) -> Any:
    """Recursively drop code-bearing keys from metadata."""
    if depth > 12:
        return node
    if isinstance(node, dict):
        return {
            k: _strip_forbidden(v, depth + 1)
            for k, v in node.items()
            if not (isinstance(k, str) and k.lower() in FORBIDDEN_KEYS)
        }
    if isinstance(node, list):
        return [_strip_forbidden(v, depth + 1) for v in node]
    return node


def _event_cost_usd(record: dict) -> float | None:
    """Per-event USD cost from token usage, priced by the row's provider.

    Pricing stays client-side (single source: `ortim.llm.providers`); we enrich
    the redacted `payloadMeta` with `cost_usd` so the control plane can record
    `usd_spent` metering without duplicating a pricing table. Returns None when
    the row carries no token usage.
    """
    tokens = record.get("tokens")
    if not isinstance(tokens, dict):
        return None
    try:
        in_t = int(tokens.get("in", 0))
        out_t = int(tokens.get("out", 0))
    except (TypeError, ValueError):
        return None
    if in_t == 0 and out_t == 0:
        return None
    provider = str(record.get("provider") or "anthropic").lower()
    try:
        in_per_m, out_per_m = pricing_for(provider, str(record.get("model") or ""))
    except Exception:
        return None
    cost = (in_t / 1_000_000) * in_per_m + (out_t / 1_000_000) * out_per_m
    return round(cost, 6) if cost > 0 else None


def build_events(audit_path: Path, after_seq: int = 0) -> tuple[list[dict], int]:
    """Return (events_past_cursor, total_event_count).

    `total_event_count` is the new cursor to persist on a successful push.
    """
    events: list[dict] = []
    total = 0
    if not audit_path.exists():
        return events, 0
    with audit_path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            total += 1
            if total <= after_seq:
                continue
            meta = {k: v for k, v in record.items() if k not in _META_EXCLUDE}
            payload_meta = _strip_forbidden(meta)
            # Enrich with derived cost so the server can record usd_spent
            # metering. chainHash is computed from the original record (not
            # payloadMeta), so this addition does not affect chain linkage.
            cost = _event_cost_usd(record)
            if cost is not None and isinstance(payload_meta, dict) and "cost_usd" not in payload_meta:
                payload_meta["cost_usd"] = cost
            events.append({
                "seq": total,
                "prevHash": record.get("prev_hash", ""),
                "chainHash": event_hash(record),
                "eventType": record.get("event", "unknown"),
                "payloadMeta": payload_meta,
                "occurredAt": record.get("timestamp"),
            })
    return events, total


def build_payload(
    audit_path: Path,
    after_seq: int = 0,
    current_state: str | None = None,
    task_dag_metadata: dict | None = None,
) -> tuple[dict, int]:
    """Build the full OrtimSyncRequest body + the new cursor."""
    events, total = build_events(audit_path, after_seq)
    head = events[-1]["chainHash"] if events else None
    payload = {
        "currentState": current_state,
        "taskDagMetadata": task_dag_metadata,
        "auditChainHeadHash": head,
        "events": events,
    }
    return payload, total


# ---------------------------------------------------------------------------
# Per-project link state (.ortim/cloud.json)
# ---------------------------------------------------------------------------


@dataclass
class LinkState:
    org_id: str
    project_id: str
    synced_seq: int = 0


def link_state_path(metadata_dir: Path) -> Path:
    return metadata_dir / "cloud.json"


def load_link_state(metadata_dir: Path) -> LinkState | None:
    path = link_state_path(metadata_dir)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return LinkState(
            org_id=data["org_id"],
            project_id=data["project_id"],
            synced_seq=int(data.get("synced_seq", 0)),
        )
    except (OSError, ValueError, KeyError):
        return None


def save_link_state(metadata_dir: Path, state: LinkState) -> Path:
    path = link_state_path(metadata_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(state), indent=2) + "\n", encoding="utf-8")
    return path
