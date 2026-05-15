# SPDX-License-Identifier: FSL-1.1-Apache-2.0
# Copyright (c) 2026 ortim.dev
"""Dialog artifact + turn-history persistence.

Keeps the workspace shape obvious so the CLI commands (`refine`, `lock`,
`show`) stay thin. Every helper is idempotent or append-only — no
in-place mutation outside the artifact files themselves.
"""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from pydantic import BaseModel

from runtime.architecture import LockedStack
from runtime.orchestrator.state_machine import ProjectState

DIALOG_MODE_ENV = "AI_FACTORY_DIALOG_MODE"
DIALOG_TURN_CAP_ENV = "AI_FACTORY_DIALOG_TURN_CAP"
DIALOG_TURN_CAP_DEFAULT = 10

_DIALOG_STATES = frozenset(
    {
        ProjectState.INTAKE_DIALOG,
        ProjectState.STACK_DIALOG,
        ProjectState.PRD_DIALOG,
    }
)


def dialog_mode_on() -> bool:
    """Default on. Operators opt out via `AI_FACTORY_DIALOG_MODE=off`."""
    raw = os.getenv(DIALOG_MODE_ENV, "on").strip().lower()
    return raw not in ("0", "off", "false", "no")


def turn_cap() -> int:
    """Per-state cap on refine turns before the CLI requires --force."""
    raw = os.getenv(DIALOG_TURN_CAP_ENV)
    if raw is None:
        return DIALOG_TURN_CAP_DEFAULT
    try:
        value = int(raw)
    except ValueError:
        return DIALOG_TURN_CAP_DEFAULT
    return max(1, value)


# ---- artifact paths ------------------------------------------------------


def _intent_path(workspace: Path) -> Path:
    return workspace / "intent.md"


def _stack_json_path(workspace: Path) -> Path:
    return workspace / "stack.json"


def _stack_md_path(workspace: Path) -> Path:
    return workspace / "stack.md"


def _prd_path(workspace: Path) -> Path:
    return workspace / "PRD.md"


def _dialog_dir(workspace: Path) -> Path:
    return workspace / ".dialog"


def _turns_path(workspace: Path, state: ProjectState) -> Path:
    key = state.value.replace("_dialog", "")  # intake | stack | prd
    return _dialog_dir(workspace) / f"{key}_turns.jsonl"


def _prev_path(workspace: Path, state: ProjectState) -> Path:
    """Snapshot of the artifact as it was BEFORE the most recent refine.
    `ortim lock` diffs against this to show the user what the final turn
    changed; absent on the very first draft."""
    key = state.value.replace("_dialog", "")
    return _dialog_dir(workspace) / f"{key}_prev.md"


def _state_to_artifact_path(workspace: Path, state: ProjectState) -> Path:
    if state == ProjectState.INTAKE_DIALOG:
        return _intent_path(workspace)
    if state == ProjectState.STACK_DIALOG:
        return _stack_md_path(workspace)
    if state == ProjectState.PRD_DIALOG:
        return _prd_path(workspace)
    raise ValueError(f"{state.value} is not a dialog state")


def snapshot_current_artifact(workspace: Path, state: ProjectState) -> bool:
    """Copy the current artifact (intent.md / stack.md / PRD.md) into
    `.dialog/<state>_prev.md` so the next `lock` can diff against it.

    Returns True if a snapshot was taken (artifact existed), False
    otherwise. Should be called BEFORE writing the new turn's artifact.
    """
    artifact = _state_to_artifact_path(workspace, state)
    if not artifact.exists():
        return False
    _dialog_dir(workspace).mkdir(parents=True, exist_ok=True)
    _prev_path(workspace, state).write_text(
        artifact.read_text(encoding="utf-8"), encoding="utf-8"
    )
    return True


def load_prev_snapshot(workspace: Path, state: ProjectState) -> str | None:
    path = _prev_path(workspace, state)
    if not path.exists():
        return None
    return path.read_text(encoding="utf-8")


def load_current_artifact(workspace: Path, state: ProjectState) -> str | None:
    path = _state_to_artifact_path(workspace, state)
    if not path.exists():
        return None
    return path.read_text(encoding="utf-8")


# ---- artifact I/O --------------------------------------------------------


def save_intent_md(workspace: Path, md: str) -> Path:
    workspace.mkdir(parents=True, exist_ok=True)
    path = _intent_path(workspace)
    path.write_text(md, encoding="utf-8")
    return path


def load_intent_md(workspace: Path) -> str | None:
    path = _intent_path(workspace)
    if not path.exists():
        return None
    return path.read_text(encoding="utf-8")


def save_locked_stack(workspace: Path, stack: LockedStack) -> tuple[Path, Path]:
    """Write stack.json (structured, for downstream layers) and stack.md
    (human-readable, for `ortim show`). Returns both paths."""
    workspace.mkdir(parents=True, exist_ok=True)
    json_path = _stack_json_path(workspace)
    json_path.write_text(stack.model_dump_json(indent=2), encoding="utf-8")
    md_path = _stack_md_path(workspace)
    md_path.write_text(stack.to_markdown(), encoding="utf-8")
    return json_path, md_path


def load_locked_stack(workspace: Path) -> LockedStack | None:
    path = _stack_json_path(workspace)
    if not path.exists():
        return None
    return LockedStack.model_validate_json(path.read_text(encoding="utf-8"))


def save_prd_md(workspace: Path, md: str) -> Path:
    workspace.mkdir(parents=True, exist_ok=True)
    path = _prd_path(workspace)
    path.write_text(md, encoding="utf-8")
    return path


def load_prd_md(workspace: Path) -> str | None:
    path = _prd_path(workspace)
    if not path.exists():
        return None
    return path.read_text(encoding="utf-8")


# ---- turn history --------------------------------------------------------


class DialogTurn(BaseModel):
    timestamp: str
    state: ProjectState
    turn_n: int
    feedback_hash: str
    response_hash: str
    had_feedback: bool


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256_short(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def append_dialog_turn(
    workspace: Path,
    state: ProjectState,
    user_feedback: str | None,
    response_text: str,
) -> DialogTurn:
    """Append a turn to the per-state jsonl. The caller must verify the
    state is a dialog state — non-dialog states raise ValueError."""
    if state not in _DIALOG_STATES:
        raise ValueError(
            f"{state.value} is not a dialog state; "
            "append_dialog_turn only accepts INTAKE_DIALOG / STACK_DIALOG / PRD_DIALOG"
        )

    _dialog_dir(workspace).mkdir(parents=True, exist_ok=True)
    path = _turns_path(workspace, state)

    next_n = count_dialog_turns(workspace, state) + 1
    feedback_text = (user_feedback or "").strip()
    turn = DialogTurn(
        timestamp=_utc_now(),
        state=state,
        turn_n=next_n,
        feedback_hash=_sha256_short(feedback_text) if feedback_text else "",
        response_hash=_sha256_short(response_text),
        had_feedback=bool(feedback_text),
    )
    with path.open("a", encoding="utf-8") as f:
        f.write(turn.model_dump_json() + "\n")
    return turn


def count_dialog_turns(workspace: Path, state: ProjectState) -> int:
    """Count how many turns the user has spent in this dialog state.
    Missing file = 0. Corrupt lines are skipped silently — a malformed
    jsonl shouldn't crash the cap check."""
    if state not in _DIALOG_STATES:
        return 0
    path = _turns_path(workspace, state)
    if not path.exists():
        return 0
    count = 0
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                json.loads(line)
                count += 1
            except json.JSONDecodeError:
                continue
    return count
