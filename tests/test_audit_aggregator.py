# SPDX-License-Identifier: FSL-1.1-Apache-2.0
# Copyright (c) 2026 ortim.dev
"""Tests for the retro aggregator + the logger timestamp-no-redact guarantee.

The aggregator is a pure projection over the audit JSONL — no LLM, no
network. Unit tests use synthetic JSONL fixtures so they stay fast and
deterministic. One snapshot test pins the JSON serialization shape so a
downstream dashboard / external tool can rely on field stability.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from ortim.audit import AuditLogger, aggregate, to_json_dict  # noqa: E402
from ortim.audit.logger import _derive_category  # noqa: E402


def _write_jsonl(path: Path, records: list[dict]) -> None:
    with path.open("w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")


def test_aggregate_empty_log_returns_zero_report() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "audit.jsonl"
        report = aggregate("P1", audit_path=path, workspace_root=Path(tmp))
        assert report.total_llm_calls == 0
        assert report.per_category == []
        assert report.per_task == []
        assert report.skill_triggers == []
        assert report.retry_rate == 0.0
        assert report.hitl_escalations == 0
        assert report.wall_seconds_p50 is None
        assert report.wall_seconds_p95 is None


def test_per_category_rollup_and_filter_by_project() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "audit.jsonl"
        _write_jsonl(
            path,
            [
                {
                    "timestamp": "2026-05-15T10:00:00+00:00",
                    "event": "architect_rfc_draft",
                    "category": "architect",
                    "project_id": "P1",
                    "tokens": {"in": 4000, "out": 2000},
                    "provider": "anthropic",
                },
                {
                    "timestamp": "2026-05-15T10:01:00+00:00",
                    "event": "worker_output_ok",
                    "category": "worker",
                    "project_id": "P1",
                    "task_id": "T-001",
                    "tokens": {"in": 3000, "out": 500},
                    "provider": "deepseek",
                },
                {
                    "timestamp": "2026-05-15T10:02:00+00:00",
                    "event": "worker_output_ok",
                    "category": "worker",
                    "project_id": "P2",
                    "task_id": "T-099",
                    "tokens": {"in": 9999, "out": 9999},
                    "provider": "anthropic",
                },
            ],
        )
        report = aggregate("P1", audit_path=path, workspace_root=Path(tmp))
        assert report.total_llm_calls == 2

        by_cat = {r.category: r for r in report.per_category}
        assert set(by_cat) == {"architect", "worker"}
        assert by_cat["architect"].input_tokens == 4000
        assert by_cat["architect"].output_tokens == 2000
        assert by_cat["worker"].input_tokens == 3000
        assert by_cat["worker"].output_tokens == 500
        assert by_cat["architect"].estimated_cost_usd > 0


def test_per_task_attempt_counts_and_wall_time() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "audit.jsonl"
        _write_jsonl(
            path,
            [
                {
                    "timestamp": "2026-05-15T10:00:00+00:00",
                    "event": "worker_sandbox_violation",
                    "category": "worker",
                    "project_id": "P1",
                    "task_id": "T-001",
                    "tokens": {"in": 100, "out": 50},
                    "provider": "anthropic",
                },
                {
                    "timestamp": "2026-05-15T10:00:30+00:00",
                    "event": "worker_output_ok",
                    "category": "worker",
                    "project_id": "P1",
                    "task_id": "T-001",
                    "tokens": {"in": 100, "out": 200},
                    "provider": "anthropic",
                },
                {
                    "timestamp": "2026-05-15T10:01:00+00:00",
                    "event": "reviewer_verdict",
                    "category": "reviewer",
                    "project_id": "P1",
                    "task_id": "T-001",
                    "approved": False,
                    "tokens": {"in": 400, "out": 50},
                    "provider": "anthropic",
                },
                {
                    "timestamp": "2026-05-15T10:02:00+00:00",
                    "event": "worker_output_ok",
                    "category": "worker",
                    "project_id": "P1",
                    "task_id": "T-001",
                    "tokens": {"in": 110, "out": 220},
                    "provider": "anthropic",
                },
                {
                    "timestamp": "2026-05-15T10:02:30+00:00",
                    "event": "reviewer_verdict",
                    "category": "reviewer",
                    "project_id": "P1",
                    "task_id": "T-001",
                    "approved": True,
                    "tokens": {"in": 400, "out": 50},
                    "provider": "anthropic",
                },
            ],
        )
        report = aggregate("P1", audit_path=path, workspace_root=Path(tmp))
        assert len(report.per_task) == 1
        t = report.per_task[0]
        assert t.task_id == "T-001"
        assert t.worker_attempts == 2
        assert t.sandbox_violations == 1
        assert t.reviewer_rejects == 1
        assert t.wall_seconds == 150.0  # 10:00:00 → 10:02:30

        # 1 sandbox + 1 reviewer reject = 2 rejects across 3 attempts
        # (2 worker_ok + 1 sandbox = 3 attempts)
        assert report.retry_rate == round(2 / 3, 4)


def test_skill_triggers_aggregated_from_executor_event() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "audit.jsonl"
        _write_jsonl(
            path,
            [
                {
                    "timestamp": "2026-05-15T10:00:00+00:00",
                    "event": "executor_skill_resolved",
                    "category": "executor",
                    "project_id": "P1",
                    "task_id": "T-001",
                    "worker_skills": ["typescript-module-boundaries", "react-dependency-injection"],
                    "reviewer_skills": ["typescript-module-boundaries"],
                },
                {
                    "timestamp": "2026-05-15T10:05:00+00:00",
                    "event": "executor_skill_resolved",
                    "category": "executor",
                    "project_id": "P1",
                    "task_id": "T-002",
                    "worker_skills": ["typescript-module-boundaries"],
                    "reviewer_skills": [],
                },
            ],
        )
        report = aggregate("P1", audit_path=path, workspace_root=Path(tmp))
        names = {s.skill_name: s for s in report.skill_triggers}
        assert names["typescript-module-boundaries"].trigger_count == 2
        assert names["typescript-module-boundaries"].last_task_id == "T-002"
        assert names["react-dependency-injection"].trigger_count == 1
        # Sorted by count desc, then name asc
        assert report.skill_triggers[0].skill_name == "typescript-module-boundaries"


def test_hitl_escalation_count_from_task_status_file() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        audit_path = Path(tmp) / "audit.jsonl"
        _write_jsonl(
            audit_path,
            [
                {
                    "timestamp": "2026-05-15T10:00:00+00:00",
                    "event": "worker_output_ok",
                    "category": "worker",
                    "project_id": "P1",
                    "task_id": "T-001",
                    "tokens": {"in": 100, "out": 50},
                },
                {
                    "timestamp": "2026-05-15T10:01:00+00:00",
                    "event": "worker_output_ok",
                    "category": "worker",
                    "project_id": "P1",
                    "task_id": "T-002",
                    "tokens": {"in": 100, "out": 50},
                },
            ],
        )
        workspace_root = Path(tmp) / "workspaces"
        (workspace_root / "P1").mkdir(parents=True)
        (workspace_root / "P1" / "task_status.json").write_text(
            json.dumps(
                {
                    "project_id": "P1",
                    "records": {
                        "T-001": {"task_id": "T-001", "status": "DONE", "attempts": 1},
                        "T-002": {
                            "task_id": "T-002",
                            "status": "AWAITING_HITL",
                            "attempts": 3,
                        },
                    },
                }
            ),
            encoding="utf-8",
        )
        report = aggregate("P1", audit_path=audit_path, workspace_root=workspace_root)
        assert report.hitl_escalations == 1
        by_id = {t.task_id: t for t in report.per_task}
        assert by_id["T-001"].final_status == "done"
        assert by_id["T-002"].final_status == "awaiting_hitl"


def test_aggregate_handles_unparsable_timestamp() -> None:
    """Pre-fix audit lines have `[PHONE]T13:00:53...` timestamps because
    the redactor's phone regex matched `2026-05-08`. Aggregator must
    survive those rows: tokens still count, only wall_seconds drops."""
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "audit.jsonl"
        _write_jsonl(
            path,
            [
                {
                    "timestamp": "[PHONE]T13:00:53.242264+00:00",
                    "event": "worker_output_ok",
                    "category": "worker",
                    "project_id": "P1",
                    "task_id": "T-001",
                    "tokens": {"in": 100, "out": 50},
                    "provider": "anthropic",
                },
                {
                    "timestamp": "[PHONE]T13:00:59.000000+00:00",
                    "event": "reviewer_verdict",
                    "category": "reviewer",
                    "project_id": "P1",
                    "task_id": "T-001",
                    "approved": True,
                    "tokens": {"in": 200, "out": 50},
                    "provider": "anthropic",
                },
            ],
        )
        report = aggregate("P1", audit_path=path, workspace_root=Path(tmp))
        assert report.total_llm_calls == 2
        t = report.per_task[0]
        assert t.worker_attempts == 1
        assert t.wall_seconds is None
        assert report.wall_seconds_p50 is None
        assert report.wall_seconds_p95 is None


def test_aggregate_skips_malformed_lines() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "audit.jsonl"
        path.write_text(
            "not json at all\n"
            + json.dumps(
                {
                    "timestamp": "2026-05-15T10:00:00+00:00",
                    "event": "worker_output_ok",
                    "category": "worker",
                    "project_id": "P1",
                    "task_id": "T-001",
                    "tokens": {"in": 100, "out": 50},
                }
            )
            + "\n"
            + "{broken json\n",
            encoding="utf-8",
        )
        report = aggregate("P1", audit_path=path, workspace_root=Path(tmp))
        assert report.total_llm_calls == 1


def test_to_json_dict_snapshot_shape() -> None:
    """Pin the field ordering + key set of the JSON serialization so a
    downstream dashboard can rely on stable structure across versions."""
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "audit.jsonl"
        _write_jsonl(
            path,
            [
                {
                    "timestamp": "2026-05-15T10:00:00+00:00",
                    "event": "worker_output_ok",
                    "category": "worker",
                    "project_id": "P1",
                    "task_id": "T-001",
                    "tokens": {"in": 100, "out": 50},
                    "provider": "anthropic",
                },
                {
                    "timestamp": "2026-05-15T10:00:10+00:00",
                    "event": "executor_skill_resolved",
                    "category": "executor",
                    "project_id": "P1",
                    "task_id": "T-001",
                    "worker_skills": ["typescript-module-boundaries"],
                    "reviewer_skills": ["typescript-module-boundaries"],
                },
            ],
        )
        report = aggregate("P1", audit_path=path, workspace_root=Path(tmp))
        out = to_json_dict(report)
        assert set(out.keys()) == {
            "project_id",
            "total_llm_calls",
            "retry_rate",
            "hitl_escalations",
            "wall_seconds_p50",
            "wall_seconds_p95",
            "per_category",
            "per_task",
            "skill_triggers",
        }
        assert set(out["per_category"][0].keys()) == {
            "category",
            "entry_count",
            "input_tokens",
            "output_tokens",
            "estimated_cost_usd",
        }
        assert set(out["per_task"][0].keys()) == {
            "task_id",
            "worker_attempts",
            "sandbox_violations",
            "reviewer_rejects",
            "final_status",
            "wall_seconds",
        }
        assert set(out["skill_triggers"][0].keys()) == {
            "skill_name",
            "trigger_count",
            "last_task_id",
        }


def test_category_derivation_covers_all_emitted_events() -> None:
    """Pin the category map so future events don't silently fall into
    `other` (which makes retro output less useful). When a new agent or
    pipeline stage starts emitting audit events, add its prefix here
    AND to `_CATEGORY_PREFIXES`."""
    expected = {
        "architect_extract_inputs": "architect",
        "orchestrator_dag_ok": "orchestrator",
        "analyst_prd_draft": "analyst",
        "intent_analyst_draft": "analyst",
        "stack_analyst_propose": "analyst",
        "prd_analyst_draft": "analyst",
        "babel_extract_ok": "babel",
        "worker_output_ok": "worker",
        "reviewer_verdict": "reviewer",
        "security_reviewer_verdict": "reviewer",
        "test_reviewer_verdict": "reviewer",
        "perf_reviewer_verdict": "reviewer",
        "executor_skill_resolved": "executor",
        "hook_event": "executor",
        "workspace_bootstrapped": "executor",
        "documenter_readme_generated": "documenter",
        "extend_prd_delta_drafted": "extender",
        "extend_rfc_delta_drafted": "extender",
        "drift_check_run": "drift",
        "budget_cap_exceeded": "budget",
        "gate_promotion": "gate",
        "project_created": "project",
        "intake_locked": "intake",
    }
    for event, category in expected.items():
        assert _derive_category(event) == category, (
            f"{event} should map to {category}, got {_derive_category(event)}"
        )


def test_logger_timestamp_survives_redaction() -> None:
    """Regression guard for the logger fix: timestamp must round-trip as
    ISO 8601, not as `[PHONE]T...`. Without this, `ortim retro` latency
    metrics break silently on every log written with redaction on."""
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "audit.jsonl"
        prev_raw = os.environ.pop("ORTIM_AUDIT_RAW", None)
        try:
            logger = AuditLogger(path=path)
            logger.log("worker_output_ok", project_id="P1", task_id="T-001")
        finally:
            if prev_raw is not None:
                os.environ["ORTIM_AUDIT_RAW"] = prev_raw

        line = path.read_text(encoding="utf-8").splitlines()[0]
        rec = json.loads(line)
        ts = rec["timestamp"]
        assert "[PHONE]" not in ts
        # Pin the ISO-8601 prefix shape (YYYY-MM-DDTHH:MM:SS).
        assert ts[4] == "-" and ts[7] == "-" and ts[10] == "T"


if __name__ == "__main__":
    tests = [
        test_aggregate_empty_log_returns_zero_report,
        test_per_category_rollup_and_filter_by_project,
        test_per_task_attempt_counts_and_wall_time,
        test_skill_triggers_aggregated_from_executor_event,
        test_hitl_escalation_count_from_task_status_file,
        test_aggregate_handles_unparsable_timestamp,
        test_aggregate_skips_malformed_lines,
        test_to_json_dict_snapshot_shape,
        test_category_derivation_covers_all_emitted_events,
        test_logger_timestamp_survives_redaction,
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
