# SPDX-License-Identifier: FSL-1.1-Apache-2.0
# Copyright (c) 2026 ortim.dev
"""Org governance policy — local cache + effective view for run-time enforcement.

The control plane is the source of truth (`OrtimPolicy`); the CLI pulls it via
`cloud policy` / post-run auto-sync and caches it per workspace in
`.ortim/policy.json`. `execute`/`run-all` read the *cache* (no network in the
hot path) so enforcement is fast and offline-safe: a cached policy keeps being
enforced when the cloud is unreachable, and a missing cache degrades to no
enforcement (free/unlinked workspaces are never blocked).

Empty cloud policy (org without an active entitlement) also degrades — the
server returns empty lists / null cap, which here means "no constraint".
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path


@dataclass
class EffectivePolicy:
    org_id: str
    mandatory_gates: list[str] = field(default_factory=list)
    allowed_providers: list[str] = field(default_factory=list)
    budget_cap_usd: float | None = None
    fetched_at: str | None = None

    def provider_allowed(self, provider: str | None) -> bool:
        """An empty allowlist means 'any provider'. Comparison is case-insensitive."""
        if not self.allowed_providers:
            return True
        if not provider:
            return True
        return provider.lower() in {p.lower() for p in self.allowed_providers}

    @property
    def is_constraining(self) -> bool:
        """True when the policy actually restricts anything (else it's degrade)."""
        return bool(self.mandatory_gates or self.allowed_providers or self.budget_cap_usd)


def policy_cache_path(metadata_dir: Path) -> Path:
    return metadata_dir / "policy.json"


def save_policy_cache(metadata_dir: Path, org_id: str, policy: dict) -> Path:
    """Persist the server policy DTO (camelCase) into the local cache."""
    cap = policy.get("budgetCapUsd")
    data = {
        "org_id": org_id,
        "mandatory_gates": list(policy.get("mandatoryGates") or []),
        "allowed_providers": list(policy.get("allowedProviders") or []),
        "budget_cap_usd": cap,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
    }
    path = policy_cache_path(metadata_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return path


def load_policy_cache(metadata_dir: Path) -> EffectivePolicy | None:
    """Read the cached policy; None when absent or unreadable (→ degrade)."""
    path = policy_cache_path(metadata_dir)
    if not path.exists():
        return None
    try:
        d = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    cap = d.get("budget_cap_usd")
    try:
        cap_val = float(cap) if cap is not None else None
    except (TypeError, ValueError):
        cap_val = None
    return EffectivePolicy(
        org_id=str(d.get("org_id", "")),
        mandatory_gates=list(d.get("mandatory_gates") or []),
        allowed_providers=list(d.get("allowed_providers") or []),
        budget_cap_usd=cap_val,
        fetched_at=d.get("fetched_at"),
    )
