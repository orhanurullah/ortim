# SPDX-License-Identifier: FSL-1.1-Apache-2.0
# Copyright (c) 2026 ortim.dev
"""Tests for the hook framework (Faz 6c).

Hooks are subprocess wrappers around env-configured commands. We use
portable Python one-liners so the tests pass on Windows + POSIX without
needing bash, sh, or external tools.
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from ortim.audit import AuditLogger  # noqa: E402
from ortim.hooks import HOOK_COMMANDS, run_hook  # noqa: E402


def _scrub(*keys: str) -> dict[str, str | None]:
    saved = {k: os.environ.get(k) for k in keys}
    for k in keys:
        os.environ.pop(k, None)
    return saved


def _restore(saved: dict[str, str | None]) -> None:
    for k, v in saved.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v


PY = f'"{sys.executable}"'


def test_hook_skipped_when_no_command_configured() -> None:
    saved = _scrub("ORTIM_LINT_CMD", "ORTIM_FORMAT_CHECK_CMD",
                   "ORTIM_HOOKS_ENABLED")
    try:
        with tempfile.TemporaryDirectory() as tmp:
            audit = AuditLogger(path=Path(tmp) / "audit.jsonl")
            r = run_hook("pre_commit", Path(tmp), audit, project_id="P")
            assert r.skipped is True
            assert r.passed is True  # skip == pass for the pipeline
            assert "no commands configured" in r.skipped_reason
    finally:
        _restore(saved)


def test_hook_disabled_via_env() -> None:
    saved = _scrub("ORTIM_LINT_CMD", "ORTIM_HOOKS_ENABLED")
    os.environ["ORTIM_LINT_CMD"] = f'{PY} -c "pass"'
    os.environ["ORTIM_HOOKS_ENABLED"] = "false"
    try:
        with tempfile.TemporaryDirectory() as tmp:
            audit = AuditLogger(path=Path(tmp) / "audit.jsonl")
            r = run_hook("pre_commit", Path(tmp), audit, project_id="P")
            assert r.skipped is True
            assert "disabled" in r.skipped_reason.lower()
    finally:
        _restore(saved)


def test_hook_passes_with_zero_exit() -> None:
    saved = _scrub("ORTIM_LINT_CMD", "ORTIM_FORMAT_CHECK_CMD",
                   "ORTIM_HOOKS_ENABLED")
    os.environ["ORTIM_LINT_CMD"] = f'{PY} -c "pass"'
    try:
        with tempfile.TemporaryDirectory() as tmp:
            audit = AuditLogger(path=Path(tmp) / "audit.jsonl")
            r = run_hook("pre_commit", Path(tmp), audit, project_id="P")
            assert r.skipped is False
            assert r.exit_code == 0
            assert r.passed is True
    finally:
        _restore(saved)


def test_hook_fails_with_nonzero_exit() -> None:
    saved = _scrub("ORTIM_LINT_CMD", "ORTIM_FORMAT_CHECK_CMD",
                   "ORTIM_HOOKS_ENABLED")
    os.environ["ORTIM_LINT_CMD"] = (
        f'{PY} -c "import sys; sys.stderr.write(\'lint err\'); sys.exit(2)"'
    )
    try:
        with tempfile.TemporaryDirectory() as tmp:
            audit = AuditLogger(path=Path(tmp) / "audit.jsonl")
            r = run_hook("pre_commit", Path(tmp), audit, project_id="P")
            assert r.skipped is False
            assert r.exit_code == 2
            assert r.passed is False
            assert "lint err" in r.stderr_tail
    finally:
        _restore(saved)


def test_first_failing_command_short_circuits_chain() -> None:
    """pre_commit runs LINT then FORMAT_CHECK; lint failure must stop format."""
    saved = _scrub("ORTIM_LINT_CMD", "ORTIM_FORMAT_CHECK_CMD",
                   "ORTIM_HOOKS_ENABLED")
    os.environ["ORTIM_LINT_CMD"] = f'{PY} -c "import sys; sys.exit(7)"'
    # If format check ran, it would write a marker; we assert it does NOT.
    marker = None
    try:
        with tempfile.TemporaryDirectory() as tmp:
            marker = Path(tmp) / "format_ran.marker"
            os.environ["ORTIM_FORMAT_CHECK_CMD"] = (
                f'{PY} -c "open(r\'{marker}\', \'w\').close()"'
            )
            audit = AuditLogger(path=Path(tmp) / "audit.jsonl")
            r = run_hook("pre_commit", Path(tmp), audit, project_id="P")
            assert r.exit_code == 7
            assert not marker.exists(), (
                "FORMAT_CHECK must not have run after LINT failed"
            )
    finally:
        _restore(saved)


def test_unknown_hook_name_raises() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        audit = AuditLogger(path=Path(tmp) / "audit.jsonl")
        try:
            run_hook("not_a_real_hook", Path(tmp), audit)
        except ValueError:
            return
        raise AssertionError("Expected ValueError on unknown hook")


def test_hook_registry_has_pre_commit_and_pre_deploy() -> None:
    assert "pre_commit" in HOOK_COMMANDS
    assert "pre_deploy" in HOOK_COMMANDS
    assert "ORTIM_LINT_CMD" in HOOK_COMMANDS["pre_commit"]
    assert "ORTIM_DEPLOY_CMD" in HOOK_COMMANDS["pre_deploy"]


if __name__ == "__main__":
    tests = [
        test_hook_skipped_when_no_command_configured,
        test_hook_disabled_via_env,
        test_hook_passes_with_zero_exit,
        test_hook_fails_with_nonzero_exit,
        test_first_failing_command_short_circuits_chain,
        test_unknown_hook_name_raises,
        test_hook_registry_has_pre_commit_and_pre_deploy,
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
