# SPDX-License-Identifier: FSL-1.1-Apache-2.0
# Copyright (c) 2026 ortim.dev
"""Retrospective rollup over the audit JSONL.

Produces a multi-axis view of a single project run:

  * per-category token + USD breakdown (worker, reviewer, architect, ...)
  * per-task attempt stats (worker_output_ok / sandbox_violation /
    reviewer_reject counts + wall_seconds end-to-end)
  * skill trigger counts (resolved via `executor_skill_resolved` events
    emitted by `executor.runner` after each `resolve_for_task` call)
  * headline metrics: retry rate, HITL escalations, p50/p95 task wall time

The audit log is the only required input. `task_status.json` is consulted
opportunistically for `final_status` enrichment; missing/corrupt sidecar
degrades silently — the report still renders without it.

Wall time is task-level (gap between the first and last audit event tagged
with the same `task_id`), not per-LLM-call latency. Per-call timing would
require `llm/client.py` to emit `duration_ms` on every response, which is
out of scope for v1.
"""

from __future__ import annotations

import json
import os
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from runtime.audit.logger import _derive_category
from runtime.llm.providers import pricing_for


@dataclass(frozen=True)
class RoleBreakdown:
    category: str
    entry_count: int
    input_tokens: int
    output_tokens: int
    estimated_cost_usd: float

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


@dataclass(frozen=True)
class TaskAttemptStats:
    task_id: str
    worker_attempts: int
    sandbox_violations: int
    reviewer_rejects: int
    final_status: str | None
    wall_seconds: float | None


@dataclass(frozen=True)
class SkillTrigger:
    skill_name: str
    trigger_count: int
    last_task_id: str | None


@dataclass(frozen=True)
class RetroReport:
    project_id: str
    total_llm_calls: int
    retry_rate: float
    hitl_escalations: int
    per_category: list[RoleBreakdown] = field(default_factory=list)
    per_task: list[TaskAttemptStats] = field(default_factory=list)
    skill_triggers: list[SkillTrigger] = field(default_factory=list)
    wall_seconds_p50: float | None = None
    wall_seconds_p95: float | None = None


def _parse_iso(ts: object) -> datetime | None:
    """Tolerant ISO 8601 parser.

    Returns None for missing / non-string / unparsable inputs. Pre-fix
    audit lines whose timestamp got mangled by the PII redactor (e.g.
    `[PHONE]T13:00:53...`) land here as `None` — the row is still counted
    in token rollups, only its wall_seconds contribution is dropped.
    """
    if not isinstance(ts, str) or not ts:
        return None
    try:
        return datetime.fromisoformat(ts)
    except ValueError:
        return None


def _percentile(values: list[float], p: float) -> float | None:
    if not values:
        return None
    sorted_values = sorted(values)
    if len(sorted_values) == 1:
        return round(sorted_values[0], 3)
    k = (len(sorted_values) - 1) * p
    f_idx = int(k)
    c_idx = min(f_idx + 1, len(sorted_values) - 1)
    if f_idx == c_idx:
        return round(sorted_values[f_idx], 3)
    return round(
        sorted_values[f_idx] * (c_idx - k) + sorted_values[c_idx] * (k - f_idx),
        3,
    )


def _category_cost(
    provider_tokens: dict[str, tuple[int, int]],
) -> float:
    """Sum cost across (provider × input/output) for one category.

    Per-provider pricing is honored so a mixed Anthropic + DeepSeek
    run reports the correct blended USD instead of pricing every row
    at Anthropic's rate.
    """
    total = 0.0
    for provider, (in_t, out_t) in provider_tokens.items():
        in_per_m, out_per_m = pricing_for(provider, "")
        total += (in_t / 1_000_000) * in_per_m
        total += (out_t / 1_000_000) * out_per_m
    return round(total, 6)


def aggregate(
    project_id: str,
    *,
    audit_path: Path | None = None,
    workspace_root: Path | None = None,
) -> RetroReport:
    """Build a RetroReport for `project_id` by reading the audit JSONL.

    Args:
        project_id: matched against the `project_id` field on every audit
            event; non-matching rows are skipped.
        audit_path: override for the audit JSONL (default: $AUDIT_LOG_PATH
            or `./runtime/audit/decisions.jsonl`).
        workspace_root: override for the workspaces dir (default:
            $WORKSPACE_ROOT or `./workspaces`); used to find
            `task_status.json` for `final_status` enrichment.
    """
    audit_path = audit_path or Path(
        os.getenv("AUDIT_LOG_PATH", "./runtime/audit/decisions.jsonl")
    )

    if not audit_path.exists():
        return RetroReport(
            project_id=project_id,
            total_llm_calls=0,
            retry_rate=0.0,
            hitl_escalations=0,
        )

    per_cat_in: dict[str, int] = defaultdict(int)
    per_cat_out: dict[str, int] = defaultdict(int)
    per_cat_count: dict[str, int] = defaultdict(int)
    per_cat_provider: dict[str, dict[str, tuple[int, int]]] = defaultdict(dict)

    per_task_worker_ok: dict[str, int] = defaultdict(int)
    per_task_sandbox: dict[str, int] = defaultdict(int)
    per_task_rejects: dict[str, int] = defaultdict(int)
    per_task_t_first: dict[str, datetime] = {}
    per_task_t_last: dict[str, datetime] = {}

    skill_count: dict[str, int] = defaultdict(int)
    skill_last_task: dict[str, str] = {}

    total_llm_calls = 0

    with audit_path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue

            if entry.get("project_id") != project_id:
                continue

            event = str(entry.get("event") or "")
            # Re-derive from event name rather than trusting the persisted
            # `category` field. The audit log is immutable history; old rows
            # carry whatever categorization rule was active at write time,
            # which `_CATEGORY_PREFIXES` may have since refined. Re-deriving
            # keeps retro output current without rewriting the log.
            category = _derive_category(event)
            task_id = entry.get("task_id")
            ts = _parse_iso(entry.get("timestamp"))

            tokens = entry.get("tokens")
            if isinstance(tokens, dict):
                in_t = int(tokens.get("in", 0) or 0)
                out_t = int(tokens.get("out", 0) or 0)
                if in_t > 0 or out_t > 0:
                    provider = str(entry.get("provider") or "anthropic").lower()
                    per_cat_in[category] += in_t
                    per_cat_out[category] += out_t
                    per_cat_count[category] += 1
                    cur = per_cat_provider[category].get(provider, (0, 0))
                    per_cat_provider[category][provider] = (
                        cur[0] + in_t,
                        cur[1] + out_t,
                    )
                    total_llm_calls += 1

            if task_id:
                if ts is not None:
                    if task_id not in per_task_t_first:
                        per_task_t_first[task_id] = ts
                    per_task_t_last[task_id] = ts

                if event == "worker_output_ok":
                    per_task_worker_ok[task_id] += 1
                elif event == "worker_sandbox_violation":
                    per_task_sandbox[task_id] += 1
                elif event == "reviewer_verdict":
                    if entry.get("approved") is False:
                        per_task_rejects[task_id] += 1

            if event == "executor_skill_resolved":
                names = entry.get("worker_skills") or []
                if isinstance(names, list):
                    for raw in names:
                        name = str(raw)
                        if not name:
                            continue
                        skill_count[name] += 1
                        if task_id:
                            skill_last_task[name] = str(task_id)

    final_status_by_task: dict[str, str] = {}
    hitl_escalations = 0
    if workspace_root is None:
        workspace_root = Path(os.getenv("WORKSPACE_ROOT", "./workspaces"))
    status_path = workspace_root / project_id / "task_status.json"
    if status_path.exists():
        try:
            data = json.loads(status_path.read_text(encoding="utf-8"))
            records = data.get("records") or {}
            for tid, rec in records.items():
                status = str(rec.get("status", "") or "").lower()
                final_status_by_task[str(tid)] = status
                if status == "awaiting_hitl":
                    hitl_escalations += 1
        except (json.JSONDecodeError, OSError):
            pass

    per_category: list[RoleBreakdown] = []
    for cat in sorted(per_cat_in):
        per_category.append(
            RoleBreakdown(
                category=cat,
                entry_count=per_cat_count[cat],
                input_tokens=per_cat_in[cat],
                output_tokens=per_cat_out[cat],
                estimated_cost_usd=_category_cost(per_cat_provider[cat]),
            )
        )

    all_task_ids = (
        set(per_task_worker_ok)
        | set(per_task_sandbox)
        | set(per_task_rejects)
        | set(per_task_t_first)
        | set(final_status_by_task)
    )
    per_task: list[TaskAttemptStats] = []
    wall_seconds_samples: list[float] = []
    for tid in sorted(all_task_ids):
        wall: float | None = None
        if tid in per_task_t_first and tid in per_task_t_last:
            delta = (
                per_task_t_last[tid] - per_task_t_first[tid]
            ).total_seconds()
            wall = round(delta, 3)
            wall_seconds_samples.append(wall)
        per_task.append(
            TaskAttemptStats(
                task_id=tid,
                worker_attempts=per_task_worker_ok.get(tid, 0),
                sandbox_violations=per_task_sandbox.get(tid, 0),
                reviewer_rejects=per_task_rejects.get(tid, 0),
                final_status=final_status_by_task.get(tid),
                wall_seconds=wall,
            )
        )

    # Retry rate: rejections / total attempts. Total attempts includes
    # successful Worker calls + Worker calls that died in the sandbox
    # before reaching review. Reviewer rejections are then a subset of
    # post-sandbox attempts. The ratio captures "what fraction of work
    # had to be re-done".
    total_attempts = sum(
        s.worker_attempts + s.sandbox_violations for s in per_task
    )
    total_rejects = sum(s.sandbox_violations + s.reviewer_rejects for s in per_task)
    retry_rate = round(total_rejects / total_attempts, 4) if total_attempts > 0 else 0.0

    skill_triggers: list[SkillTrigger] = [
        SkillTrigger(
            skill_name=name,
            trigger_count=skill_count[name],
            last_task_id=skill_last_task.get(name),
        )
        for name in sorted(skill_count, key=lambda n: (-skill_count[n], n))
    ]

    return RetroReport(
        project_id=project_id,
        total_llm_calls=total_llm_calls,
        retry_rate=retry_rate,
        hitl_escalations=hitl_escalations,
        per_category=per_category,
        per_task=per_task,
        skill_triggers=skill_triggers,
        wall_seconds_p50=_percentile(wall_seconds_samples, 0.50),
        wall_seconds_p95=_percentile(wall_seconds_samples, 0.95),
    )


def to_json_dict(report: RetroReport) -> dict:
    """Plain-dict serialization for `ortim retro --json`. Stable field
    order so downstream snapshot tests can diff predictably."""
    return {
        "project_id": report.project_id,
        "total_llm_calls": report.total_llm_calls,
        "retry_rate": report.retry_rate,
        "hitl_escalations": report.hitl_escalations,
        "wall_seconds_p50": report.wall_seconds_p50,
        "wall_seconds_p95": report.wall_seconds_p95,
        "per_category": [
            {
                "category": c.category,
                "entry_count": c.entry_count,
                "input_tokens": c.input_tokens,
                "output_tokens": c.output_tokens,
                "estimated_cost_usd": c.estimated_cost_usd,
            }
            for c in report.per_category
        ],
        "per_task": [
            {
                "task_id": t.task_id,
                "worker_attempts": t.worker_attempts,
                "sandbox_violations": t.sandbox_violations,
                "reviewer_rejects": t.reviewer_rejects,
                "final_status": t.final_status,
                "wall_seconds": t.wall_seconds,
            }
            for t in report.per_task
        ],
        "skill_triggers": [
            {
                "skill_name": s.skill_name,
                "trigger_count": s.trigger_count,
                "last_task_id": s.last_task_id,
            }
            for s in report.skill_triggers
        ],
    }
