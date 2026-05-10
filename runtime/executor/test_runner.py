# SPDX-License-Identifier: FSL-1.1-Apache-2.0
# Copyright (c) 2026 ortim.dev
"""Run a configurable test command on the workspace before review.

Opt-in via `AI_FACTORY_TEST_CMD` (e.g. `"pytest -q"`, `"npm test --silent"`),
or — Phase 0 (M1.5+) — via a workspace-local `.ai-factory.env` file written
by the bootstrap layer at scaffolding time. The file format is one
`KEY=VALUE` per line, comments with `#`. Env var wins over file when both
are set.

We deliberately avoid filesystem auto-detection (looking for `package.json`
etc.) — that path is too easy to false-positive on a stray manifest.
Bootstrap writes `.ai-factory.env` only when the tier+app_class actually
implies a known test runner.

Disable explicitly with `AI_FACTORY_TESTS_ENABLED=false`.
"""

from __future__ import annotations

import os
import shlex
import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class TestPlan:
    cmd: list[str]
    rationale: str


@dataclass(frozen=True)
class TestResult:
    plan: TestPlan | None
    skipped_reason: str | None
    exit_code: int
    stdout_tail: str
    stderr_tail: str

    @property
    def passed(self) -> bool:
        return self.skipped_reason is None and self.exit_code == 0

    @property
    def skipped(self) -> bool:
        return self.skipped_reason is not None


def configured_plan(workspace: Path | None = None) -> TestPlan | None:
    if os.getenv("AI_FACTORY_TESTS_ENABLED", "true").lower() == "false":
        return None
    cmd = os.getenv("AI_FACTORY_TEST_CMD", "").strip()
    rationale_source = "AI_FACTORY_TEST_CMD"
    if not cmd and workspace is not None:
        cmd = _read_workspace_test_cmd(workspace)
        if cmd:
            rationale_source = ".ai-factory.env"
    if not cmd:
        return None
    # posix=True works on both Windows and POSIX: quotes are stripped and
    # backslashes inside double-quoted segments are kept literal, so paths
    # like `"C:\Python\python.exe"` survive.
    parts = shlex.split(cmd)
    if not parts:
        return None
    return TestPlan(parts, f"{rationale_source}={cmd}")


def _read_workspace_test_cmd(workspace: Path) -> str:
    """Read `AI_FACTORY_TEST_CMD` from `<workspace>/.ai-factory.env`, if present.

    Tiny line-based parser — no python-dotenv dep. Strips quotes and ignores
    blank lines and `#` comments. Returns "" when the file is missing,
    unreadable, or doesn't define the key.
    """
    env_path = workspace / ".ai-factory.env"
    if not env_path.exists():
        return ""
    try:
        for raw_line in env_path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                continue
            key, _, value = line.partition("=")
            if key.strip() == "AI_FACTORY_TEST_CMD":
                return value.strip().strip('"').strip("'")
    except OSError:
        pass
    return ""


def run_tests(workspace: Path, timeout: float = 120.0) -> TestResult:
    plan = configured_plan(workspace)
    if plan is None:
        if os.getenv("AI_FACTORY_TESTS_ENABLED", "true").lower() == "false":
            return TestResult(None, "disabled via AI_FACTORY_TESTS_ENABLED=false", 0, "", "")
        return TestResult(None, "no test command configured (set AI_FACTORY_TEST_CMD)", 0, "", "")

    try:
        proc = subprocess.run(
            plan.cmd,
            cwd=str(workspace),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
    except FileNotFoundError:
        return TestResult(plan, f"runner '{plan.cmd[0]}' not on PATH", 127, "", "")
    except subprocess.TimeoutExpired as e:
        return TestResult(
            plan, None, 124, _tail(e.stdout or "", 4000), f"timeout after {timeout}s"
        )

    return TestResult(
        plan=plan,
        skipped_reason=None,
        exit_code=proc.returncode,
        stdout_tail=_tail(proc.stdout, 4000),
        stderr_tail=_tail(proc.stderr, 4000),
    )


def _tail(s: str | bytes, n: int) -> str:
    if not s:
        return ""
    text = s.decode("utf-8", errors="replace") if isinstance(s, bytes) else s
    text = text.strip()
    if len(text) <= n:
        return text
    return "...(truncated)...\n" + text[-n:]
