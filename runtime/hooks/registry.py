# SPDX-License-Identifier: FSL-1.1-Apache-2.0
# Copyright (c) 2026 ortim.dev
"""Hook execution framework.

A hook is a shell command (configured by env var) that runs at a specific
point in the executor lifecycle. We don't try to be a full hook DSL; the
contract is intentionally narrow:

  - exit code 0 → hook passed, runner proceeds
  - any non-zero exit → hook failed, runner blocks the corresponding action
  - hook output (stdout/stderr tail) goes into the audit log

Initial hooks (Faz 6c):
  - `pre_commit` — runs after Reviewer chain approves but before `git commit`.
                   Wires `AI_FACTORY_LINT_CMD` and `AI_FACTORY_FORMAT_CHECK_CMD`.
  - `pre_deploy` — runs when entering DEPLOY_AWAITING_APPROVAL → DONE.
                   Wires `AI_FACTORY_DEPLOY_CMD`.

Hooks are best-effort: if no env command is set, the hook is a no-op (and
audited as such). This keeps current setups working without ceremony.
"""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

from runtime.audit import AuditLogger


@dataclass(frozen=True)
class HookResult:
    name: str
    skipped: bool
    skipped_reason: str = ""
    exit_code: int | None = None
    stdout_tail: str = ""
    stderr_tail: str = ""
    duration_seconds: float = 0.0

    @property
    def passed(self) -> bool:
        if self.skipped:
            return True
        return self.exit_code == 0


# Hook → list of env var names. Multiple commands per hook run sequentially;
# any failure halts the rest. Order matters for pre_commit (lint before
# format check, by convention).
HOOK_COMMANDS: dict[str, tuple[str, ...]] = {
    "pre_commit": ("AI_FACTORY_LINT_CMD", "AI_FACTORY_FORMAT_CHECK_CMD"),
    "pre_deploy": ("AI_FACTORY_DEPLOY_CMD",),
}


def run_hook(
    name: str,
    cwd: Path,
    audit: AuditLogger,
    project_id: str | None = None,
    task_id: str | None = None,
    timeout: float = 300.0,
) -> HookResult:
    """Run all configured commands for `name` in `cwd`. First failure wins."""
    if name not in HOOK_COMMANDS:
        raise ValueError(f"unknown hook: {name}; valid: {list(HOOK_COMMANDS)}")

    if os.getenv("AI_FACTORY_HOOKS_ENABLED", "true").lower() == "false":
        result = HookResult(
            name=name, skipped=True, skipped_reason="hooks disabled via env"
        )
        _log(audit, project_id, task_id, result)
        return result

    cmds: list[tuple[str, str]] = []
    for env_name in HOOK_COMMANDS[name]:
        cmd = os.getenv(env_name, "").strip()
        if cmd:
            cmds.append((env_name, cmd))

    if not cmds:
        result = HookResult(
            name=name,
            skipped=True,
            skipped_reason=(
                f"no commands configured (set "
                f"{' or '.join(HOOK_COMMANDS[name])})"
            ),
        )
        _log(audit, project_id, task_id, result)
        return result

    import time

    for env_name, cmd in cmds:
        t0 = time.monotonic()
        try:
            proc = subprocess.run(
                cmd,
                shell=True,
                cwd=str(cwd),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
            )
        except subprocess.TimeoutExpired as e:
            result = HookResult(
                name=name,
                skipped=False,
                exit_code=124,
                stderr_tail=f"timeout after {timeout}s ({env_name})",
                stdout_tail=(e.stdout or "")[-500:] if e.stdout else "",
                duration_seconds=time.monotonic() - t0,
            )
            _log(audit, project_id, task_id, result)
            return result

        duration = time.monotonic() - t0
        result = HookResult(
            name=name,
            skipped=False,
            exit_code=proc.returncode,
            stdout_tail=(proc.stdout or "")[-500:],
            stderr_tail=(proc.stderr or "")[-500:],
            duration_seconds=duration,
        )
        _log(audit, project_id, task_id, result, env_name=env_name)
        if proc.returncode != 0:
            return result

    return result  # last successful command's result


def _log(
    audit: AuditLogger,
    project_id: str | None,
    task_id: str | None,
    result: HookResult,
    env_name: str | None = None,
) -> None:
    audit.log(
        "hook_event",
        project_id=project_id,
        task_id=task_id,
        hook=result.name,
        env_name=env_name,
        skipped=result.skipped,
        skipped_reason=result.skipped_reason,
        exit_code=result.exit_code,
        duration_seconds=round(result.duration_seconds, 3),
        stderr_tail=result.stderr_tail,
    )
