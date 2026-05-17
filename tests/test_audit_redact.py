# SPDX-License-Identifier: FSL-1.1-Apache-2.0
# Copyright (c) 2026 ortim.dev
"""PII redaction tests for the audit log.

Compliance posture: KVKK + GDPR. We assert that all string-typed PII patterns
are scrubbed before serialization and that the bypass env var leaves a marker.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from ortim.audit import AuditLogger, redact_string  # noqa: E402


def test_redact_email_tckn_phone_card_ip() -> None:
    text = (
        "Customer email orhan@example.com with TC kimlik 12345678901, "
        "phone +90 555 123 45 67, card 4111-1111-1111-1111, IP 192.168.1.10."
    )
    out = redact_string(text)
    assert "@example.com" not in out, out
    assert "12345678901" not in out, out
    assert "555 123 45 67" not in out and "5551234567" not in out, out
    assert "4111-1111-1111-1111" not in out, out
    assert "192.168.1.10" not in out, out
    assert "[EMAIL]" in out
    assert "[TCKN]" in out
    assert "[CARD]" in out
    assert "[IP]" in out


def test_redact_does_not_clobber_safe_text() -> None:
    """Ordinary identifiers and integers should pass through untouched."""
    safe = "task T-007 reviewer veto on PR 42, exit_code=2, summary OK"
    out = redact_string(safe)
    assert out == safe, f"Safe text was modified: {safe!r} -> {out!r}"


def test_logger_writes_redacted_strings() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "audit.jsonl"
        logger = AuditLogger(path=path)
        logger.log(
            "architect_extract_inputs",
            project_id="p1",
            user_brief="Mail at user@corp.com lütfen",
        )
        line = path.read_text(encoding="utf-8").strip()
        rec = json.loads(line)
        assert "user@corp.com" not in rec["user_brief"]
        assert "[EMAIL]" in rec["user_brief"]
        assert rec.get("redaction_bypassed") is None  # default: redaction on


def test_bypass_env_leaves_marker() -> None:
    os.environ["ORTIM_AUDIT_RAW"] = "1"
    try:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "audit.jsonl"
            logger = AuditLogger(path=path)
            logger.log("architect_extract_inputs", brief="contact me at a@b.com")
            rec = json.loads(path.read_text(encoding="utf-8").strip())
            assert rec["redaction_bypassed"] is True
            assert rec["brief"] == "contact me at a@b.com"  # raw passthrough
    finally:
        del os.environ["ORTIM_AUDIT_RAW"]


if __name__ == "__main__":
    tests = [
        test_redact_email_tckn_phone_card_ip,
        test_redact_does_not_clobber_safe_text,
        test_logger_writes_redacted_strings,
        test_bypass_env_leaves_marker,
    ]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"PASS  {t.__name__}")
        except Exception as e:
            failed += 1
            print(f"FAIL  {t.__name__}: {e}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
