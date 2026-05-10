# SPDX-License-Identifier: FSL-1.1-Apache-2.0
# Copyright (c) 2026 ortim.dev
"""Deterministic Golden Path scorer.

The Architect agent uses an LLM to extract characteristics from the PRD
(GoldenPathInputs), but the *tier selection itself* is rule-based and
reproducible. This prevents an LLM from picking microservices "because it
sounds enterprise" when a modular monolith is the right answer.

Each tier has a scoring function returning pros, cons, and blockers.
Blockers disqualify a tier outright. Among non-blocked tiers, highest score
wins. T4 (Modular Monolith) is the safety net — it has no blockers and is
chosen when nothing else clearly fits.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from pydantic import BaseModel, Field


class Tier(str, Enum):
    # Web tiers (T0–T6)
    T0 = "T0"
    T1 = "T1"
    T2 = "T2"
    T3 = "T3"
    T4 = "T4"
    T5 = "T5"
    T6 = "T6"
    # Mobile tiers (M0–M2)
    M0 = "M0"
    M1 = "M1"
    M2 = "M2"
    # Desktop tiers (D0–D1)
    D0 = "D0"
    D1 = "D1"


class AppClass(str, Enum):
    """Top-level decision: which tier family applies.

    Architect Call 1 sets this from the PRD ("mobile app", "Flutter") or
    from a brownfield codebase summary's app_class_hint (`runtime.codebase`).
    `MIXED` indicates a monorepo where the operator must explicitly disambiguate.
    """

    WEB = "web"
    MOBILE = "mobile"
    DESKTOP = "desktop"
    MIXED = "mixed"


TIER_NAMES: dict[Tier, str] = {
    Tier.T0: "Static",
    Tier.T1: "SPA / Frontend-only",
    Tier.T2: "BaaS",
    Tier.T3: "Serverless",
    Tier.T4: "Modular Monolith",
    Tier.T5: "Microservices",
    Tier.T6: "Event-driven / CQRS",
    Tier.M0: "Native Mobile",
    Tier.M1: "Cross-platform Mobile (Flutter / RN)",
    Tier.M2: "PWA + Wrapper (Capacitor)",
    Tier.D0: "Native Desktop",
    Tier.D1: "Cross-platform Desktop (Tauri / Electron)",
}


class Scale(str, Enum):
    SMALL = "small"
    MEDIUM = "medium"
    LARGE = "large"
    UNKNOWN = "unknown"


class TeamSize(str, Enum):
    SOLO = "solo"
    SMALL = "small"
    LARGE = "large"
    UNKNOWN = "unknown"


class OpsCapacity(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    UNKNOWN = "unknown"


class GoldenPathInputs(BaseModel):
    has_persistent_state: bool = True
    has_auth: bool = True
    compliance: list[str] = Field(default_factory=list)
    expected_scale: Scale = Scale.UNKNOWN
    team_size: TeamSize = TeamSize.UNKNOWN
    audit_heavy: bool = False
    realtime_required: bool = False
    multi_tenant: bool = False
    bursty_workload: bool = False
    ops_capacity: OpsCapacity = OpsCapacity.UNKNOWN

    # M1 — app-class extension. Default WEB preserves pre-M1 scoring behavior.
    app_class: AppClass = AppClass.WEB
    target_platforms: list[str] = Field(default_factory=list)
    """e.g. ["ios","android"], ["windows","macos","linux"], or ["ios"] for single-target."""
    offline_required: bool = False
    """Significant offline-first capability needed (drift/isar, IndexedDB, local caches)."""
    native_features: list[str] = Field(default_factory=list)
    """Tags from {"ble","high-fps-game","push","biometric","camera","ar",
    "background-sync","deep-os-integration"} — drive M0/M2/D0 scoring."""
    has_existing_web_frontend: bool = False
    """True iff the codebase already ships a React/Vue/Svelte web app — used
    by M2 (PWA wrapper) to determine whether wrapping is feasible."""


@dataclass
class TierScore:
    tier: Tier
    score: int = 0
    pros: list[str] = field(default_factory=list)
    cons: list[str] = field(default_factory=list)
    blockers: list[str] = field(default_factory=list)

    @property
    def disqualified(self) -> bool:
        return bool(self.blockers)

    @property
    def name(self) -> str:
        return TIER_NAMES[self.tier]


def _score_t0(inputs: GoldenPathInputs) -> TierScore:
    s = TierScore(tier=Tier.T0)
    if inputs.has_persistent_state:
        s.blockers.append("requires persistent server-side state")
    if inputs.has_auth:
        s.blockers.append("requires authentication")
    if not s.disqualified:
        s.score = 100
        s.pros.append("zero ops, fully CDN-cacheable")
    return s


def _score_t1(inputs: GoldenPathInputs) -> TierScore:
    s = TierScore(tier=Tier.T1)
    if inputs.has_persistent_state:
        s.blockers.append("backend persistent state needed; SPA is client-only")
    if inputs.has_auth:
        s.blockers.append("auth requires backend or BaaS (use T2 instead)")
    if not s.disqualified:
        s.score = 90
        s.pros.append("simple, CDN-cacheable, fast iteration")
    return s


def _score_t2(inputs: GoldenPathInputs) -> TierScore:
    s = TierScore(tier=Tier.T2)
    enterprise_compliance = {"HIPAA", "PCI-DSS", "SOC2"}
    blocked = enterprise_compliance & set(inputs.compliance)
    if blocked:
        s.blockers.append(
            f"enterprise compliance not BaaS-friendly: {sorted(blocked)}"
        )
    if inputs.expected_scale == Scale.LARGE:
        s.blockers.append("BaaS cost grows non-linearly at large scale")
    if not s.disqualified:
        # Score scales with how many positive BaaS signals fired.
        # No signals → low score → T4 wins. Full signals → strong T2 win.
        signals = sum(
            [
                inputs.expected_scale == Scale.SMALL,
                inputs.team_size == TeamSize.SOLO,
                inputs.ops_capacity == OpsCapacity.LOW,
            ]
        )
        s.score = {0: 40, 1: 65, 2: 85, 3: 100}[signals]
        s.pros.append("fastest time-to-market")
        s.pros.append("auth + DB + storage out of the box")
        if "KVKK" in inputs.compliance:
            s.cons.append("verify KVKK data residency in chosen BaaS provider")
    return s


def _score_t3(inputs: GoldenPathInputs) -> TierScore:
    s = TierScore(tier=Tier.T3)
    s.score = 50
    if inputs.bursty_workload:
        s.score += 30
        s.pros.append("scales to zero between bursts")
    if inputs.ops_capacity == OpsCapacity.LOW:
        s.score += 20
        s.pros.append("no infra to manage")
    if inputs.expected_scale == Scale.LARGE:
        s.score -= 10
        s.cons.append("cold starts and per-invocation cost grow with scale")
    if inputs.realtime_required:
        s.cons.append("websocket support varies by serverless provider")
    return s


def _score_t4(inputs: GoldenPathInputs) -> TierScore:
    """Default tier — never blocked. SOLO devs lean BaaS (T2); T4 favors SMALL teams."""
    s = TierScore(tier=Tier.T4, score=60)
    s.pros.append("balanced: simple to deploy, can scale, easy to refactor later")
    s.pros.append("supports any compliance with proper module boundaries")
    if inputs.expected_scale in (Scale.SMALL, Scale.MEDIUM):
        s.score += 20
    if inputs.team_size == TeamSize.SMALL:
        s.score += 15
        s.pros.append("single deploy = lower coordination overhead")
    if inputs.compliance:
        s.score += 10
        s.pros.append(
            f"compliance ({', '.join(inputs.compliance)}) easier to audit in single codebase"
        )
    if inputs.team_size == TeamSize.LARGE:
        s.cons.append(
            "large team may benefit from module-team ownership separation (T5)"
        )
    return s


def _score_t5(inputs: GoldenPathInputs) -> TierScore:
    s = TierScore(tier=Tier.T5)
    if inputs.team_size in (TeamSize.SOLO, TeamSize.SMALL, TeamSize.UNKNOWN):
        s.blockers.append(
            "microservices require a known large team; SOLO/SMALL/UNKNOWN blocked"
        )
    if inputs.ops_capacity == OpsCapacity.LOW:
        s.blockers.append("microservices require significant ops capacity")
    if not s.disqualified:
        s.score = 40
        if inputs.team_size == TeamSize.LARGE:
            s.score += 25
            s.pros.append("team-per-service ownership scales engineering org")
        if inputs.expected_scale == Scale.LARGE:
            s.score += 15
            s.pros.append("independent scaling of hot services")
        s.cons.append("distributed transactions, network failure, observability cost")
    return s


def _score_t6(inputs: GoldenPathInputs) -> TierScore:
    s = TierScore(tier=Tier.T6)
    if inputs.team_size in (TeamSize.SOLO, TeamSize.SMALL, TeamSize.UNKNOWN):
        s.blockers.append("event-driven needs known large team; SOLO/SMALL/UNKNOWN blocked")
    if not s.disqualified:
        s.score = 30
        if inputs.audit_heavy:
            s.score += 30
            s.pros.append("event log = audit trail by construction")
        if inputs.realtime_required:
            s.score += 20
            s.pros.append("event streams natural for realtime")
        if not inputs.audit_heavy and not inputs.realtime_required:
            s.cons.append(
                "event-driven complexity not justified without audit/realtime"
            )
        s.cons.append("eventual consistency, idempotency complexity")
    return s


# ---- Mobile scorers (M0/M1/M2) --------------------------------------------


def _score_m0(inputs: GoldenPathInputs) -> TierScore:
    """Native mobile (Swift / Kotlin). High-leverage only — single platform
    or hardware-bound features (BLE, high-FPS games, AR)."""
    s = TierScore(tier=Tier.M0)
    score = 0
    if "ble" in inputs.native_features:
        score += 30
        s.pros.append("BLE / hardware integration is reliable on native SDKs")
    if "high-fps-game" in inputs.native_features:
        score += 30
        s.pros.append("Skia / Flutter framerate caps lifted on native render path")
    if "ar" in inputs.native_features:
        score += 30
        s.pros.append("ARKit / ARCore native APIs avoid bridge overhead")
    if len(inputs.target_platforms) == 1:
        score += 20
        s.pros.append("single platform = native dev cost matches output")
    if score == 0:
        s.blockers.append(
            "no hardware/single-platform signal; M1 cross-platform default wins"
        )
        return s
    s.score = score
    s.cons.append("two codebases if cross-platform later required")
    return s


def _score_m1(inputs: GoldenPathInputs) -> TierScore:
    """Cross-platform mobile (Flutter / RN). The mobile default. Never blocked."""
    s = TierScore(tier=Tier.M1, score=60)
    s.pros.append("single codebase across iOS+Android")
    s.pros.append("Flutter Material/Cupertino widgets ship most UX out of the box")
    if len(inputs.target_platforms) >= 2:
        s.score += 15
        s.pros.append("cross-platform value compounds with multi-target")
    if inputs.team_size in (TeamSize.SOLO, TeamSize.SMALL):
        s.score += 15
        s.pros.append("single-codebase advantage scales with small team")
    if inputs.offline_required:
        s.score += 10
        s.pros.append("offline-first stack (drift/isar) mature on Flutter")
    if "high-fps-game" in inputs.native_features:
        s.score -= 30
        s.cons.append("Skia render path caps high-FPS gaming workloads (M0 better)")
    if "ble" in inputs.native_features:
        s.score -= 5
        s.cons.append("flutter_blue_plus works but trails native SDK depth")
    return s


def _score_m2(inputs: GoldenPathInputs) -> TierScore:
    """PWA + Capacitor wrapper. Only sensible when an existing web app
    needs a thin mobile presence."""
    s = TierScore(tier=Tier.M2, score=30)
    if inputs.has_existing_web_frontend:
        s.score += 30
        s.pros.append("reuses existing React/Vue/Svelte codebase")
    if "push" in inputs.native_features and "ios" in inputs.target_platforms:
        s.blockers.append(
            "iOS PWA push notifications are unreliable; "
            "wrapper can't paper over the platform gap"
        )
    if "biometric" in inputs.native_features:
        s.cons.append("biometric APIs limited via WebAuthn on iOS")
    if "ble" in inputs.native_features:
        s.blockers.append("BLE not supported in iOS Safari / WKWebView")
    if not inputs.has_existing_web_frontend:
        s.cons.append(
            "no existing web codebase — M1 (Flutter) gives more native UX for the same effort"
        )
    return s


# ---- Desktop scorers (D0/D1) ----------------------------------------------


def _score_d0(inputs: GoldenPathInputs) -> TierScore:
    """Native desktop (SwiftUI / WinUI / GTK). Picked when single-platform
    deep OS integration is required."""
    s = TierScore(tier=Tier.D0)
    if len(inputs.target_platforms) > 1:
        s.blockers.append(
            "native desktop is single-platform by definition; "
            "use D1 cross-platform when multiple targets are needed"
        )
        return s
    score = 30  # base when not blocked
    if len(inputs.target_platforms) == 1:
        score += 30
        s.pros.append("single platform — native dev maps 1:1 to output")
    if "deep-os-integration" in inputs.native_features:
        score += 20
        s.pros.append("OS extension points (services, file providers, menu bar) accessible")
    s.score = score
    s.cons.append("port to other platforms means rewriting from scratch")
    return s


def _score_d1(inputs: GoldenPathInputs) -> TierScore:
    """Cross-platform desktop (Tauri / Electron). Desktop default. Never blocked."""
    s = TierScore(tier=Tier.D1, score=60)
    s.pros.append("Tauri (Rust) gives small binaries; Electron gives largest ecosystem")
    if len(inputs.target_platforms) >= 2:
        s.score += 15
        s.pros.append("cross-platform value compounds with multi-target")
    if inputs.team_size in (TeamSize.SOLO, TeamSize.SMALL):
        s.score += 10
        s.pros.append("single-codebase keeps team focused")
    if "deep-os-integration" in inputs.native_features:
        s.score -= 10
        s.cons.append(
            "deep OS integration is harder behind the WebView abstraction (D0 better)"
        )
    return s


# ---- Scorer registries ----------------------------------------------------

_WEB_SCORERS = (
    _score_t0, _score_t1, _score_t2, _score_t3, _score_t4, _score_t5, _score_t6,
)
_MOBILE_SCORERS = (_score_m0, _score_m1, _score_m2)
_DESKTOP_SCORERS = (_score_d0, _score_d1)

# Default fallback per app class — the tier that is never blocked and that
# select_tier() returns when every other tier is disqualified.
_DEFAULT_FALLBACK: dict[AppClass, Tier] = {
    AppClass.WEB: Tier.T4,
    AppClass.MOBILE: Tier.M1,
    AppClass.DESKTOP: Tier.D1,
}


def score_all(inputs: GoldenPathInputs) -> list[TierScore]:
    """Score every tier in the family selected by `inputs.app_class`.

    AppClass.MIXED is intentionally rejected — when a monorepo holds both
    a Flutter app and a FastAPI service, no single tier scores meaningfully
    over both halves; the Architect must pick a primary class explicitly.
    """
    if inputs.app_class == AppClass.WEB:
        return [scorer(inputs) for scorer in _WEB_SCORERS]
    if inputs.app_class == AppClass.MOBILE:
        return [scorer(inputs) for scorer in _MOBILE_SCORERS]
    if inputs.app_class == AppClass.DESKTOP:
        return [scorer(inputs) for scorer in _DESKTOP_SCORERS]
    raise ValueError(
        f"Cannot auto-score app_class={inputs.app_class.value!r}; "
        "Architect must set a non-MIXED class explicitly"
    )


def select_tier(inputs: GoldenPathInputs) -> TierScore:
    """Pick the highest-scoring non-blocked tier. Falls back to the class default."""
    scores = score_all(inputs)
    valid = [s for s in scores if not s.disqualified]
    fallback_tier = _DEFAULT_FALLBACK[inputs.app_class]
    if not valid:
        return next(s for s in scores if s.tier == fallback_tier)
    return max(valid, key=lambda s: s.score)
