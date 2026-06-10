# SPDX-License-Identifier: FSL-1.1-Apache-2.0
# Copyright (c) 2026 ortim.dev
"""Task 8: org policy cache + execution-path hooks (enforcement / auto-sync).

Covers the staged scope: provider allowlist resolution, policy caching for
offline enforcement, and offline-safe auto-sync (cloud outage never blocks).
"""

from __future__ import annotations

import json
from pathlib import Path

from ortim.audit.verify import GENESIS_HASH, event_hash
from ortim.cloud import hooks
from ortim.cloud import policy as cloud_policy
from ortim.cloud import sync as cloud_sync
from ortim.cloud.config import CloudConfig

# --------------------------------------------------------------------------- #
# policy cache + EffectivePolicy
# --------------------------------------------------------------------------- #


def test_policy_cache_roundtrip(tmp_path: Path) -> None:
    dto = {
        "mandatoryGates": ["G5", "G6"],
        "allowedProviders": ["anthropic", "deepseek"],
        "budgetCapUsd": 12.50,
    }
    cloud_policy.save_policy_cache(tmp_path, "org-1", dto)
    pol = cloud_policy.load_policy_cache(tmp_path)

    assert pol is not None
    assert pol.org_id == "org-1"
    assert pol.mandatory_gates == ["G5", "G6"]
    assert pol.allowed_providers == ["anthropic", "deepseek"]
    assert pol.budget_cap_usd == 12.50
    assert pol.is_constraining is True


def test_load_policy_cache_missing_is_none(tmp_path: Path) -> None:
    assert cloud_policy.load_policy_cache(tmp_path) is None


def test_empty_policy_allows_any_provider(tmp_path: Path) -> None:
    cloud_policy.save_policy_cache(
        tmp_path, "org-1", {"mandatoryGates": [], "allowedProviders": [], "budgetCapUsd": None}
    )
    pol = cloud_policy.load_policy_cache(tmp_path)
    assert pol is not None
    assert pol.provider_allowed("anything") is True
    assert pol.is_constraining is False
    assert pol.budget_cap_usd is None


def test_provider_allowed_is_case_insensitive() -> None:
    pol = cloud_policy.EffectivePolicy(org_id="o", allowed_providers=["Anthropic"])
    assert pol.provider_allowed("anthropic") is True
    assert pol.provider_allowed("deepseek") is False


# --------------------------------------------------------------------------- #
# hooks.disallowed_providers
# --------------------------------------------------------------------------- #


def test_disallowed_providers_none_policy_degrades() -> None:
    assert hooks.disallowed_providers(None, ["deepseek"]) == []


def test_disallowed_providers_reports_violations() -> None:
    pol = cloud_policy.EffectivePolicy(org_id="o", allowed_providers=["anthropic"])
    assert hooks.disallowed_providers(pol, ["anthropic", "deepseek", "openai"]) == [
        "deepseek",
        "openai",
    ]


def test_disallowed_providers_empty_allowlist_allows_all() -> None:
    pol = cloud_policy.EffectivePolicy(org_id="o", allowed_providers=[])
    assert hooks.disallowed_providers(pol, ["deepseek", "openai"]) == []


# --------------------------------------------------------------------------- #
# hooks.mandatory_gate_violations — "zorunlu gate atlanamaz"
# --------------------------------------------------------------------------- #


def test_mandatory_gate_none_policy_degrades() -> None:
    assert (
        hooks.mandatory_gate_violations(
            None, schema_required=True, schema_honored=False, budget_cap_in_effect=False
        )
        == []
    )


def test_mandatory_gate_empty_set_degrades() -> None:
    pol = cloud_policy.EffectivePolicy(org_id="o", mandatory_gates=[])
    assert (
        hooks.mandatory_gate_violations(
            pol, schema_required=True, schema_honored=False, budget_cap_in_effect=False
        )
        == []
    )


def test_mandatory_schema_bypass_is_violation() -> None:
    # G3 mandatory + a schema task in the DAG, but the run jumped the stop.
    pol = cloud_policy.EffectivePolicy(org_id="o", mandatory_gates=["G3"])
    assert hooks.mandatory_gate_violations(
        pol, schema_required=True, schema_honored=False, budget_cap_in_effect=True
    ) == ["G3"]


def test_mandatory_schema_honored_is_clean() -> None:
    pol = cloud_policy.EffectivePolicy(org_id="o", mandatory_gates=["G3"])
    assert (
        hooks.mandatory_gate_violations(
            pol, schema_required=True, schema_honored=True, budget_cap_in_effect=True
        )
        == []
    )


def test_mandatory_schema_not_required_is_clean() -> None:
    # No schema task in the DAG → G3 is moot even when mandatory.
    pol = cloud_policy.EffectivePolicy(org_id="o", mandatory_gates=["G3"])
    assert (
        hooks.mandatory_gate_violations(
            pol, schema_required=False, schema_honored=False, budget_cap_in_effect=True
        )
        == []
    )


def test_mandatory_budget_without_cap_is_violation() -> None:
    # Gate IDs are matched case-insensitively.
    pol = cloud_policy.EffectivePolicy(org_id="o", mandatory_gates=["g7"])
    assert hooks.mandatory_gate_violations(
        pol, schema_required=False, schema_honored=True, budget_cap_in_effect=False
    ) == ["G7"]


def test_mandatory_budget_with_cap_is_clean() -> None:
    pol = cloud_policy.EffectivePolicy(org_id="o", mandatory_gates=["G7"])
    assert (
        hooks.mandatory_gate_violations(
            pol, schema_required=False, schema_honored=True, budget_cap_in_effect=True
        )
        == []
    )


def test_mandatory_multiple_violations_listed_in_order() -> None:
    pol = cloud_policy.EffectivePolicy(org_id="o", mandatory_gates=["G7", "G3"])
    assert hooks.mandatory_gate_violations(
        pol, schema_required=True, schema_honored=False, budget_cap_in_effect=False
    ) == ["G3", "G7"]


# --------------------------------------------------------------------------- #
# hooks.auto_sync — offline-safe
# --------------------------------------------------------------------------- #


def _write_chain(path: Path, records: list[dict]) -> None:
    prev = GENESIS_HASH
    lines = []
    for body in records:
        record = {"prev_hash": prev, **body}
        lines.append(json.dumps(record, ensure_ascii=False))
        prev = event_hash(record)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


class _OfflineClient:
    def __init__(self, *a, **k) -> None:
        pass

    def sync(self, *a, **k):
        raise hooks.CloudError("cloud down")

    def get_policy(self, *a, **k):
        raise hooks.CloudError("cloud down")


class _OnlineClient:
    def __init__(self, *a, **k) -> None:
        pass

    def sync(self, project_id, payload):
        return {"accepted": len(payload["events"]), "skipped": 0}

    def get_policy(self, org_id):
        return {"mandatoryGates": [], "allowedProviders": ["anthropic"], "budgetCapUsd": 9}


def test_auto_sync_not_linked_returns_none(tmp_path: Path) -> None:
    audit = tmp_path / "audit.jsonl"
    _write_chain(audit, [{"timestamp": "t", "event": "a", "category": "project"}])
    # No cloud.json link state in tmp_path → no-op.
    assert hooks.auto_sync(tmp_path, current_state="done", audit_path=audit) is None


def test_auto_sync_offline_defers_without_advancing_cursor(tmp_path, monkeypatch) -> None:
    audit = tmp_path / "audit.jsonl"
    _write_chain(audit, [{"timestamp": "t", "event": "a", "category": "project"}])
    cloud_sync.save_link_state(
        tmp_path, cloud_sync.LinkState(org_id="org-1", project_id="proj-1", synced_seq=0)
    )
    monkeypatch.setattr(hooks, "CloudClient", _OfflineClient)
    monkeypatch.setattr(hooks.cloud_config, "load", lambda: CloudConfig(token="t"))

    status = hooks.auto_sync(tmp_path, current_state="done", audit_path=audit)

    assert status == "deferred"
    # Cursor must NOT advance on an offline deferral (event re-pushed next run).
    assert cloud_sync.load_link_state(tmp_path).synced_seq == 0


def test_auto_sync_success_advances_cursor_and_caches_policy(tmp_path, monkeypatch) -> None:
    audit = tmp_path / "audit.jsonl"
    _write_chain(audit, [
        {"timestamp": "t1", "event": "a", "category": "project"},
        {"timestamp": "t2", "event": "b", "category": "project"},
    ])
    cloud_sync.save_link_state(
        tmp_path, cloud_sync.LinkState(org_id="org-1", project_id="proj-1", synced_seq=0)
    )
    monkeypatch.setattr(hooks, "CloudClient", _OnlineClient)
    monkeypatch.setattr(hooks.cloud_config, "load", lambda: CloudConfig(token="t"))

    status = hooks.auto_sync(tmp_path, current_state="done", audit_path=audit)

    assert status == "accepted=2"
    assert cloud_sync.load_link_state(tmp_path).synced_seq == 2
    # Policy refreshed into the local cache as a side effect.
    cached = cloud_policy.load_policy_cache(tmp_path)
    assert cached is not None
    assert cached.allowed_providers == ["anthropic"]
    assert cached.budget_cap_usd == 9
