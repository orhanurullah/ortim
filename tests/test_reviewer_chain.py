# SPDX-License-Identifier: FSL-1.1-Apache-2.0
# Copyright (c) 2026 ortim.dev
"""Smoke tests for the multi-reviewer chain (v0.6b).

We never call a real LLM. A `FakeLLM` returns canned JSON per role so we can
exercise:
  - SecurityVerdict / TestVerdict / PerfVerdict parsing
  - ReviewerChain wiring through `execute_task`
  - Hard veto → task → AWAITING_HITL (no retry)
  - Soft (perf) veto → annotates but does not block
  - Pre-6b call site (no chain passed) still works → 33 prior smoke tests cover
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from ortim.audit import AuditLogger  # noqa: E402
from ortim.executor import (  # noqa: E402
    PerfReviewerAgent,
    PerfVerdict,
    ReviewerChain,
    SecurityReviewerAgent,
    SecurityVerdict,
    TaskStatus,
    TaskStatusFile,
    TestReviewerAgent,
    TestVerdict,
    execute_task,
)
from ortim.executor.worker import FileChange, WorkerOutput  # noqa: E402
from ortim.llm.client import LLMResponse  # noqa: E402
from ortim.memory import MemoryLoader  # noqa: E402
from ortim.orchestrator import TaskSpec  # noqa: E402


class FakeLLM:
    """Replace `LLMClient` with canned responses keyed by detected agent role.

    The Worker prompt asks for `WorkerOutput` JSON; the CodeReviewer prompt
    asks for `ReviewVerdict`; the SecurityReviewer prompt mentions threat
    catalogue, etc. We sniff the system prompt to pick a canned response.
    """

    def __init__(self, canned: dict[str, str]) -> None:
        self.canned = canned
        self.calls: list[tuple[str, str]] = []

    def call(
        self,
        system: str,
        user: str,
        temperature: float = 0.0,
        max_tokens: int = 4096,
    ) -> LLMResponse:
        sys_lower = system.lower()
        if "security reviewer" in sys_lower:
            role = "security"
        elif "test strategist" in sys_lower:
            role = "test"
        elif "performance reviewer" in sys_lower:
            role = "perf"
        elif "code reviewer" in sys_lower:
            role = "code"
        else:
            role = "worker"
        self.calls.append((role, user[:80]))
        text = self.canned.get(role, "{}")
        return LLMResponse(
            text=text,
            input_tokens=100,
            output_tokens=50,
            model="fake-model",
            provider="fake",
        )


def _task() -> TaskSpec:
    return TaskSpec(
        id="T-001",
        title="Add rate limit",
        description="Add token-bucket rate limit to /login",
        module_scope="src/auth",
        rfc_section="§7 Auth",
        dependencies=[],
        acceptance_criteria=[
            "Limit is 5 attempts per minute per IP",
            "Returns 429 when exceeded",
        ],
        estimated_tokens=2000,
    )


def _worker_output_json() -> str:
    """Realistic-shaped output the FakeLLM returns for the Worker call."""
    return json.dumps(
        {
            "task_id": "T-001",
            "summary": "Added rate limiter middleware",
            "files": [
                {
                    "path": "src/auth/rate_limit.py",
                    "content": "# rate limit\nDEF = 5\n",
                    "operation": "create",
                }
            ],
        }
    )


def _setup(canned: dict[str, str]) -> tuple:
    tmp = tempfile.mkdtemp()
    workspace = Path(tmp)
    status_file = TaskStatusFile.load_or_init(workspace, "P1")
    audit = AuditLogger(path=workspace / "audit.jsonl")
    memory = MemoryLoader(REPO_ROOT)
    llm = FakeLLM(canned)
    return workspace, status_file, audit, memory, llm


def _approved_code_verdict() -> str:
    """All-pass rubric verdict matching `_task()`'s acceptance_criteria.

    Phase-0 schema: every criterion needs an explicit pass/fail/partial/
    unverifiable entry. An empty `criteria_verdicts` list yields
    `approved=False`, which breaks downstream chain assertions, so canned
    responses must enumerate the criteria.
    """
    return json.dumps({
        "criteria_verdicts": [
            {
                "criterion": "Limit is 5 attempts per minute per IP",
                "status": "pass",
                "evidence": "rate_limit.py:DEF=5 with per-IP bucket",
            },
            {
                "criterion": "Returns 429 when exceeded",
                "status": "pass",
                "evidence": "middleware returns 429 on bucket exhaustion",
            },
        ],
    })


def test_chain_none_preserves_legacy_behavior() -> None:
    """When ReviewerChain is None, only CodeReviewer runs (no extra LLM calls)."""
    canned = {
        "worker": _worker_output_json(),
        "code": _approved_code_verdict(),
    }
    workspace, status_file, audit, memory, llm = _setup(canned)
    import os
    os.environ["ORTIM_GIT_ENABLED"] = "false"
    try:
        result = execute_task(
            task=_task(),
            rfc_text="dummy RFC",
            project_id="P1",
            workspace=workspace,
            status_file=status_file,
            llm=llm,
            memory=memory,
            audit=audit,
            max_attempts=3,
            reviewer_chain=None,
        )
    finally:
        os.environ.pop("ORTIM_GIT_ENABLED", None)

    assert result.status == TaskStatus.DONE
    # Exactly two LLM calls when no chain: worker + code reviewer.
    roles_called = [r for (r, _) in llm.calls]
    assert roles_called == ["worker", "code"]
    assert result.blocked_by is None
    assert len(result.verdicts) == 1


def test_security_hard_veto_immediately_escalates() -> None:
    canned = {
        "worker": _worker_output_json(),
        "code": _approved_code_verdict(),
        "security": json.dumps({
            "approved": False,
            "severity": "high",
            "reasons": ["src/auth/rate_limit.py:1 — uses md5 for tokens"],
            "suggestions": ["use HMAC-SHA256"],
        }),
        "test": '{"approved": true, "severity": null, "reasons": [], '
                '"suggestions": [], "ac_coverage": []}',
        "perf": '{"approved": true, "severity": null, "reasons": [], '
                '"suggestions": []}',
    }
    workspace, status_file, audit, memory, llm = _setup(canned)
    chain = ReviewerChain(
        security=SecurityReviewerAgent(llm, memory, audit),
        test=TestReviewerAgent(llm, memory, audit),
        perf=PerfReviewerAgent(llm, memory, audit),
    )
    import os
    os.environ["ORTIM_GIT_ENABLED"] = "false"
    try:
        result = execute_task(
            task=_task(), rfc_text="rfc", project_id="P1",
            workspace=workspace, status_file=status_file,
            llm=llm, memory=memory, audit=audit,
            max_attempts=3, reviewer_chain=chain,
        )
    finally:
        os.environ.pop("ORTIM_GIT_ENABLED", None)

    assert result.status == TaskStatus.AWAITING_HITL, (
        f"hard veto must skip retry; got {result.status}"
    )
    assert result.blocked_by == "security"
    # Test reviewer should NOT have been called once Security rejected.
    roles = [r for (r, _) in llm.calls]
    assert "security" in roles
    assert "test" not in roles, "Test reviewer must not run after Security veto"
    # First attempt and already at AWAITING_HITL — no retry budget consumed beyond #1.
    rec = status_file.records["T-001"]
    assert rec.attempts == 1
    # Reasons are tagged with [security].
    assert any("[security]" in r for r in rec.last_review_reasons)


def test_test_hard_veto_after_security_pass() -> None:
    canned = {
        "worker": _worker_output_json(),
        "code": _approved_code_verdict(),
        "security": '{"approved": true, "severity": null, "reasons": [], '
                    '"suggestions": []}',
        "test": json.dumps({
            "approved": False,
            "severity": "high",
            "reasons": ["AC #2 (returns 429) has no test"],
            "suggestions": ["add test_returns_429_on_excess"],
            "ac_coverage": [
                {"ac": "Limit is 5/min/IP", "test": "tests/test_rate_limit.py::test_limit"},
                {"ac": "Returns 429", "test": None},
            ],
        }),
        "perf": '{"approved": true, "severity": null, "reasons": [], '
                '"suggestions": []}',
    }
    workspace, status_file, audit, memory, llm = _setup(canned)
    chain = ReviewerChain(
        security=SecurityReviewerAgent(llm, memory, audit),
        test=TestReviewerAgent(llm, memory, audit),
        perf=PerfReviewerAgent(llm, memory, audit),
    )
    import os
    os.environ["ORTIM_GIT_ENABLED"] = "false"
    try:
        result = execute_task(
            task=_task(), rfc_text="rfc", project_id="P1",
            workspace=workspace, status_file=status_file,
            llm=llm, memory=memory, audit=audit,
            max_attempts=3, reviewer_chain=chain,
        )
    finally:
        os.environ.pop("ORTIM_GIT_ENABLED", None)

    assert result.status == TaskStatus.AWAITING_HITL
    assert result.blocked_by == "test"
    roles = [r for (r, _) in llm.calls]
    assert roles.index("security") < roles.index("test")


def test_perf_only_findings_do_not_block() -> None:
    canned = {
        "worker": _worker_output_json(),
        "code": _approved_code_verdict(),
        "security": '{"approved": true, "severity": null, "reasons": [], '
                    '"suggestions": []}',
        "test": '{"approved": true, "severity": null, "reasons": [], '
                '"suggestions": [], "ac_coverage": []}',
        "perf": json.dumps({
            "approved": False,
            "severity": "medium",
            "reasons": ["src/auth/rate_limit.py:5 — repeated time.time() inside hot loop"],
            "suggestions": ["cache timestamp once per request"],
            "estimated_cost": "low",
        }),
    }
    workspace, status_file, audit, memory, llm = _setup(canned)
    chain = ReviewerChain(
        security=SecurityReviewerAgent(llm, memory, audit),
        test=TestReviewerAgent(llm, memory, audit),
        perf=PerfReviewerAgent(llm, memory, audit),
    )
    import os
    os.environ["ORTIM_GIT_ENABLED"] = "false"
    try:
        result = execute_task(
            task=_task(), rfc_text="rfc", project_id="P1",
            workspace=workspace, status_file=status_file,
            llm=llm, memory=memory, audit=audit,
            max_attempts=3, reviewer_chain=chain,
        )
    finally:
        os.environ.pop("ORTIM_GIT_ENABLED", None)

    assert result.status == TaskStatus.DONE, (
        "Perf is soft-veto only — must not block merge"
    )
    assert result.blocked_by is None
    # Perf finding lands in suggestions with [perf] tag.
    rec = status_file.records["T-001"]
    assert any("[perf]" in s for s in rec.last_review_suggestions)


def test_security_verdict_parses_minimal() -> None:
    raw = '{"approved": false, "severity": "high", "reasons": ["bad"], "suggestions": []}'
    v = SecurityVerdict.model_validate_json(raw)
    assert v.approved is False
    assert v.severity == "high"
    assert v.reviewer == "security"


def test_test_verdict_parses_with_coverage() -> None:
    raw = json.dumps({
        "approved": False,
        "severity": "high",
        "reasons": ["AC #1 missing"],
        "suggestions": ["add it"],
        "ac_coverage": [
            {"ac": "x", "test": "tests/test_x.py::test_x"},
            {"ac": "y", "test": None},
        ],
    })
    v = TestVerdict.model_validate_json(raw)
    assert len(v.ac_coverage) == 2
    assert v.ac_coverage[1].test is None
    assert v.reviewer == "test"


def test_perf_verdict_parses_with_estimated_cost() -> None:
    raw = json.dumps({
        "approved": True,
        "severity": "low",
        "reasons": [],
        "suggestions": ["consider a cache"],
        "estimated_cost": "medium",
    })
    v = PerfVerdict.model_validate_json(raw)
    assert v.estimated_cost == "medium"
    assert v.reviewer == "perf"


# ---------- Phase 0 / item 15 — sandbox feedback in prior_reasons ----------


def _out_of_scope_worker_output_json() -> str:
    """Worker output that writes outside the task's module_scope.

    `_task()` declares `module_scope='src/auth'`; emitting `model/todo.go`
    triggers a SandboxViolation inside `Worker.execute`, which raises
    `WorkerOutOfScope` before the file is written.
    """
    return json.dumps({
        "task_id": "T-001",
        "summary": "Worker tries to re-create a model file from another module",
        "files": [
            {
                "path": "model/todo.go",
                "content": "package model\n\ntype Todo struct {}\n",
                "operation": "create",
            }
        ],
    })


def test_sandbox_violation_populates_prior_reasons_for_next_attempt() -> None:
    """Repro of todo-greenfield-3 T-002 failure: out-of-scope Worker output
    must put a `[sandbox]`-tagged reason into `record.last_review_reasons`
    so the next attempt's Worker call sees concrete feedback in
    `prior_reasons`. Without this fix the auto-retry loop runs three times
    with no feedback and produces identical violations."""
    canned = {
        "worker": _out_of_scope_worker_output_json(),
        "code": _approved_code_verdict(),  # never reached, but harmless
    }
    workspace, status_file, audit, memory, llm = _setup(canned)
    import os
    os.environ["ORTIM_GIT_ENABLED"] = "false"
    try:
        result = execute_task(
            task=_task(),
            rfc_text="dummy",
            project_id="P1",
            workspace=workspace,
            status_file=status_file,
            llm=llm,
            memory=memory,
            audit=audit,
            max_attempts=3,
            reviewer_chain=None,
        )
    finally:
        os.environ.pop("ORTIM_GIT_ENABLED", None)

    assert result.status == TaskStatus.PENDING, (
        "first attempt should land in PENDING with retry budget remaining"
    )
    rec = status_file.records["T-001"]
    assert rec.attempts == 1
    assert rec.last_review_reasons, "sandbox feedback must populate last_review_reasons"
    assert any("[sandbox]" in r for r in rec.last_review_reasons), (
        f"expected [sandbox] tag in reasons; got {rec.last_review_reasons}"
    )
    assert any("module_scope='src/auth/'" in r for r in rec.last_review_reasons)


def test_reviewer_length_mismatch_triggers_retry_then_succeeds() -> None:
    """Phase 0+ length validator: LLM first emits 1-of-2 criteria (dropped
    one — observed in todo-greenfield-4 T-005, 9-of-13). Validator catches,
    retry tells the LLM the expected count, second attempt emits both."""
    from ortim.executor.reviewer import CodeReviewerAgent
    from ortim.executor.worker import FileChange, WorkerOutput

    short_verdict = json.dumps({
        "criteria_verdicts": [
            {
                "criterion": "Limit is 5 attempts per minute per IP",
                "status": "pass",
                "evidence": "rate_limit.py:DEF=5",
            },
        ],  # only 1 — task has 2
    })
    full_verdict = _approved_code_verdict()

    class TwoShotLLM:
        def __init__(self) -> None:
            self.calls: list[str] = []
            self._responses = [short_verdict, full_verdict]

        def call(
            self,
            system: str,
            user: str,
            temperature: float = 0.0,
            max_tokens: int = 4096,
        ) -> LLMResponse:
            self.calls.append(user[:200])
            text = self._responses.pop(0) if self._responses else full_verdict
            return LLMResponse(
                text=text,
                input_tokens=10,
                output_tokens=5,
                model="fake",
                provider="fake",
            )

    tmp = tempfile.mkdtemp()
    audit = AuditLogger(path=Path(tmp) / "audit.jsonl")
    memory = MemoryLoader(REPO_ROOT)
    llm = TwoShotLLM()
    agent = CodeReviewerAgent(llm, memory, audit)
    output = WorkerOutput(
        task_id="T-001",
        summary="x",
        files=[FileChange(path="src/auth/x.py", content="pass\n", operation="create")],
    )

    verdict = agent.review(
        task=_task(),
        worker_output=output,
        rfc_text="rfc",
        project_id="P1",
    )

    assert len(verdict.criteria_verdicts) == 2
    assert verdict.approved is True
    assert len(llm.calls) == 2, "validator should have triggered exactly one retry"
    # Retry prompt must include the structured correction message.
    assert "EXACTLY 2 acceptance criteria" in llm.calls[1] or \
           "emitted 1 criterion verdicts" in llm.calls[1]


def test_reviewer_length_mismatch_three_strikes_raises() -> None:
    """Three consecutive count mismatches → RuntimeError (operator must
    investigate; retrying further is wasted budget)."""
    from ortim.executor.reviewer import CodeReviewerAgent
    from ortim.executor.worker import FileChange, WorkerOutput

    short_verdict = json.dumps({
        "criteria_verdicts": [
            {"criterion": "x", "status": "pass", "evidence": "y"},
        ],
    })

    class AlwaysShortLLM:
        def __init__(self) -> None:
            self.call_count = 0

        def call(
            self,
            system: str,
            user: str,
            temperature: float = 0.0,
            max_tokens: int = 4096,
        ) -> LLMResponse:
            self.call_count += 1
            return LLMResponse(
                text=short_verdict,
                input_tokens=10,
                output_tokens=5,
                model="fake",
                provider="fake",
            )

    tmp = tempfile.mkdtemp()
    audit = AuditLogger(path=Path(tmp) / "audit.jsonl")
    memory = MemoryLoader(REPO_ROOT)
    llm = AlwaysShortLLM()
    agent = CodeReviewerAgent(llm, memory, audit)
    output = WorkerOutput(
        task_id="T-001",
        summary="x",
        files=[FileChange(path="src/auth/x.py", content="pass\n", operation="create")],
    )

    import pytest
    with pytest.raises(RuntimeError, match="CodeReviewer failed"):
        agent.review(
            task=_task(),
            worker_output=output,
            rfc_text="rfc",
            project_id="P1",
        )
    assert llm.call_count == CodeReviewerAgent.MAX_RETRIES


def test_sandbox_violation_third_attempt_escalates_to_hitl() -> None:
    """Three sandbox violations exhaust retry budget and escalate to AWAITING_HITL."""
    canned = {
        "worker": _out_of_scope_worker_output_json(),
        "code": _approved_code_verdict(),
    }
    workspace, status_file, audit, memory, llm = _setup(canned)
    import os
    os.environ["ORTIM_GIT_ENABLED"] = "false"
    try:
        for _ in range(3):
            result = execute_task(
                task=_task(),
                rfc_text="dummy",
                project_id="P1",
                workspace=workspace,
                status_file=status_file,
                llm=llm,
                memory=memory,
                audit=audit,
                max_attempts=3,
                reviewer_chain=None,
            )
    finally:
        os.environ.pop("ORTIM_GIT_ENABLED", None)

    assert result.status == TaskStatus.AWAITING_HITL
    rec = status_file.records["T-001"]
    assert rec.attempts == 3
    # Worker was called three times with out-of-scope output; check that the
    # second and third Worker prompts included prior_reasons with [sandbox].
    worker_calls = [u for (r, u) in llm.calls if r == "worker"]
    assert len(worker_calls) == 3
    # The user prompt sent to the Worker on retries should mention prior reasons.
    # FakeLLM stores only the first 80 chars; we can't grep prior_reasons text
    # from the trimmed user_prompt directly, so we verify the structural
    # invariant via the record state instead.
    assert any("[sandbox]" in r for r in rec.last_review_reasons)


if __name__ == "__main__":
    tests = [
        test_chain_none_preserves_legacy_behavior,
        test_security_hard_veto_immediately_escalates,
        test_test_hard_veto_after_security_pass,
        test_perf_only_findings_do_not_block,
        test_security_verdict_parses_minimal,
        test_test_verdict_parses_with_coverage,
        test_perf_verdict_parses_with_estimated_cost,
        test_sandbox_violation_populates_prior_reasons_for_next_attempt,
        test_sandbox_violation_third_attempt_escalates_to_hitl,
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
