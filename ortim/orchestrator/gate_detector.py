# SPDX-License-Identifier: FSL-1.1-Apache-2.0
# Copyright (c) 2026 ortim.dev
"""HITL gate detectors — pure functions over DAG / WorkerOutput / audit log.

Each detector returns evidence (which task/file/keyword tripped it) so the
caller can either route the project to the matching `*_AWAITING_APPROVAL`
state, or annotate the task with a [g4]/[g5] tag without blocking the run.

Design choice: detection is regex/string-based, not LLM-based. A false
positive is cheap (one human glance to dismiss); a false negative on schema
or external integration is expensive (silent prod migration, surprise SaaS
bill).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

from ortim.orchestrator.task_dag import TaskDAG, TaskSpec

if TYPE_CHECKING:
    # `ortim.executor.worker` imports from `ortim.orchestrator`, so we
    # avoid a runtime import here to break the cycle. Detectors duck-type the
    # `WorkerOutput` argument (only `.files[i].content` / `.path` are used).
    from ortim.executor.worker import WorkerOutput


# ---- G3 — Schema / migration -------------------------------------------------

_SCHEMA_KEYWORDS = (
    r"\bmigration\b",
    r"\bmigrate\b",
    r"\bDDL\b",
    r"\bCREATE TABLE\b",
    r"\bALTER TABLE\b",
    r"\bDROP TABLE\b",
    r"\bschema change\b",
    r"\bAlembic\b",
    r"\bFlyway\b",
    r"\bLiquibase\b",
    r"\bprisma migrate\b",
    r"\bdjango migrate\b",
    r"\bgolang-migrate\b",
)
_SCHEMA_RE = re.compile("|".join(_SCHEMA_KEYWORDS), re.IGNORECASE)

# Common module-scope hints that DAG generators use for migrations.
_SCHEMA_PATH_HINTS = ("migration", "migrations", "alembic", "flyway", "prisma/migrations")


def _task_is_schema(task: TaskSpec) -> bool:
    haystack = f"{task.title}\n{task.description}\n{task.module_scope}"
    if _SCHEMA_RE.search(haystack):
        return True
    scope_lower = task.module_scope.lower().replace("\\", "/")
    return any(hint in scope_lower for hint in _SCHEMA_PATH_HINTS)


@dataclass(frozen=True)
class SchemaGateEvidence:
    task_ids: tuple[str, ...]

    @property
    def triggered(self) -> bool:
        return bool(self.task_ids)


def detect_schema_tasks(dag: TaskDAG) -> SchemaGateEvidence:
    """Return the IDs of any task whose title/description/scope smells like
    a schema migration. Empty tuple = no G3 gate needed."""
    hits = tuple(t.id for t in dag.tasks if _task_is_schema(t))
    return SchemaGateEvidence(task_ids=hits)


# ---- G4 — External integration -----------------------------------------------

# Conservative list — extend as new SDKs become common. Hits trigger a
# task-level AWAITING_HITL the first time a Worker output introduces them.
_EXTERNAL_IMPORTS = (
    # Cloud SDKs
    r"\bimport\s+boto3\b",
    r"\bfrom\s+boto3\b",
    r"\bimport\s+google\.cloud\b",
    r"\bfrom\s+google\.cloud\b",
    r"\bimport\s+azure\.\w+\b",
    r"\bfrom\s+azure\.\w+\b",
    # HTTP clients pointed at external hosts
    r"\bimport\s+requests\b",
    r"\bfrom\s+requests\b",
    r"\bimport\s+httpx\b",
    r"\bfrom\s+httpx\b",
    r"@aws-sdk/",
    r"\bfetch\(",
    r"\baxios\b",
    # Payment / messaging / identity
    r"\bstripe\b",
    r"\btwilio\b",
    r"\bsendgrid\b",
    r"\bauth0\b",
    r"\bfirebase\b",
    # OpenAI/Anthropic etc. (worth flagging)
    r"\bopenai\b",
    r"\banthropic\b",
)
_EXTERNAL_RE = re.compile("|".join(_EXTERNAL_IMPORTS), re.IGNORECASE)

_URL_RE = re.compile(r"https?://[a-z0-9.-]+", re.IGNORECASE)
_LOCAL_HOSTS = ("localhost", "127.0.0.1", "0.0.0.0", "::1", "host.docker.internal")


@dataclass(frozen=True)
class ExternalGateEvidence:
    matches: tuple[tuple[str, str], ...]  # (file_path, snippet)

    @property
    def triggered(self) -> bool:
        return bool(self.matches)


def detect_external_calls(worker_output: "WorkerOutput") -> ExternalGateEvidence:
    """Scan emitted file content for external SDK imports or non-local URLs."""
    matches: list[tuple[str, str]] = []
    for f in worker_output.files:
        for m in _EXTERNAL_RE.finditer(f.content):
            snippet = _line_around(f.content, m.start())
            matches.append((f.path, snippet))
        for m in _URL_RE.finditer(f.content):
            host = m.group(0).split("://", 1)[1].split("/", 1)[0].lower()
            if any(local in host for local in _LOCAL_HOSTS):
                continue
            snippet = _line_around(f.content, m.start())
            matches.append((f.path, snippet))
    return ExternalGateEvidence(matches=tuple(matches))


def _line_around(content: str, idx: int, max_len: int = 120) -> str:
    line_start = content.rfind("\n", 0, idx) + 1
    line_end = content.find("\n", idx)
    if line_end == -1:
        line_end = len(content)
    line = content[line_start:line_end].strip()
    if len(line) > max_len:
        line = line[:max_len] + "…"
    return line


# ---- G5 — Security severity --------------------------------------------------

@dataclass(frozen=True)
class SecurityGateEvidence:
    severity: str | None
    reasons: tuple[str, ...]

    @property
    def triggered(self) -> bool:
        return self.severity in ("high", "medium")


def detect_security_severity(verdict) -> SecurityGateEvidence:
    """Wrap a SecurityVerdict for G5 routing. Accepts the duck-typed verdict
    so this module doesn't import the executor (avoids a cycle)."""
    if verdict is None:
        return SecurityGateEvidence(severity=None, reasons=())
    severity = getattr(verdict, "severity", None)
    reasons = tuple(getattr(verdict, "reasons", ()) or ())
    return SecurityGateEvidence(severity=severity, reasons=reasons)


# ---- G7 — Budget cap ---------------------------------------------------------

@dataclass(frozen=True)
class BudgetGateEvidence:
    project_id: str
    spent_usd: float
    cap_usd: float

    @property
    def triggered(self) -> bool:
        return self.spent_usd >= self.cap_usd

    @property
    def overage_pct(self) -> float:
        if self.cap_usd <= 0:
            return 0.0
        return round((self.spent_usd / self.cap_usd) * 100, 1)


def detect_budget_breach(tracker, project_id: str, cap_usd: float) -> BudgetGateEvidence:
    """`tracker` is a BudgetTracker. Returns evidence with `triggered=True`
    if accumulated spend has reached or exceeded `cap_usd`."""
    report = tracker.report(project_id)
    return BudgetGateEvidence(
        project_id=project_id,
        spent_usd=report.estimated_cost_usd,
        cap_usd=cap_usd,
    )
