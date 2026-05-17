# SPDX-License-Identifier: FSL-1.1-Apache-2.0
# Copyright (c) 2026 ortim.dev
"""Tests for the deterministic Golden Path scorer.

These cover the rule-based logic — the most important part to test, since
the LLM-extracted inputs feed directly into here.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from ortim.architecture import (  # noqa: E402
    AppClass,
    GoldenPathInputs,
    OpsCapacity,
    Scale,
    TeamSize,
    Tier,
    score_all,
    select_tier,
)


def test_default_inputs_select_t4() -> None:
    """With no signals, T4 (modular monolith default) wins."""
    inputs = GoldenPathInputs()
    selected = select_tier(inputs)
    assert selected.tier == Tier.T4


def test_static_site_picks_t0() -> None:
    inputs = GoldenPathInputs(has_persistent_state=False, has_auth=False)
    selected = select_tier(inputs)
    assert selected.tier == Tier.T0


def test_t0_blocked_when_state_required() -> None:
    inputs = GoldenPathInputs(has_persistent_state=True, has_auth=False)
    scores = {s.tier: s for s in score_all(inputs)}
    assert scores[Tier.T0].disqualified


def test_t1_blocked_when_auth_required() -> None:
    inputs = GoldenPathInputs(has_persistent_state=False, has_auth=True)
    scores = {s.tier: s for s in score_all(inputs)}
    assert scores[Tier.T1].disqualified


def test_baas_blocked_by_hipaa() -> None:
    inputs = GoldenPathInputs(compliance=["HIPAA"])
    scores = {s.tier: s for s in score_all(inputs)}
    assert scores[Tier.T2].disqualified
    assert any("HIPAA" in b or "enterprise" in b for b in scores[Tier.T2].blockers)


def test_baas_wins_for_solo_small_kvkk_only() -> None:
    inputs = GoldenPathInputs(
        team_size=TeamSize.SOLO,
        expected_scale=Scale.SMALL,
        ops_capacity=OpsCapacity.LOW,
        compliance=["KVKK"],
    )
    selected = select_tier(inputs)
    assert selected.tier == Tier.T2


def test_microservices_blocked_for_solo_team() -> None:
    inputs = GoldenPathInputs(team_size=TeamSize.SOLO, expected_scale=Scale.LARGE)
    scores = {s.tier: s for s in score_all(inputs)}
    assert scores[Tier.T5].disqualified


def test_microservices_blocked_for_low_ops() -> None:
    inputs = GoldenPathInputs(team_size=TeamSize.LARGE, ops_capacity=OpsCapacity.LOW)
    scores = {s.tier: s for s in score_all(inputs)}
    assert scores[Tier.T5].disqualified


def test_large_team_high_ops_can_pick_microservices() -> None:
    inputs = GoldenPathInputs(
        team_size=TeamSize.LARGE,
        expected_scale=Scale.LARGE,
        ops_capacity=OpsCapacity.HIGH,
    )
    selected = select_tier(inputs)
    assert selected.tier == Tier.T5


def test_event_driven_wins_for_audit_heavy_realtime() -> None:
    inputs = GoldenPathInputs(
        team_size=TeamSize.LARGE,
        ops_capacity=OpsCapacity.HIGH,
        audit_heavy=True,
        realtime_required=True,
    )
    selected = select_tier(inputs)
    assert selected.tier == Tier.T6


def test_event_driven_blocked_for_solo_team() -> None:
    inputs = GoldenPathInputs(
        team_size=TeamSize.SOLO, audit_heavy=True, realtime_required=True
    )
    scores = {s.tier: s for s in score_all(inputs)}
    assert scores[Tier.T6].disqualified


def test_serverless_wins_for_bursty_low_ops() -> None:
    inputs = GoldenPathInputs(
        bursty_workload=True,
        ops_capacity=OpsCapacity.LOW,
        expected_scale=Scale.MEDIUM,
        team_size=TeamSize.SMALL,
    )
    selected = select_tier(inputs)
    assert selected.tier == Tier.T3


def test_t4_never_blocked() -> None:
    """Critical invariant: T4 must always be a valid fallback."""
    test_combinations = [
        GoldenPathInputs(),
        GoldenPathInputs(has_persistent_state=True, has_auth=True),
        GoldenPathInputs(compliance=["HIPAA", "PCI-DSS", "SOC2"]),
        GoldenPathInputs(
            team_size=TeamSize.SOLO,
            expected_scale=Scale.LARGE,
            ops_capacity=OpsCapacity.LOW,
        ),
    ]
    for inputs in test_combinations:
        scores = {s.tier: s for s in score_all(inputs)}
        assert not scores[Tier.T4].disqualified, f"T4 was blocked: {inputs}"


def test_kvkk_compliance_adds_t4_pro() -> None:
    inputs = GoldenPathInputs(compliance=["KVKK"], team_size=TeamSize.SMALL)
    scores = {s.tier: s for s in score_all(inputs)}
    t4 = scores[Tier.T4]
    assert any("compliance" in pro.lower() for pro in t4.pros)


# ---- Day 3: mobile / desktop tier coverage (M1-plan tests 13–17) ----------


def test_mobile_default_picks_m1() -> None:
    """Standard cross-platform Flutter brief lands on M1."""
    inputs = GoldenPathInputs(
        app_class=AppClass.MOBILE,
        target_platforms=["ios", "android"],
    )
    selected = select_tier(inputs)
    assert selected.tier == Tier.M1, selected


def test_mobile_high_fps_game_single_platform_picks_m0() -> None:
    """High-FPS game on iOS only — Flutter render path penalised, M0 wins."""
    inputs = GoldenPathInputs(
        app_class=AppClass.MOBILE,
        target_platforms=["ios"],
        native_features=["high-fps-game"],
    )
    selected = select_tier(inputs)
    assert selected.tier == Tier.M0, selected


def test_mobile_pwa_blocked_when_ios_push_required() -> None:
    """PWA can't deliver iOS push reliably; M2 must be blocked, M1 wins as fallback."""
    inputs = GoldenPathInputs(
        app_class=AppClass.MOBILE,
        target_platforms=["ios"],
        native_features=["push"],
        has_existing_web_frontend=True,  # would otherwise boost M2
    )
    scores = {s.tier: s for s in score_all(inputs)}
    assert scores[Tier.M2].disqualified, scores[Tier.M2]
    assert any("ios" in b.lower() for b in scores[Tier.M2].blockers)
    selected = select_tier(inputs)
    assert selected.tier == Tier.M1, selected


def test_desktop_default_picks_d1() -> None:
    """Multi-target desktop project lands on D1 (Tauri/Electron)."""
    inputs = GoldenPathInputs(
        app_class=AppClass.DESKTOP,
        target_platforms=["macos", "windows"],
    )
    selected = select_tier(inputs)
    assert selected.tier == Tier.D1, selected


def test_desktop_native_picks_d0_for_single_target_with_deep_integration() -> None:
    """Single-platform desktop with OS integration tags lands on D0."""
    inputs = GoldenPathInputs(
        app_class=AppClass.DESKTOP,
        target_platforms=["macos"],
        native_features=["deep-os-integration"],
    )
    selected = select_tier(inputs)
    assert selected.tier == Tier.D0, selected


def test_web_default_inputs_still_pick_t4_after_app_class_extension() -> None:
    """Regression guard: existing web behavior must not change once
    AppClass.WEB is the default."""
    inputs = GoldenPathInputs()
    selected = select_tier(inputs)
    assert selected.tier == Tier.T4


if __name__ == "__main__":
    tests = [
        test_default_inputs_select_t4,
        test_static_site_picks_t0,
        test_t0_blocked_when_state_required,
        test_t1_blocked_when_auth_required,
        test_baas_blocked_by_hipaa,
        test_baas_wins_for_solo_small_kvkk_only,
        test_microservices_blocked_for_solo_team,
        test_microservices_blocked_for_low_ops,
        test_large_team_high_ops_can_pick_microservices,
        test_event_driven_wins_for_audit_heavy_realtime,
        test_event_driven_blocked_for_solo_team,
        test_serverless_wins_for_bursty_low_ops,
        test_t4_never_blocked,
        test_kvkk_compliance_adds_t4_pro,
        test_mobile_default_picks_m1,
        test_mobile_high_fps_game_single_platform_picks_m0,
        test_mobile_pwa_blocked_when_ios_push_required,
        test_desktop_default_picks_d1,
        test_desktop_native_picks_d0_for_single_target_with_deep_integration,
        test_web_default_inputs_still_pick_t4_after_app_class_extension,
    ]
    failed = 0
    for test in tests:
        try:
            test()
            print(f"PASS  {test.__name__}")
        except Exception as e:
            failed += 1
            print(f"FAIL  {test.__name__}: {e}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
