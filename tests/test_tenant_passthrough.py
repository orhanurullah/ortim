# SPDX-License-Identifier: FSL-1.1-Apache-2.0
# Copyright (c) 2026 ortim.dev
"""Tenant ID passthrough tests.

Validates that the multi-tenant API surface is wired through Project and
BudgetTracker without breaking single-tenant ("default") behavior.

What we DO test (M1 — Gun 0 scope):
  * Default tenant preserves legacy path layout
  * Non-default tenant nests under its own dir
  * Project model round-trips tenant_id field
  * BudgetTracker.report filters by tenant_id

What we do NOT test (deferred to enterprise/):
  * Authentication / authorization
  * Per-tenant rate limiting
  * Cross-tenant audit isolation at the OS level
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from ortim.audit import AuditLogger  # noqa: E402
from ortim.budget import BudgetTracker  # noqa: E402
from ortim.orchestrator import Project  # noqa: E402


def test_default_tenant_preserves_legacy_path() -> None:
    """Default tenant must produce the pre-tenant path layout."""
    root = Path("/tmp/ws")
    p_implicit = Project.workspace_path("p1", root)
    p_explicit = Project.workspace_path("p1", root, "default")
    assert p_implicit == root / "p1"
    assert p_explicit == root / "p1"
    assert p_implicit == p_explicit, (
        "Default tenant path must equal the no-arg path for backward compat"
    )


def test_explicit_tenant_nests_under_its_own_dir() -> None:
    root = Path("/tmp/ws")
    assert Project.workspace_path("p1", root, "acme") == root / "acme" / "p1"
    assert Project.workspace_path("p1", root, "globex") == root / "globex" / "p1"


def test_project_save_load_round_trips_tenant_id() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        # Default tenant
        p_default = Project(name="d", initial_brief_tr="brief")
        p_default.save(root)
        loaded_default = Project.load(p_default.id, root)
        assert loaded_default.tenant_id == "default"
        assert (root / p_default.id / "state.json").exists()

        # Explicit tenant — non-default routes to nested path
        p_acme = Project(name="a", initial_brief_tr="brief", tenant_id="acme")
        p_acme.save(root)
        loaded_acme = Project.load(p_acme.id, root, "acme")
        assert loaded_acme.tenant_id == "acme"
        assert (root / "acme" / p_acme.id / "state.json").exists()
        # And the default-path lookup must NOT find the acme project
        assert not (root / p_acme.id / "state.json").exists()


def test_budget_filter_by_tenant_id() -> None:
    """Audit entries tagged with tenant_id should filter cleanly."""
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "audit.jsonl"
        logger = AuditLogger(path=path)
        # acme tenant — 100 in / 50 out
        logger.log(
            "architect_call",
            project_id="p1",
            tenant_id="acme",
            tokens={"in": 100, "out": 50},
            provider="anthropic",
        )
        # default tenant — 200 in / 100 out
        logger.log(
            "architect_call",
            project_id="p2",
            tenant_id="default",
            tokens={"in": 200, "out": 100},
            provider="anthropic",
        )

        # Sanity: total report (no filter) sees both
        tracker = BudgetTracker(audit_path=path, input_usd_per_m=1.0, output_usd_per_m=1.0)
        full = tracker.report()
        assert full.input_tokens == 300
        assert full.output_tokens == 150

        # Filter by tenant
        acme = tracker.report(tenant_id="acme")
        assert acme.input_tokens == 100
        assert acme.output_tokens == 50

        default = tracker.report(tenant_id="default")
        assert default.input_tokens == 200
        assert default.output_tokens == 100


if __name__ == "__main__":
    tests = [
        test_default_tenant_preserves_legacy_path,
        test_explicit_tenant_nests_under_its_own_dir,
        test_project_save_load_round_trips_tenant_id,
        test_budget_filter_by_tenant_id,
    ]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"PASS  {t.__name__}")
        except Exception as e:
            failed += 1
            print(f"FAIL  {t.__name__}: {e}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
