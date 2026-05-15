# SPDX-License-Identifier: FSL-1.1-Apache-2.0
# Copyright (c) 2026 ortim.dev
"""Tests for `ortim doctor` — environment health check.

Doctor is read-only and the individual checks are pure functions over
env + filesystem, so tests exercise each check independently with
monkeypatch + tmp_path. Integration coverage focuses on:

  * Exit code semantics (0 / 2 / 3)
  * Category routing (required vs recommended vs optional)
  * JSON serialization stability
  * The two API-key checks correctly classify themselves as recommended
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from runtime.doctor import (  # noqa: E402
    CAT_OPTIONAL,
    CAT_RECOMMENDED,
    CAT_REQUIRED,
    STATUS_MISSING,
    STATUS_OK,
    STATUS_WARNING,
    DoctorCheck,
    DoctorReport,
    check_agent_prompts,
    check_anthropic_key,
    check_audit_log_dir,
    check_deepseek_key,
    check_l1_principles,
    check_python_version,
    check_skills_dir,
    check_workspace_dir,
    run_all_checks,
    to_json_dict,
)


# ---------------------------------------------------------------------
# Individual check tests
# ---------------------------------------------------------------------


def test_python_version_is_required_and_passes_on_current_interpreter() -> None:
    c = check_python_version()
    assert c.category == CAT_REQUIRED
    assert c.status == STATUS_OK  # pytest itself requires 3.11+


def test_workspace_dir_check_creates_and_writes() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        ws = Path(tmp) / "workspaces"
        c = check_workspace_dir(ws)
        assert c.status == STATUS_OK
        assert c.category == CAT_REQUIRED
        # The probe write/unlink must leave the dir clean.
        assert ws.exists()
        assert list(ws.iterdir()) == []


def test_audit_log_dir_uses_env_override_when_set() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        custom = Path(tmp) / "custom" / "audit.jsonl"
        os.environ["AUDIT_LOG_PATH"] = str(custom)
        try:
            c = check_audit_log_dir(repo_root=Path(tmp))
            assert c.status == STATUS_OK
            assert "custom" in c.detail
        finally:
            os.environ.pop("AUDIT_LOG_PATH", None)


def test_l1_principles_missing_when_file_absent() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        c = check_l1_principles(Path(tmp))
        assert c.status == STATUS_MISSING
        assert c.category == CAT_REQUIRED
        assert c.fix_hint  # actionable hint required for required-class misses


def test_agent_prompts_missing_lists_specific_files() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        agents_dir = Path(tmp) / "agents"
        agents_dir.mkdir()
        # Only one of the required prompts present.
        (agents_dir / "worker.md").write_text("x", encoding="utf-8")
        c = check_agent_prompts(Path(tmp))
        assert c.status == STATUS_MISSING
        # Specific missing names surfaced (helps the operator know what
        # to restore rather than re-clone the whole repo).
        for name in ("babel.md", "reviewer.md", "architect.md", "orchestrator.md"):
            assert name in c.detail


def test_anthropic_key_check_is_recommended_not_required() -> None:
    """Per the design: several commands (`score-tier`, `states`, `retro`,
    ...) operate without an LLM. ANTHROPIC_API_KEY is recommended but
    not required so doctor doesn't bark at users running key-free flows."""
    saved = os.environ.pop("ANTHROPIC_API_KEY", None)
    try:
        c = check_anthropic_key()
        assert c.category == CAT_RECOMMENDED
        assert c.status == STATUS_MISSING
    finally:
        if saved is not None:
            os.environ["ANTHROPIC_API_KEY"] = saved


def test_deepseek_key_check_passes_when_set() -> None:
    os.environ["DEEPSEEK_API_KEY"] = "sk-test-deadbeef"
    try:
        c = check_deepseek_key()
        assert c.status == STATUS_OK
        assert c.category == CAT_RECOMMENDED
        assert "length" in c.detail  # avoid logging the actual secret
        assert "deadbeef" not in c.detail  # secret must not leak into output
    finally:
        os.environ.pop("DEEPSEEK_API_KEY", None)


def test_skills_dir_warns_when_present_but_empty() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        skills = Path(tmp) / "skills"
        skills.mkdir()
        c = check_skills_dir(Path(tmp))
        assert c.status == STATUS_WARNING
        assert c.category == CAT_RECOMMENDED


# ---------------------------------------------------------------------
# Report-level semantics
# ---------------------------------------------------------------------


def test_exit_code_zero_when_all_required_and_recommended_pass() -> None:
    report = DoctorReport(checks=[
        DoctorCheck("a", STATUS_OK, "", CAT_REQUIRED),
        DoctorCheck("b", STATUS_OK, "", CAT_RECOMMENDED),
        DoctorCheck("c", STATUS_MISSING, "", CAT_OPTIONAL),
    ])
    assert report.exit_code == 0


def test_exit_code_two_when_only_recommended_missing() -> None:
    report = DoctorReport(checks=[
        DoctorCheck("a", STATUS_OK, "", CAT_REQUIRED),
        DoctorCheck("b", STATUS_MISSING, "", CAT_RECOMMENDED),
    ])
    assert report.exit_code == 2


def test_exit_code_three_when_required_missing() -> None:
    report = DoctorReport(checks=[
        DoctorCheck("a", STATUS_MISSING, "", CAT_REQUIRED),
        DoctorCheck("b", STATUS_OK, "", CAT_RECOMMENDED),
    ])
    assert report.exit_code == 3


def test_optional_misses_alone_do_not_change_exit_code() -> None:
    report = DoctorReport(checks=[
        DoctorCheck("a", STATUS_OK, "", CAT_REQUIRED),
        DoctorCheck("b", STATUS_OK, "", CAT_RECOMMENDED),
        DoctorCheck("c", STATUS_MISSING, "", CAT_OPTIONAL),
        DoctorCheck("d", STATUS_MISSING, "", CAT_OPTIONAL),
    ])
    assert report.exit_code == 0


# ---------------------------------------------------------------------
# Integration — run_all_checks
# ---------------------------------------------------------------------


def test_run_all_checks_returns_complete_report() -> None:
    """A full run on the test environment must include all expected
    categories. Status varies (LLM keys may or may not be set in CI), so
    we only assert structure here."""
    with tempfile.TemporaryDirectory() as tmp:
        report = run_all_checks(
            workspace_root=Path(tmp),
            repo_root=REPO_ROOT,
        )
        categories = {c.category for c in report.checks}
        assert categories == {CAT_REQUIRED, CAT_RECOMMENDED, CAT_OPTIONAL}
        assert len(report.checks) >= 10  # design guarantees ~15 checks


def test_to_json_dict_has_stable_schema() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        report = run_all_checks(
            workspace_root=Path(tmp),
            repo_root=REPO_ROOT,
        )
        out = to_json_dict(report)
        assert set(out.keys()) == {
            "exit_code",
            "required_failures",
            "recommended_misses",
            "optional_misses",
            "checks",
        }
        assert set(out["checks"][0].keys()) == {
            "name",
            "status",
            "category",
            "detail",
            "fix_hint",
        }
