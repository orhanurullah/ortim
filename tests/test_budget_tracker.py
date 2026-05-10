# SPDX-License-Identifier: FSL-1.1-Apache-2.0
# Copyright (c) 2026 ortim.dev
"""Tests for budget tracker reading from synthetic audit JSONL."""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from runtime.budget import BudgetTracker  # noqa: E402


def _write_jsonl(path: Path, records: list[dict]) -> None:
    with path.open("w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")


def test_empty_log_returns_zero_report() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "decisions.jsonl"
        tracker = BudgetTracker(audit_path=path)
        report = tracker.report()
        assert report.input_tokens == 0
        assert report.output_tokens == 0
        assert report.estimated_cost_usd == 0.0
        assert report.entry_count == 0


def test_aggregates_tokens_across_entries() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "decisions.jsonl"
        _write_jsonl(
            path,
            [
                {"event": "babel_extract_ok", "project_id": "P1", "tokens": {"in": 1000, "out": 500}},
                {"event": "analyst_prd_draft", "project_id": "P1", "tokens": {"in": 2000, "out": 1500}},
                {"event": "babel_extract_ok", "project_id": "P2", "tokens": {"in": 800, "out": 200}},
            ],
        )
        tracker = BudgetTracker(audit_path=path)
        all_report = tracker.report()
        assert all_report.input_tokens == 3800
        assert all_report.output_tokens == 2200
        assert all_report.entry_count == 3


def test_filters_by_project_id() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "decisions.jsonl"
        _write_jsonl(
            path,
            [
                {"project_id": "P1", "tokens": {"in": 1000, "out": 500}},
                {"project_id": "P2", "tokens": {"in": 100, "out": 50}},
            ],
        )
        tracker = BudgetTracker(audit_path=path)
        p1 = tracker.report("P1")
        p2 = tracker.report("P2")
        assert p1.input_tokens == 1000
        assert p1.output_tokens == 500
        assert p2.input_tokens == 100
        assert p2.output_tokens == 50


def test_skips_entries_without_token_field() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "decisions.jsonl"
        _write_jsonl(
            path,
            [
                {"event": "state_transition", "project_id": "P1"},
                {"project_id": "P1", "tokens": {"in": 500, "out": 200}},
            ],
        )
        tracker = BudgetTracker(audit_path=path)
        report = tracker.report("P1")
        assert report.input_tokens == 500
        assert report.entry_count == 1


def test_cost_calculation_matches_pricing() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "decisions.jsonl"
        _write_jsonl(
            path,
            [{"project_id": "P1", "tokens": {"in": 1_000_000, "out": 1_000_000}}],
        )
        tracker = BudgetTracker(
            audit_path=path,
            input_usd_per_m=10.0,
            output_usd_per_m=20.0,
        )
        report = tracker.report("P1")
        assert report.estimated_cost_usd == 30.0


def test_is_under_cap() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "decisions.jsonl"
        _write_jsonl(
            path,
            [{"project_id": "P1", "tokens": {"in": 5000, "out": 5000}}],
        )
        tracker = BudgetTracker(audit_path=path)
        assert tracker.is_under_cap("P1", 20_000)
        assert not tracker.is_under_cap("P1", 5_000)


def test_skips_malformed_lines() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "decisions.jsonl"
        path.write_text(
            'not json at all\n'
            '{"project_id": "P1", "tokens": {"in": 100, "out": 50}}\n'
            '\n'
            '{"broken json\n',
            encoding="utf-8",
        )
        tracker = BudgetTracker(audit_path=path)
        report = tracker.report("P1")
        assert report.input_tokens == 100
        assert report.entry_count == 1


if __name__ == "__main__":
    tests = [
        test_empty_log_returns_zero_report,
        test_aggregates_tokens_across_entries,
        test_filters_by_project_id,
        test_skips_entries_without_token_field,
        test_cost_calculation_matches_pricing,
        test_is_under_cap,
        test_skips_malformed_lines,
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
