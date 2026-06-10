# SPDX-License-Identifier: FSL-1.1-Apache-2.0
# Copyright (c) 2026 ortim.dev
"""Execution-path cloud hooks: policy enforcement (pre-run) + auto-sync (post-run).

Design:
  * **Offline-safe** — cloud unreachability never blocks the pipeline. Pre-run
    enforcement reads only the *cached* policy (no network); post-run auto-sync
    swallows every network error.
  * **Hot path stays local** — `load_effective_policy` is a cache read. The
    cache is refreshed by `cloud policy`, `cloud sync`, and post-run auto-sync.
  * **Moat** — provider allowlist + budget cap are real, enforced constraints,
    but only when a policy is actually in effect (linked + entitled). No policy
    → degrade (free/unlinked workspaces run unencumbered).
"""

from __future__ import annotations

from pathlib import Path

from ortim.cloud import config as cloud_config
from ortim.cloud import policy as cloud_policy
from ortim.cloud import sync as cloud_sync
from ortim.cloud.client import CloudClient, CloudError
from ortim.cloud.policy import EffectivePolicy


def load_effective_policy(metadata_dir: Path) -> EffectivePolicy | None:
    """Cached org policy for enforcement; None → degrade (no enforcement)."""
    return cloud_policy.load_policy_cache(metadata_dir)


def disallowed_providers(
    policy: EffectivePolicy | None, providers: list[str]
) -> list[str]:
    """Subset of `providers` rejected by the policy allowlist (empty if none)."""
    if policy is None:
        return []
    return sorted({p for p in providers if p and not policy.provider_allowed(p)})


def mandatory_gate_violations(
    policy: EffectivePolicy | None,
    *,
    schema_required: bool,
    schema_honored: bool,
    budget_cap_in_effect: bool,
) -> list[str]:
    """IDs of org-mandated gates this run has bypassed (empty when compliant).

    Backs the "zorunlu gate atlanamaz" invariant — a gate the org marks
    mandatory must actually be honored. Observer-first detective check,
    evaluated against the *cached* policy so it stays offline-safe:

      * **G3 (schema):** the DAG carries a schema/migration task but the
        project advanced past the schema-approval stop without ever opening
        it (e.g. a manual ``ortim advance tasks_ready -> executing``).
      * **G7 (budget):** marked mandatory but no budget cap is in effect, so
        the cap gate can never fire — the ceiling the org requires is absent.

    Gate IDs are matched case-insensitively. ``None`` policy / empty mandatory
    set → no violations (degrade; free/unlinked workspaces are never blocked).
    """
    if policy is None or not policy.mandatory_gates:
        return []
    wanted = {g.strip().upper() for g in policy.mandatory_gates if g and g.strip()}
    bad: list[str] = []
    if "G3" in wanted and schema_required and not schema_honored:
        bad.append("G3")
    if "G7" in wanted and not budget_cap_in_effect:
        bad.append("G7")
    return bad


def refresh_policy(metadata_dir: Path) -> bool:
    """Best-effort: pull the linked org's policy and cache it. Never raises.

    Returns True when the cache was refreshed, False otherwise (not linked,
    not logged in, or cloud unreachable).
    """
    link = cloud_sync.load_link_state(metadata_dir)
    if link is None:
        return False
    cfg = cloud_config.load()
    if not cfg.token:
        return False
    try:
        client = CloudClient(cfg.base_url, cfg.token)
        policy_dto = client.get_policy(link.org_id)
    except CloudError:
        return False
    try:
        cloud_policy.save_policy_cache(metadata_dir, link.org_id, policy_dto)
    except OSError:
        return False
    return True


def auto_sync(
    metadata_dir: Path, current_state: str | None, audit_path: Path
) -> str | None:
    """Post-run: push redacted audit + state, then refresh the policy cache.

    Best-effort and offline-safe — NEVER raises. Returns a short status string
    for display (e.g. ``"accepted=3"``, ``"deferred"``) or None when there is
    nothing to do / the workspace is not cloud-linked.
    """
    link = cloud_sync.load_link_state(metadata_dir)
    if link is None:
        return None

    payload, new_cursor = cloud_sync.build_payload(
        audit_path, after_seq=link.synced_seq, current_state=current_state
    )
    if not payload["events"] and new_cursor == link.synced_seq:
        refresh_policy(metadata_dir)  # nothing to push; still refresh policy
        return None

    cfg = cloud_config.load()
    if not cfg.token:
        return None

    try:
        client = CloudClient(cfg.base_url, cfg.token)
        result = client.sync(link.project_id, payload)
    except CloudError:
        return "deferred"  # offline: cursor intentionally not advanced

    link.synced_seq = new_cursor
    cloud_sync.save_link_state(metadata_dir, link)
    refresh_policy(metadata_dir)
    accepted = result.get("accepted")
    return f"accepted={accepted}" if accepted is not None else "ok"
