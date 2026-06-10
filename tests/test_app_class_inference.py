# SPDX-License-Identifier: FSL-1.1-Apache-2.0
# Copyright (c) 2026 ortim.dev
"""Tests for Faz 1.2 B-5 — deterministic app_class inference.

Proof-point 45ed19809dec showed that a Flutter mobile brief landed at
tier T2/BaaS because Architect Call 1's LLM defaults `app_class` to
"web" when the PRD has no mobile/desktop signal — even though Babel
captured "Flutter" / "Hive" / "SharedPreferences" in user_stack_hints.

`app_class_from_hints` is a pure deterministic gate that closes this
silent drift: when the hints contain a framework name that only makes
sense for mobile or desktop, return that app_class for downstream
override. Returns None when hints don't carry a clear signal so the
LLM's choice still wins for ambiguous briefs.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from ortim.babel import app_class_from_brief, app_class_from_hints  # noqa: E402


def test_empty_hints_returns_none() -> None:
    assert app_class_from_hints([]) is None


def test_web_only_hints_return_none() -> None:
    """Python + SQLite is a backend brief — no clear app_class signal.
    Architect Call 1's LLM choice stays authoritative."""
    assert app_class_from_hints(["Python", "FastAPI", "SQLite"]) is None
    assert app_class_from_hints(["Node.js", "Express", "PostgreSQL"]) is None


def test_flutter_hint_yields_mobile() -> None:
    assert app_class_from_hints(["Flutter", "Hive"]) == "mobile"


def test_react_native_variants_yield_mobile() -> None:
    assert app_class_from_hints(["React Native"]) == "mobile"
    assert app_class_from_hints(["react-native", "Expo"]) == "mobile"


def test_other_mobile_frameworks_yield_mobile() -> None:
    assert app_class_from_hints(["Ionic"]) == "mobile"
    assert app_class_from_hints(["Capacitor", "React"]) == "mobile"
    assert app_class_from_hints(["SwiftUI"]) == "mobile"
    assert app_class_from_hints(["Jetpack Compose"]) == "mobile"


def test_tauri_hint_yields_desktop() -> None:
    assert app_class_from_hints(["Tauri", "React", "TypeScript"]) == "desktop"


def test_electron_yields_desktop() -> None:
    assert app_class_from_hints(["Electron", "TypeScript"]) == "desktop"


def test_case_insensitive() -> None:
    assert app_class_from_hints(["FLUTTER"]) == "mobile"
    assert app_class_from_hints(["TAURI"]) == "desktop"


def test_mobile_wins_over_web_companion_libs() -> None:
    """Flutter mobile may use Dio (HTTP client) — the mobile framework
    still drives the app_class verdict."""
    assert app_class_from_hints(["Flutter", "Dio", "Riverpod"]) == "mobile"


def test_mobile_wins_when_both_signals_present() -> None:
    """Edge case: user names both Flutter and Tauri. Mobile is checked
    first (heuristic — more common). Document this so a future test
    catches drift if priority changes."""
    assert app_class_from_hints(["Flutter", "Tauri"]) == "mobile"


def test_generic_mobile_terms_in_hints_yield_mobile() -> None:
    """Babel may capture 'mobile app' or 'Android' verbatim from a brief
    that names no framework. The hint classifier must still resolve."""
    assert app_class_from_hints(["mobile app"]) == "mobile"
    assert app_class_from_hints(["Android"]) == "mobile"
    assert app_class_from_hints(["iOS"]) == "mobile"
    assert app_class_from_hints(["mobil uygulama"]) == "mobile"


def test_generic_desktop_terms_in_hints_yield_desktop() -> None:
    assert app_class_from_hints(["desktop"]) == "desktop"
    assert app_class_from_hints(["masaüstü"]) == "desktop"
    assert app_class_from_hints(["Windows app"]) == "desktop"


# ---------------- app_class_from_brief — raw-text scanner ----------------


def test_brief_empty_returns_none() -> None:
    assert app_class_from_brief("") is None


def test_brief_with_no_platform_signal_returns_none() -> None:
    assert app_class_from_brief("basit bir todo yöneticisi") is None
    assert app_class_from_brief("REST API for inventory tracking") is None


def test_brief_explicit_turkish_mobile_phrase_returns_mobile() -> None:
    assert app_class_from_brief("Android için mobil uygulama yapmak istiyorum") == "mobile"
    assert app_class_from_brief("iOS uygulaması olacak") == "mobile"


def test_brief_explicit_english_mobile_phrase_returns_mobile() -> None:
    assert app_class_from_brief("a mobile app for tracking habits") == "mobile"
    assert app_class_from_brief("publish to Play Store and App Store") == "mobile"


def test_brief_framework_name_returns_mobile() -> None:
    assert app_class_from_brief("React Native uygulama") == "mobile"
    assert app_class_from_brief("Flutter ile habit tracker") == "mobile"


def test_brief_explicit_desktop_returns_desktop() -> None:
    assert app_class_from_brief("Tauri ile masaüstü uygulaması") == "desktop"
    assert app_class_from_brief("a desktop application for Windows") == "desktop"


def test_brief_word_boundary_avoids_false_positives() -> None:
    """'ios' inside 'kiosks' or 'studios' must not fire."""
    assert app_class_from_brief("kiosks for retail stores") is None
    assert app_class_from_brief("recording studios management") is None
    assert app_class_from_brief("a tabletop game scorekeeper") is None


def test_brief_mobile_wins_over_desktop_when_both_present() -> None:
    """Matches `app_class_from_hints` priority ordering for consistency."""
    assert app_class_from_brief("mobile app with desktop companion") == "mobile"
