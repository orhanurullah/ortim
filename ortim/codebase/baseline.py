# SPDX-License-Identifier: FSL-1.1-Apache-2.0
# Copyright (c) 2026 ortim.dev
"""Test-suite baseline contract for brownfield projects.

When a project is bootstrapped via `--from-existing`, we capture how many
tests are passing in the existing codebase. After every Worker task, the
runner re-parses the test output and compares against the baseline; a
regression (passing count drops) sends the task to AWAITING_HITL even if
the Worker's output is otherwise approved.

The baseline is intentionally narrow:

  * `passing` is the headline number (the contract the user signed up for)
  * `failed` is recorded for visibility — a brownfield project may already
    have failing tests, and that's not the Worker's problem to fix unless
    asked
  * `skipped` is informational; never gates anything

Auto-detect picks one of three test commands by inspecting the workspace:

  * `pubspec.yaml` → `flutter test`
  * `pyproject.toml` → `pytest`
  * `package.json` with a `test` script → `npm test`

Anything else: caller must pass `cmd` explicitly. We don't guess.

The output parser is regex-based and tolerant — flutter and pytest emit
different stable shapes; if neither matches, `passing=-1` indicates "could
not determine" and the regression check is disabled (with a warning).
"""

from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from ortim.env import env_get


@dataclass(frozen=True)
class TestBaseline:
    cmd: str
    captured_at: str
    passing: int
    skipped: int
    failed: int
    full_output_tail: str  # last ~4KB for debugging

    def to_dict(self) -> dict[str, object]:
        return {
            "cmd": self.cmd,
            "captured_at": self.captured_at,
            "passing": self.passing,
            "skipped": self.skipped,
            "failed": self.failed,
            "full_output_tail": self.full_output_tail,
        }

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> TestBaseline:
        return cls(
            cmd=str(data["cmd"]),
            captured_at=str(data["captured_at"]),
            passing=int(data["passing"]),  # type: ignore[arg-type]
            skipped=int(data["skipped"]),  # type: ignore[arg-type]
            failed=int(data["failed"]),  # type: ignore[arg-type]
            full_output_tail=str(data.get("full_output_tail", "")),
        )

    @property
    def parseable(self) -> bool:
        """False when the parser couldn't extract a count — disables regression check."""
        return self.passing >= 0


# --------- Auto-detect ---------


def detect_test_cmd(workspace: Path) -> str | None:
    """Return the test command for `workspace`, or None if it's unrecognized."""
    if (workspace / "pubspec.yaml").exists():
        return "flutter test"
    if (workspace / "pyproject.toml").exists():
        return "pytest"
    pkg = workspace / "package.json"
    if pkg.exists():
        try:
            data = json.loads(pkg.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        scripts = data.get("scripts") or {}
        if isinstance(scripts, dict) and "test" in scripts:
            return "npm test"
    return None


# --------- Parsers ---------

# pytest emits a final summary line:
#   "5 passed, 1 skipped in 0.42s"
#   "3 failed, 17 passed in 1.21s"
# We pick each count out independently — a single all-optional pattern
# matches the empty string and is useless.
_PYTEST_PASSED = re.compile(r"(\d+)\s+passed", re.IGNORECASE)
_PYTEST_FAILED = re.compile(r"(\d+)\s+failed", re.IGNORECASE)
_PYTEST_SKIPPED = re.compile(r"(\d+)\s+skipped", re.IGNORECASE)

# flutter test variant 1 (compact):  "All tests passed!"
# variant 2 (with counts):           "+12 ~3 -1: Some tests failed."
# variant 3 (json reporter):         we don't parse — falls back to text counts
_FLUTTER_PATTERN = re.compile(
    r"\+(\d+)(?:\s*~(\d+))?(?:\s*-(\d+))?\s*:",
)


def parse_test_count(stdout: str, cmd: str) -> tuple[int, int, int]:
    """Return (passing, skipped, failed). `(-1, -1, -1)` if no match."""
    text = stdout.strip()
    if not text:
        return (-1, -1, -1)

    if "flutter" in cmd.lower():
        # Try flutter compact summary first.
        last_match: re.Match[str] | None = None
        for m in _FLUTTER_PATTERN.finditer(text):
            last_match = m
        if last_match:
            passing = int(last_match.group(1))
            skipped = int(last_match.group(2) or 0)
            failed = int(last_match.group(3) or 0)
            return (passing, skipped, failed)
        # "All tests passed!" — count is hidden in earlier `+N` markers.
        if "all tests passed" in text.lower():
            return (0, 0, 0)
        return (-1, -1, -1)

    # pytest path. Walk lines bottom-up — the summary lives at the tail —
    # and pick the first line that has at least one of {passed, failed, skipped}.
    for line in reversed(text.splitlines()):
        passed_m = _PYTEST_PASSED.search(line)
        failed_m = _PYTEST_FAILED.search(line)
        skipped_m = _PYTEST_SKIPPED.search(line)
        if not (passed_m or failed_m or skipped_m):
            continue
        return (
            int(passed_m.group(1)) if passed_m else 0,
            int(skipped_m.group(1)) if skipped_m else 0,
            int(failed_m.group(1)) if failed_m else 0,
        )
    return (-1, -1, -1)


# --------- Capture ---------


def capture(workspace: Path, cmd: str | None = None, timeout: int = 600) -> TestBaseline:
    """Run the test command and snapshot the result as the project's baseline.

    `cmd` may be passed explicitly; otherwise auto-detect. If neither yields
    a command, raise — the caller must decide whether to skip baseline mode
    or supply one manually.
    """
    chosen = cmd or detect_test_cmd(workspace)
    if not chosen:
        raise RuntimeError(
            f"Cannot auto-detect test command for {workspace}; "
            "pass cmd= explicitly (e.g. 'flutter test', 'pytest', 'npm test')."
        )

    try:
        proc = subprocess.run(
            chosen,
            shell=True,
            cwd=str(workspace),
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )
        combined = (proc.stdout or "") + "\n" + (proc.stderr or "")
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as e:
        combined = f"<baseline capture failed: {e}>"

    passing, skipped, failed = parse_test_count(combined, chosen)
    tail = combined[-4000:] if len(combined) > 4000 else combined
    return TestBaseline(
        cmd=chosen,
        captured_at=datetime.now(tz=timezone.utc).isoformat(),
        passing=passing,
        skipped=skipped,
        failed=failed,
        full_output_tail=tail,
    )


# --------- Persistence ---------


def write_baseline(cache_dir: Path, baseline: TestBaseline) -> Path:
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = cache_dir / "baseline.json"
    path.write_text(json.dumps(baseline.to_dict(), indent=2), encoding="utf-8")
    return path


def load_baseline(cache_dir: Path) -> TestBaseline | None:
    path = cache_dir / "baseline.json"
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return TestBaseline.from_dict(data)


# --------- Regression check ---------


@dataclass(frozen=True)
class RegressionReport:
    regressed: bool
    baseline_passing: int
    current_passing: int
    reason: str  # human-readable

    @property
    def message(self) -> str:
        if self.regressed:
            return (
                f"baseline regression: {self.baseline_passing} → "
                f"{self.current_passing} tests passing"
            )
        return self.reason


def check_regression(
    baseline: TestBaseline | None,
    current_stdout: str,
    cmd: str | None = None,
) -> RegressionReport:
    """Compare current test output against baseline; return regression status.

    No-op (regressed=False) when:
      * baseline is None (greenfield project)
      * baseline could not be parsed at capture time (parseable=False)
      * current output cannot be parsed (parser miss)
      * `ORTIM_BASELINE_DISABLED=1` is set
    """
    if env_get("ORTIM_BASELINE_DISABLED") == "1":
        return RegressionReport(False, -1, -1, "baseline check disabled by env")
    if baseline is None or not baseline.parseable:
        return RegressionReport(False, -1, -1, "no parseable baseline")
    used_cmd = cmd or baseline.cmd
    current_passing, _, _ = parse_test_count(current_stdout, used_cmd)
    if current_passing < 0:
        return RegressionReport(
            False, baseline.passing, -1, "current output not parseable"
        )
    if current_passing < baseline.passing:
        return RegressionReport(
            True, baseline.passing, current_passing, "regression"
        )
    return RegressionReport(
        False, baseline.passing, current_passing, "no regression"
    )
