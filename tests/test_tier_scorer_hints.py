# SPDX-License-Identifier: FSL-1.1-Apache-2.0
# Copyright (c) 2026 ortim.dev
"""Tests for Faz 1.2 B-1 — hint-aware tier scoring.

Proof-points 1+2 showed that a small/solo web backend brief landed at
tier T2/BaaS even when the user named SQLite + FastAPI / Node Express.
Cause: scoring signals (small, solo, low ops) push T2 to 100; T4 max
80. User-named self-hosted stack is the missing tie-breaker.

Fix: T2 gains a blocker when user_stack_hints contain a self-hosted DB
or framework name; T4 gains a bonus. BaaS provider hints (Supabase,
Firebase) suppress the blocker so explicit BaaS users still get T2.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from ortim.architecture.golden_paths import (  # noqa: E402
    AppClass,
    GoldenPathInputs,
    OpsCapacity,
    Scale,
    TeamSize,
    Tier,
    _self_hosted_signal,
    select_tier,
)


# ---------- helper signal classifier ----------------------------------------


def test_self_hosted_signal_returns_none_for_empty() -> None:
    assert _self_hosted_signal([]) is None


def test_self_hosted_signal_detects_db_names() -> None:
    assert _self_hosted_signal(["SQLite"]) == "sqlite"
    # "PostgreSQL" substring-matches "postgres" first; either trigger is
    # sufficient to disqualify T2, so we accept the canonical short form.
    assert _self_hosted_signal(["PostgreSQL", "Express"]) in ("postgres", "postgresql")


def test_self_hosted_signal_detects_framework_names() -> None:
    assert _self_hosted_signal(["FastAPI"]) == "fastapi"
    assert _self_hosted_signal(["Python", "Express"]) == "express"
    assert _self_hosted_signal(["Kotlin", "Spring Boot"]) == "spring"


def test_self_hosted_signal_suppressed_by_baas_provider() -> None:
    """User naming both Supabase AND Postgres = on BaaS (Supabase IS
    managed Postgres). T2 must NOT be blocked in this case."""
    assert _self_hosted_signal(["Supabase", "Postgres"]) is None
    assert _self_hosted_signal(["Firebase"]) is None
    assert _self_hosted_signal(["Appwrite", "SQLite"]) is None


def test_self_hosted_signal_ignores_generic_lang_names() -> None:
    """'Python' / 'Node.js' alone don't signal self-hosted — they could
    be Vercel Python or Cloudflare Workers. Only DB + framework names
    are load-bearing."""
    assert _self_hosted_signal(["Python"]) is None
    assert _self_hosted_signal(["Node.js"]) is None
    assert _self_hosted_signal(["Go"]) is None


# ---------- end-to-end scoring ----------------------------------------------


def _small_solo_web() -> GoldenPathInputs:
    """The brief class that triggered the bug — small solo web app with
    auth + persistence, low ops capacity."""
    return GoldenPathInputs(
        has_persistent_state=True,
        has_auth=True,
        compliance=[],
        expected_scale=Scale.SMALL,
        team_size=TeamSize.SOLO,
        ops_capacity=OpsCapacity.LOW,
        app_class=AppClass.WEB,
    )


def test_t2_wins_without_hints() -> None:
    """Pre-1.2 behavior preserved: no hints → T2 BaaS still wins for
    small solo web. Faz 1.1 fixtures + downstream demo path that don't
    populate user_stack_hints must stay green."""
    inputs = _small_solo_web()
    selected = select_tier(inputs)
    assert selected.tier == Tier.T2


def test_t4_wins_when_user_named_sqlite() -> None:
    """The bug case: user wrote 'SQLite' in the brief, Babel captured
    it, but tier scorer ignored it. With B-1, SQLite blocks T2 and
    boosts T4 → T4 wins."""
    inputs = _small_solo_web()
    inputs.user_stack_hints = ["Python", "FastAPI", "SQLite"]
    selected = select_tier(inputs)
    assert selected.tier == Tier.T4


def test_t4_wins_when_user_named_self_hosted_framework() -> None:
    inputs = _small_solo_web()
    inputs.user_stack_hints = ["Node.js", "Express"]
    selected = select_tier(inputs)
    assert selected.tier == Tier.T4


def test_t2_still_wins_when_user_named_supabase() -> None:
    """The BaaS-provider suppression: user explicitly chose Supabase →
    T2 stays valid even if 'Postgres' also appears (Supabase = Postgres)."""
    inputs = _small_solo_web()
    inputs.user_stack_hints = ["Supabase", "PostgreSQL"]
    selected = select_tier(inputs)
    assert selected.tier == Tier.T2


def test_t2_blocker_reason_names_the_offending_hint() -> None:
    """Blocker reason must surface which hint disqualified BaaS so the
    user can see the trace in tier_score.cons / RFC §2."""
    inputs = _small_solo_web()
    inputs.user_stack_hints = ["SQLite"]
    from ortim.architecture.golden_paths import _score_t2

    t2 = _score_t2(inputs)
    assert t2.blockers
    blocker = t2.blockers[-1].lower()
    assert "sqlite" in blocker
    assert "baas" in blocker
