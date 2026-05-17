# SPDX-License-Identifier: FSL-1.1-Apache-2.0
# Copyright (c) 2026 ortim.dev
"""Tests for multi-provider budget reporting.

Audit rows now carry `provider` and `model` (Faz 6a.4). BudgetTracker prices
each row at its own provider's rate and exposes a per-provider breakdown.
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from ortim.budget import BudgetTracker  # noqa: E402
from ortim.llm.providers import PROVIDERS  # noqa: E402


def _write_jsonl(path: Path, records: list[dict]) -> None:
    with path.open("w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")


def test_per_provider_breakdown_splits_correctly() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "decisions.jsonl"
        _write_jsonl(
            path,
            [
                {
                    "project_id": "P", "provider": "anthropic", "model": "claude-opus-4-7",
                    "tokens": {"in": 100_000, "out": 50_000},
                },
                {
                    "project_id": "P", "provider": "deepseek", "model": "deepseek-chat",
                    "tokens": {"in": 200_000, "out": 80_000},
                },
                {
                    "project_id": "P", "provider": "anthropic", "model": "claude-opus-4-7",
                    "tokens": {"in": 50_000, "out": 25_000},
                },
            ],
        )
        report = BudgetTracker(audit_path=path).report("P")

        assert set(report.per_provider) == {"anthropic", "deepseek"}
        ant = report.per_provider["anthropic"]
        ds = report.per_provider["deepseek"]
        assert ant.entry_count == 2
        assert ant.input_tokens == 150_000
        assert ant.output_tokens == 75_000
        assert ds.entry_count == 1
        assert ds.input_tokens == 200_000
        assert ds.output_tokens == 80_000

        # Totals reconcile.
        assert report.input_tokens == ant.input_tokens + ds.input_tokens
        assert report.output_tokens == ant.output_tokens + ds.output_tokens
        assert report.entry_count == 3


def test_per_provider_pricing_applies_correct_rate() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "decisions.jsonl"
        _write_jsonl(
            path,
            [
                {
                    "project_id": "P", "provider": "anthropic",
                    "tokens": {"in": 1_000_000, "out": 1_000_000},
                },
                {
                    "project_id": "P", "provider": "deepseek",
                    "tokens": {"in": 1_000_000, "out": 1_000_000},
                },
            ],
        )
        report = BudgetTracker(audit_path=path).report("P")
        ant_cfg = PROVIDERS["anthropic"]
        ds_cfg = PROVIDERS["deepseek"]

        expected_ant = ant_cfg.input_usd_per_m + ant_cfg.output_usd_per_m
        expected_ds = ds_cfg.input_usd_per_m + ds_cfg.output_usd_per_m

        ant = report.per_provider["anthropic"]
        ds = report.per_provider["deepseek"]
        assert abs(ant.estimated_cost_usd - expected_ant) < 1e-6
        assert abs(ds.estimated_cost_usd - expected_ds) < 1e-6
        assert abs(report.estimated_cost_usd - (expected_ant + expected_ds)) < 1e-6


def test_legacy_rows_without_provider_default_to_anthropic() -> None:
    """Rows written before Faz 6a.4 lack `provider`; treat as anthropic."""
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "decisions.jsonl"
        _write_jsonl(
            path,
            [
                {"project_id": "P", "tokens": {"in": 1000, "out": 500}},  # legacy
                {
                    "project_id": "P", "provider": "deepseek",
                    "tokens": {"in": 2000, "out": 1000},
                },
            ],
        )
        report = BudgetTracker(audit_path=path).report("P")
        assert "anthropic" in report.per_provider
        assert "deepseek" in report.per_provider
        assert report.per_provider["anthropic"].entry_count == 1
        assert report.per_provider["anthropic"].input_tokens == 1000


def test_unknown_provider_falls_back_to_anthropic_pricing() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "decisions.jsonl"
        _write_jsonl(
            path,
            [
                {
                    "project_id": "P", "provider": "made-up-llm",
                    "tokens": {"in": 1_000_000, "out": 0},
                },
            ],
        )
        report = BudgetTracker(audit_path=path).report("P")
        # Unknown provider keeps its name in the breakdown so the user sees it,
        # but cost is computed at the anthropic fallback rate.
        assert "made-up-llm" in report.per_provider
        expected = PROVIDERS["anthropic"].input_usd_per_m
        br = report.per_provider["made-up-llm"]
        assert abs(br.estimated_cost_usd - expected) < 1e-6


if __name__ == "__main__":
    tests = [
        test_per_provider_breakdown_splits_correctly,
        test_per_provider_pricing_applies_correct_rate,
        test_legacy_rows_without_provider_default_to_anthropic,
        test_unknown_provider_falls_back_to_anthropic_pricing,
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
