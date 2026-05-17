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
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path


def _resolve_binary(name: str) -> str:
    """Resolve a command name (`npx`, `vitest`, `pytest`, …) to its full
    path so subprocess.run can launch it without `shell=True`.

    Windows-specific reason: npm-installed CLIs are `.cmd` shims, and
    Python's subprocess does NOT walk `PATHEXT` when launching a child
    process directly. `shutil.which` does — so resolving first lets
    `["npx", "vitest", "run"]` work the same on Windows as on POSIX.

    Returns the input unchanged if `shutil.which` finds nothing — the
    subprocess call will then raise FileNotFoundError, and the caller
    surfaces a `runner X not on PATH` skip reason as before.
    """
    if os.sep in name or "/" in name:
        # Already a path; leave as-is.
        return name
    resolved = shutil.which(name)
    return resolved if resolved is not None else name


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


def _detect_runner(parts: list[str]) -> str | None:
    """Identify the runner family from a parsed test command.

    Returns one of `{'vitest', 'pytest', 'flutter', 'cargo', 'go', None}`.
    Looks at `parts[0]`'s basename (works whether the token is a raw name
    like `pytest` or a `shutil.which`-resolved path like
    `C:\\Python\\Scripts\\pytest.exe`), then peeks at `parts[1]` for
    multi-tool hosts (`npx`) and subcommand-style tools
    (`flutter`/`cargo`/`go`).
    """
    if not parts:
        return None
    head = Path(parts[0]).stem.lower()
    rest = [p.lower() for p in parts[1:]]
    if head == "npx" and rest and rest[0] == "vitest":
        return "vitest"
    if head == "vitest":
        return "vitest"
    if head == "pytest" or head == "py.test":
        return "pytest"
    if head == "flutter" and rest and rest[0] == "test":
        return "flutter"
    if head == "cargo" and rest and rest[0] == "test":
        return "cargo"
    if head == "go" and rest and rest[0] == "test":
        return "go"
    return None


def _apply_scope(parts: list[str], scope: str | None) -> list[str]:
    """Append a per-task scope path to the test command when the runner
    supports positional path filtering.

    Supported: `vitest` (positional path + `--passWithNoTests` so a
    scope matching zero test files exits 0 instead of 1), `pytest`
    (positional path), `flutter test` (positional path).

    Unsupported (legacy workspace-wide behavior preserved): `cargo test`
    (package-name flag, not path), `go test ./...` (replace pattern, not
    append). Tracked as follow-up item 39b' in tespit.md — adding
    per-runner adapters there isn't on the M2 critical path.

    A `None` or empty `scope` is a no-op — kept so callers without a
    `TaskSpec` (scripts, ad-hoc CLI use) still get the legacy
    workspace-wide command.
    """
    if not scope:
        return parts
    runner = _detect_runner(parts)
    if runner == "vitest":
        out = list(parts)
        out.append(scope)
        if "--passWithNoTests" not in out:
            out.append("--passWithNoTests")
        return out
    if runner in {"pytest", "flutter"}:
        return [*parts, scope]
    return parts


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
    parts[0] = _resolve_binary(parts[0])
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


def run_tests(
    workspace: Path,
    timeout: float = 120.0,
    scope: str | None = None,
) -> TestResult:
    plan = configured_plan(workspace)
    if plan is None:
        if os.getenv("AI_FACTORY_TESTS_ENABLED", "true").lower() == "false":
            return TestResult(None, "disabled via AI_FACTORY_TESTS_ENABLED=false", 0, "", "")
        return TestResult(None, "no test command configured (set AI_FACTORY_TEST_CMD)", 0, "", "")

    scoped_cmd = _apply_scope(plan.cmd, scope)
    scope_applied = scoped_cmd is not plan.cmd
    runner_kind = _detect_runner(plan.cmd)
    effective_plan = (
        TestPlan(scoped_cmd, f"{plan.rationale} scope={scope}")
        if scope_applied
        else plan
    )

    try:
        proc = subprocess.run(
            scoped_cmd,
            cwd=str(workspace),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
    except FileNotFoundError:
        return TestResult(effective_plan, f"runner '{scoped_cmd[0]}' not on PATH", 127, "", "")
    except subprocess.TimeoutExpired as e:
        return TestResult(
            effective_plan, None, 124, _tail(e.stdout or "", 4000), f"timeout after {timeout}s"
        )

    exit_code = proc.returncode
    stdout_tail = _tail(proc.stdout, 4000)
    stderr_tail = _tail(proc.stderr, 4000)

    # pytest exits 5 when no tests were collected. When we narrowed pytest
    # to a per-task scope (39b), the absence of tests in that module is
    # neutral, not failure. Only normalize when scope was actually applied
    # — a workspace-wide pytest returning 5 is genuinely suspicious
    # (the project has no tests at all).
    if scope_applied and runner_kind == "pytest" and exit_code == 5:
        exit_code = 0
        note = "(test_runner: pytest exit 5 normalized — no tests collected under scope)"
        stdout_tail = f"{stdout_tail}\n{note}" if stdout_tail else note

    return TestResult(
        plan=effective_plan,
        skipped_reason=None,
        exit_code=exit_code,
        stdout_tail=stdout_tail,
        stderr_tail=stderr_tail,
    )


def _tail(s: str | bytes, n: int) -> str:
    if not s:
        return ""
    text = s.decode("utf-8", errors="replace") if isinstance(s, bytes) else s
    text = text.strip()
    if len(text) <= n:
        return text
    return "...(truncated)...\n" + text[-n:]
