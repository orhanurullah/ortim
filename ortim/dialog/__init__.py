# SPDX-License-Identifier: FSL-1.1-Apache-2.0
# Copyright (c) 2026 ortim.dev
"""Dialog artifact storage for M2 conversational intake.

Three artifacts live under `<workspace>/`:
  - `intent.md`        — IntentAnalyst output (refined intent summary)
  - `stack.json`       — StackAnalyst output (LockedStack JSON, the
                         structural single source of truth)
  - `stack.md`         — rendered view of stack.json, written for the
                         user's reading; ignored by downstream layers
  - `PRD.md`           — PRDAnalyst output (legacy path, also used by
                         the non-dialog flow)

Per-state turn history lives under `<workspace>/.dialog/<state>_turns.jsonl`
so we can enforce the per-state turn cap (`ORTIM_DIALOG_TURN_CAP`,
default 10) without re-reading every audit event.
"""

from ortim.dialog.storage import (
    DIALOG_MODE_ENV,
    DIALOG_TURN_CAP_DEFAULT,
    DIALOG_TURN_CAP_ENV,
    DialogTurn,
    append_dialog_turn,
    count_dialog_turns,
    dialog_mode_on,
    load_current_artifact,
    load_intent_md,
    load_locked_stack,
    load_prd_md,
    load_prev_snapshot,
    save_intent_md,
    save_locked_stack,
    save_prd_md,
    snapshot_current_artifact,
    turn_cap,
)

__all__ = [
    "DIALOG_MODE_ENV",
    "DIALOG_TURN_CAP_DEFAULT",
    "DIALOG_TURN_CAP_ENV",
    "DialogTurn",
    "append_dialog_turn",
    "count_dialog_turns",
    "dialog_mode_on",
    "load_current_artifact",
    "load_intent_md",
    "load_locked_stack",
    "load_prd_md",
    "load_prev_snapshot",
    "save_intent_md",
    "save_locked_stack",
    "save_prd_md",
    "snapshot_current_artifact",
    "turn_cap",
]
