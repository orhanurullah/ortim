# SPDX-License-Identifier: FSL-1.1-Apache-2.0
# Copyright (c) 2026 ortim.dev
"""Smoke tests for runtime/codebase/baseline.py.

Cover:
  25. detect_test_cmd → flutter test for a Flutter workspace
  26. parse_test_count on a real-shape pytest summary
  27. check_regression flags baseline=10, current=8 as a regression
  28. check_regression is a no-op when no baseline was captured
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from runtime.codebase.baseline import (  # noqa: E402
    TestBaseline,
    check_regression,
    detect_test_cmd,
    parse_test_count,
)


def test_detect_test_cmd_flutter() -> None:
    """Test 25: pubspec.yaml present → flutter test."""
    with tempfile.TemporaryDirectory() as tmp:
        ws = Path(tmp)
        (ws / "pubspec.yaml").write_text(
            "name: my_app\nflutter:\n  sdk: flutter\n", encoding="utf-8"
        )
        assert detect_test_cmd(ws) == "flutter test"


def test_detect_test_cmd_pytest_then_npm_then_none() -> None:
    """Detection cascade: pytest first, then npm, then None for unknown."""
    with tempfile.TemporaryDirectory() as tmp:
        ws = Path(tmp)
        # pyproject only
        (ws / "pyproject.toml").write_text("[tool.pytest.ini_options]\n", encoding="utf-8")
        assert detect_test_cmd(ws) == "pytest"

    with tempfile.TemporaryDirectory() as tmp:
        ws = Path(tmp)
        (ws / "package.json").write_text('{"scripts": {"test": "jest"}}', encoding="utf-8")
        assert detect_test_cmd(ws) == "npm test"

    with tempfile.TemporaryDirectory() as tmp:
        ws = Path(tmp)
        # No recognized manifest → None
        (ws / "README.md").write_text("hi", encoding="utf-8")
        assert detect_test_cmd(ws) is None


def test_parse_pytest_summary() -> None:
    """Test 26: a typical pytest tail line yields the right counts."""
    stdout = (
        "============================== test session starts ==============================\n"
        "collected 25 items\n\n"
        "tests/test_a.py ........ [ 32%]\n"
        "tests/test_b.py ............ [ 80%]\n"
        "tests/test_c.py .....                                                       [100%]\n\n"
        "============================== 25 passed in 1.42s ==============================\n"
    )
    passing, skipped, failed = parse_test_count(stdout, "pytest")
    assert passing == 25, (passing, skipped, failed)
    assert failed == 0
    assert skipped == 0


def test_parse_pytest_with_failures_and_skips() -> None:
    stdout = "3 failed, 17 passed, 2 skipped in 1.21s"
    passing, skipped, failed = parse_test_count(stdout, "pytest")
    assert (passing, skipped, failed) == (17, 2, 3)


def test_check_regression_flags_drop() -> None:
    """Test 27: baseline=10, current=8 → regressed=True with reason."""
    baseline = TestBaseline(
        cmd="pytest",
        captured_at="2026-05-08T00:00:00Z",
        passing=10,
        skipped=0,
        failed=0,
        full_output_tail="10 passed in 1.0s",
    )
    current_stdout = "8 passed in 1.0s"
    report = check_regression(baseline, current_stdout, cmd="pytest")
    assert report.regressed, report
    assert report.baseline_passing == 10
    assert report.current_passing == 8
    assert "regression" in report.message.lower()


def test_check_regression_no_baseline_is_noop() -> None:
    """Test 28: greenfield (no baseline) → never regressed."""
    report = check_regression(baseline=None, current_stdout="42 passed", cmd="pytest")
    assert report.regressed is False
    assert report.message  # human-readable reason
