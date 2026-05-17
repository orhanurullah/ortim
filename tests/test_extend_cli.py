# SPDX-License-Identifier: FSL-1.1-Apache-2.0
# Copyright (c) 2026 ortim.dev
"""M3.1.0d — `_initiate_extend_prd` helper + `_list_extensions` CLI logic.

These tests exercise the CLI's underlying functions directly (FakeLLM,
no typer runner). The full happy path:

    DONE → EXTEND_DIALOG → EXTEND_PRD_DIALOG → EXTEND_PRD_AWAITING_APPROVAL

with audit events `extend_initiated` + `extend_prd_delta_drafted` and a
new section appended to PRD.md.

Counter-example: BLOCKED-STACK marker leaves state at EXTEND_PRD_DIALOG
and does NOT append to PRD.md.
"""

from __future__ import annotations

import json
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from ortim.architecture import LockedStack  # noqa: E402
from ortim.audit import AuditLogger  # noqa: E402
from ortim.extend import BLOCKED_STACK_MARKER, section_cycles_in  # noqa: E402
from ortim.llm.client import LLMResponse  # noqa: E402
from ortim.main import _initiate_extend_prd, _list_extensions  # noqa: E402
from ortim.memory import MemoryLoader  # noqa: E402
from ortim.orchestrator import Project, ProjectState  # noqa: E402


@dataclass
class SequentialFakeLLM:
    """Returns canned responses in order; used to drive Babel + Extender
    in one helper call (Babel runs first, then Extender)."""

    responses: list[str]
    calls: list[tuple[str, str]] = field(default_factory=list)
    _idx: int = 0

    def call(
        self,
        system: str,
        user: str,
        temperature: float = 0.0,
        max_tokens: int = 4096,
    ) -> LLMResponse:
        self.calls.append((system, user))
        text = self.responses[self._idx]
        self._idx += 1
        return LLMResponse(
            text=text,
            input_tokens=10,
            output_tokens=5,
            model="fake-model",
            provider="fake",
        )


def _setup_done_project(tmp_path: Path) -> tuple[Project, Path]:
    """Build a workspace mimicking a shipped DONE project: state.json,
    intent.md, PRD.md, RFC.md, stack.json all present."""
    workspace_root = tmp_path / "workspaces"
    workspace_root.mkdir()

    project = Project(
        name="web-todo-fixture", initial_brief_tr="Bir todo uygulaması istiyorum"
    )
    project.save(workspace_root)
    workspace = Project.workspace_path(project.id, workspace_root)

    # Walk through all transitions to DONE so the state is legitimate.
    chain = [
        ProjectState.BABEL_PROCESSING,
        ProjectState.PRD_DRAFTING,
        ProjectState.MVP_SCOPE_LOCKING,
        ProjectState.PRD_AWAITING_APPROVAL,
        ProjectState.PRD_APPROVED,
        ProjectState.RFC_DRAFTING,
        ProjectState.RFC_AWAITING_APPROVAL,
        ProjectState.RFC_APPROVED,
        ProjectState.TASKS_GENERATING,
        ProjectState.TASKS_READY,
        ProjectState.EXECUTING,
        ProjectState.DONE,
    ]
    for s in chain:
        project.transition(s, actor="fixture", note="setup")
    project.save(workspace_root)

    (workspace / "intent.md").write_text(
        "# Project Intent\n\n## Goal\nA personal todo app with browser persistence.\n",
        encoding="utf-8",
    )
    (workspace / "PRD.md").write_text(
        "# PRD: web-todo\n\n## 1. Problem\nUsers need offline todos.\n\n"
        "## 6. Acceptance Criteria\n- App renders task list\n",
        encoding="utf-8",
    )
    (workspace / "RFC.md").write_text(
        "# RFC: web-todo\n\n## 4. Tech Stack\n"
        "- **Language:** TypeScript\n- **Key libraries:** idb, zod\n",
        encoding="utf-8",
    )
    stack = LockedStack(
        tier="T2",
        app_class="web",
        language="TypeScript",
        primary_framework="React + Vite",
        package_manager="npm",
        test_cmd="npx vitest run",
        run_cmd="npm run dev",
        key_libraries=["idb", "zod"],
    )
    (workspace / "stack.json").write_text(stack.model_dump_json(), encoding="utf-8")

    return project, workspace


def _babel_response_json() -> str:
    """A valid StructuredIntent JSON for the Babel call mocking."""
    return json.dumps(
        {
            "goal": "Add tagging to tasks so users can categorize their todos",
            "target_users": ["solo developer"],
            "must_have_features": ["user can add a tag to a task"],
            "explicit_non_goals": [],
            "constraints": ["browser-only persistence"],
        }
    )


def _delta_prd_section(cycle: int) -> str:
    return (
        f"## Extension {cycle} — Tagging\n\n"
        "### Goal\nAdd tags to tasks.\n\n"
        "### Acceptance Criteria\n- Tag chip appears next to task title\n"
    )


# ---- Happy path ----


def test_initiate_extend_prd_drives_state_and_writes_section(
    tmp_path: Path, monkeypatch
) -> None:
    project, workspace = _setup_done_project(tmp_path)
    # Patch WORKSPACE_ROOT so the helper saves into our tmp tree.
    import ortim.main as main_mod

    monkeypatch.setattr(main_mod, "WORKSPACE_ROOT", tmp_path / "workspaces")

    audit_path = tmp_path / "audit.jsonl"
    audit = AuditLogger(path=audit_path)
    memory = MemoryLoader(REPO_ROOT)

    # Babel response first (StructuredIntent JSON), then Extender response
    # (delta PRD section). Babel's round_trip is NOT called by the helper,
    # only extract().
    llm = SequentialFakeLLM(
        responses=[_babel_response_json(), _delta_prd_section(cycle=1)]
    )

    cycle, blocked = _initiate_extend_prd(
        project=project,
        brief="Add tagging to tasks",
        workspace=workspace,
        audit=audit,
        memory=memory,
        extender_llm=llm,
        babel_llm=llm,
    )

    # Cycle is 1 (no prior extensions in PRD.md).
    assert cycle == 1
    assert blocked is None

    # State advanced to G1 (cycle).
    assert project.state == ProjectState.EXTEND_PRD_AWAITING_APPROVAL

    # PRD.md gained the new section.
    final_prd = (workspace / "PRD.md").read_text(encoding="utf-8")
    assert "## Extension 1 — Tagging" in final_prd
    assert section_cycles_in(final_prd) == [1]

    # Delta intent persisted under extensions/cycle_1/.
    delta_intent = workspace / "extensions" / "cycle_1" / "intent.json"
    assert delta_intent.exists()
    parsed = json.loads(delta_intent.read_text(encoding="utf-8"))
    assert parsed["cycle"] == 1
    assert parsed["parent_project_id"] == project.id
    assert "tagging" in parsed["goal"].lower()

    # Audit: extend_initiated + extend_prd_delta_drafted both fired.
    log_lines = audit_path.read_text(encoding="utf-8").splitlines()
    events = [json.loads(line)["event"] for line in log_lines]
    assert "extend_initiated" in events
    assert "extend_prd_delta_drafted" in events


def test_initiate_extend_prd_increments_cycle_on_second_call(
    tmp_path: Path, monkeypatch
) -> None:
    """Second extend cycle on the same project must produce cycle=2 and
    coexist with cycle 1 in PRD.md."""
    project, workspace = _setup_done_project(tmp_path)
    import ortim.main as main_mod

    monkeypatch.setattr(main_mod, "WORKSPACE_ROOT", tmp_path / "workspaces")

    audit = AuditLogger(path=tmp_path / "audit.jsonl")
    memory = MemoryLoader(REPO_ROOT)

    # First cycle.
    llm1 = SequentialFakeLLM(
        responses=[_babel_response_json(), _delta_prd_section(cycle=1)]
    )
    cycle1, _ = _initiate_extend_prd(
        project=project,
        brief="Add tagging",
        workspace=workspace,
        audit=audit,
        memory=memory,
        extender_llm=llm1,
        babel_llm=llm1,
    )
    assert cycle1 == 1

    # Approve cycle 1 to return to a state that allows extend.
    project.transition(ProjectState.EXTEND_PRD_APPROVED, actor="test")
    # Walk back to DONE via the chain (skip RFC + DAG for fixture brevity
    # — we're testing the cycle counter, not the full pipeline).
    # Easiest: just skip directly via a fresh setup + manual state adjust.
    # Instead, set state directly for the test fixture:
    project.state = ProjectState.DONE
    project.save(tmp_path / "workspaces")

    # Second cycle.
    llm2 = SequentialFakeLLM(
        responses=[_babel_response_json(), _delta_prd_section(cycle=2)]
    )
    cycle2, _ = _initiate_extend_prd(
        project=project,
        brief="Add due dates",
        workspace=workspace,
        audit=audit,
        memory=memory,
        extender_llm=llm2,
        babel_llm=llm2,
    )
    assert cycle2 == 2
    assert section_cycles_in((workspace / "PRD.md").read_text(encoding="utf-8")) == [
        1,
        2,
    ]


# ---- BLOCKED-STACK escape hatch ----


def test_initiate_extend_prd_blocked_stack_does_not_append_or_advance(
    tmp_path: Path, monkeypatch
) -> None:
    """When ExtenderAgent emits the BLOCKED-STACK marker, the helper
    must:
    - return (cycle, blocked_lib_name)
    - leave PRD.md unchanged (no new ## Extension section)
    - leave project state at EXTEND_PRD_DIALOG (NOT advance to G1)
    """
    project, workspace = _setup_done_project(tmp_path)
    import ortim.main as main_mod

    monkeypatch.setattr(main_mod, "WORKSPACE_ROOT", tmp_path / "workspaces")

    audit = AuditLogger(path=tmp_path / "audit.jsonl")
    memory = MemoryLoader(REPO_ROOT)

    blocked_response = (
        f"{BLOCKED_STACK_MARKER}: lodash — feature requires deep object diffing"
    )
    llm = SequentialFakeLLM(
        responses=[_babel_response_json(), blocked_response]
    )

    original_prd = (workspace / "PRD.md").read_text(encoding="utf-8")

    cycle, blocked = _initiate_extend_prd(
        project=project,
        brief="add deep undo with lodash",
        workspace=workspace,
        audit=audit,
        memory=memory,
        extender_llm=llm,
        babel_llm=llm,
    )

    assert cycle == 1
    assert blocked == "lodash"

    # PRD.md untouched.
    assert (workspace / "PRD.md").read_text(encoding="utf-8") == original_prd

    # State stuck at EXTEND_PRD_DIALOG (NOT advanced to G1).
    assert project.state == ProjectState.EXTEND_PRD_DIALOG


# ---- _list_extensions ----


# ---- _extract_extension_section + _extension_feature_title ----


def test_extract_extension_section_returns_full_block_until_next_h2() -> None:
    from ortim.main import _extract_extension_section

    text = (
        "# RFC\n\n"
        "## 1. Problem\nBase.\n\n"
        "## Extension 1 — Tagging\n\n"
        "### Goal\nAdd tags.\n\n"
        "### Module Breakdown (delta)\n| `tagging` | new |\n\n"
        "## Extension 2 — Due dates\n\n"
        "### Goal\nDates.\n"
    )
    out1 = _extract_extension_section(text, cycle=1)
    assert out1 is not None
    assert out1.startswith("## Extension 1 — Tagging")
    assert "## Extension 2" not in out1
    assert "Module Breakdown (delta)" in out1

    out2 = _extract_extension_section(text, cycle=2)
    assert out2 is not None
    assert out2.startswith("## Extension 2 — Due dates")
    assert "Dates" in out2


def test_extract_extension_section_returns_none_when_cycle_missing() -> None:
    from ortim.main import _extract_extension_section

    text = "# RFC\n\n## 1. Problem\n\n## Extension 1 — Foo\n"
    assert _extract_extension_section(text, cycle=2) is None


def test_extension_feature_title_parses_em_dash_hyphen_colon() -> None:
    from ortim.main import _extension_feature_title

    em = "## Extension 1 — Tagging\n### Goal\n..."
    hy = "## Extension 1 - Due dates\n### Goal\n..."
    co = "## Extension 1: Bulk delete\n### Goal\n..."
    bare = "## Extension 1\n### Goal\n..."

    assert _extension_feature_title(em) == "Tagging"
    assert _extension_feature_title(hy) == "Due dates"
    assert _extension_feature_title(co) == "Bulk delete"
    assert _extension_feature_title(bare, fallback="X") == "X"


def test_list_extensions_empty_when_no_sections(tmp_path: Path) -> None:
    project, workspace = _setup_done_project(tmp_path)
    rows = _list_extensions(workspace)
    assert rows == []


def test_list_extensions_returns_cycle_and_header(tmp_path: Path) -> None:
    project, workspace = _setup_done_project(tmp_path)
    prd_path = workspace / "PRD.md"
    prd_path.write_text(
        prd_path.read_text(encoding="utf-8")
        + "\n\n"
        + _delta_prd_section(1)
        + "\n"
        + _delta_prd_section(2),
        encoding="utf-8",
    )
    rows = _list_extensions(workspace)
    assert [c for c, _ in rows] == [1, 2]
    assert all(h.startswith("## Extension") for _, h in rows)
