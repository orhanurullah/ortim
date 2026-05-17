# SPDX-License-Identifier: FSL-1.1-Apache-2.0
# Copyright (c) 2026 ortim.dev
"""PII redaction for audit log entries.

Compliance posture: KVKK + GDPR. Strings flowing into the audit log may be
brief text, PRD content, or LLM input/output snippets — any of these can
contain user PII. We redact at write time, before the JSONL line is built,
so the on-disk log is safe to ship to compliance teams without sanitization.

The redactor is conservative on purpose: false positives are tolerable
(an event that says `[REDACTED]` is still useful for debugging structure),
false negatives are not.

Bypass for debug only:

    ORTIM_AUDIT_RAW=1          # disables redaction; never set in prod

Bypass leaves a `redaction_bypassed: true` marker on every event so that
auditors can still tell post-hoc that the log was written without redaction.
"""

from __future__ import annotations

import re
from typing import Any

from ortim.env import env_get

# Email — RFC 5322 lite, intentionally generous
_RE_EMAIL = re.compile(
    r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"
)

# Turkish national ID (T.C. Kimlik No): 11 digits, first cannot be 0
_RE_TC_KIMLIK = re.compile(r"\b[1-9][0-9]{10}\b")

# Phone numbers — Turkish mobile/landline + generic E.164
# +90 5xx xxx xx xx, 05xx xxx xx xx, +1 555 555 5555, etc.
_RE_PHONE = re.compile(
    r"(?:\+?\d{1,3}[\s\-]?)?(?:\(?\d{2,4}\)?[\s\-]?)?\d{3}[\s\-]?\d{2,4}[\s\-]?\d{2,4}"
)

# Credit-card-like 13–19 digit runs with optional separators (Luhn not validated)
_RE_CREDIT_CARD = re.compile(
    r"\b(?:\d[ -]*?){13,19}\b"
)

# IPv4
_RE_IPV4 = re.compile(
    r"\b(?:(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\.){3}(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\b"
)


def _redact_phone_safe(text: str) -> str:
    """Phone regex is greedy; only redact when at least one digit-grouping
    indicator is present (`+`, `(`, `-`, or a leading `0` for TR).

    Without this guard, generic 10-digit task counts or hashes get clobbered.
    """
    def _replace(match: re.Match[str]) -> str:
        s = match.group(0)
        if "+" in s or "(" in s or "-" in s or s.startswith("0") or " " in s:
            return "[PHONE]"
        return s
    return _RE_PHONE.sub(_replace, text)


def redact_string(text: str) -> str:
    """Apply all PII patterns in a fixed order.

    Order matters: credit-card and TC kimlik can both look like generic
    digit runs, so we run the most specific patterns first.
    """
    if not text:
        return text
    text = _RE_EMAIL.sub("[EMAIL]", text)
    text = _RE_CREDIT_CARD.sub("[CARD]", text)
    text = _RE_TC_KIMLIK.sub("[TCKN]", text)
    text = _redact_phone_safe(text)
    text = _RE_IPV4.sub("[IP]", text)
    return text


def redact_value(value: Any) -> Any:
    """Recursively redact strings inside dicts/lists; leave everything else alone."""
    if isinstance(value, str):
        return redact_string(value)
    if isinstance(value, dict):
        return {k: redact_value(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        out = [redact_value(v) for v in value]
        return tuple(out) if isinstance(value, tuple) else out
    return value


def redaction_enabled() -> bool:
    """False iff the operator explicitly opted out via `ORTIM_AUDIT_RAW=1`."""
    return (env_get("ORTIM_AUDIT_RAW", "") or "").strip() not in ("1", "true", "yes")
