# SPDX-License-Identifier: FSL-1.1-Apache-2.0
# Copyright (c) 2026 ortim.dev
"""Tests for the replay provider — recorded LLM responses (keyless demo).

Covers the three seams:
  * providers.py — `replay` registered, keyless, priced 0.0, api_kind
    dispatch stays intact for the existing providers.
  * replay.py — ordered serving, fingerprint tolerance, cross-process
    cursor via ORTIM_REPLAY_STATE, exhaustion error, recording append.
  * client.py — LLMClient(provider="replay") end-to-end without any
    key or network; live-path recording hook writes a valid fixture.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import pytest  # noqa: E402

from ortim.llm import replay  # noqa: E402
from ortim.llm.client import LLMClient, LLMResponse  # noqa: E402
from ortim.llm.providers import PROVIDERS, resolve_provider  # noqa: E402


def _write_fixture(path: Path, calls: list[tuple[str, str, str]]) -> None:
    """calls: list of (system, user, response_text)."""
    lines = []
    for system, user, text in calls:
        lines.append(json.dumps({
            "system_sha256": replay._sha256(system),
            "user_sha256": replay._sha256(user),
            "system_head": system[:160],
            "user_head": user[:160],
            "text": text,
            "input_tokens": 10,
            "output_tokens": 20,
            "model": "deepseek-chat",
            "provider": "deepseek",
        }))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


@pytest.fixture(autouse=True)
def _clean_replay_state(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv(replay.FIXTURE_ENV, raising=False)
    monkeypatch.delenv(replay.STATE_ENV, raising=False)
    monkeypatch.delenv(replay.RECORD_ENV, raising=False)
    replay.reset_memory_cursors()
    yield
    replay.reset_memory_cursors()


# ---------------------------------------------------------------------------
# Provider registry
# ---------------------------------------------------------------------------

def test_replay_provider_registered_keyless_and_free() -> None:
    cfg = PROVIDERS["replay"]
    assert cfg.api_key_env is None, "replay must never require a key"
    assert cfg.api_kind == "replay"
    assert cfg.input_usd_per_m == 0.0
    assert cfg.output_usd_per_m == 0.0
    assert resolve_provider("replay") is cfg


# ---------------------------------------------------------------------------
# Ordered replay + fingerprints
# ---------------------------------------------------------------------------

def test_replay_serves_recorded_responses_in_order(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = tmp_path / "fx.jsonl"
    _write_fixture(fixture, [("s1", "u1", "first"), ("s2", "u2", "second")])
    monkeypatch.setenv(replay.FIXTURE_ENV, str(fixture))

    client = LLMClient(provider="replay")
    r1 = client.call("s1", "u1")
    r2 = client.call("s2", "u2")

    assert isinstance(r1, LLMResponse)
    assert (r1.text, r2.text) == ("first", "second")
    assert r1.provider == "replay", "budget rollups must price replay at $0"
    assert r1.model == "deepseek-chat", "audit shows the recording's model"
    assert (r1.input_tokens, r1.output_tokens) == (10, 20)


def test_replay_tolerates_fingerprint_drift(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture,
) -> None:
    """A timestamp leaking into a prompt must not break the keyless demo:
    order-based serving continues, with a stderr warning."""
    fixture = tmp_path / "fx.jsonl"
    _write_fixture(fixture, [("s1", "u1", "first")])
    monkeypatch.setenv(replay.FIXTURE_ENV, str(fixture))

    resp = LLMClient(provider="replay").call("s1", "u1-DIFFERENT")
    assert resp.text == "first"
    assert "fingerprint differs" in capsys.readouterr().err


def test_replay_exhaustion_raises_actionable_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = tmp_path / "fx.jsonl"
    _write_fixture(fixture, [("s1", "u1", "only")])
    monkeypatch.setenv(replay.FIXTURE_ENV, str(fixture))

    client = LLMClient(provider="replay")
    client.call("s1", "u1")
    with pytest.raises(replay.ReplayError, match="exhausted"):
        client.call("s2", "u2")


def test_replay_missing_fixture_raises_actionable_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(replay.FIXTURE_ENV, str(tmp_path / "nope.jsonl"))
    with pytest.raises(replay.ReplayError, match="not found"):
        LLMClient(provider="replay").call("s", "u")


# ---------------------------------------------------------------------------
# Cross-process cursor (ORTIM_REPLAY_STATE)
# ---------------------------------------------------------------------------

def test_replay_cursor_persists_via_state_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`ortim demo` runs each step as a subprocess; a fresh LLMClient in a
    'new process' (fresh client + cleared memory cursors) must continue
    from the state file, not restart at entry 0."""
    fixture = tmp_path / "fx.jsonl"
    _write_fixture(fixture, [("s1", "u1", "first"), ("s2", "u2", "second")])
    monkeypatch.setenv(replay.FIXTURE_ENV, str(fixture))
    monkeypatch.setenv(replay.STATE_ENV, str(tmp_path / "cursor.json"))

    assert LLMClient(provider="replay").call("s1", "u1").text == "first"
    replay.reset_memory_cursors()  # simulate a new process
    assert LLMClient(provider="replay").call("s2", "u2").text == "second"


# ---------------------------------------------------------------------------
# Recording hook
# ---------------------------------------------------------------------------

def test_live_call_records_replayable_fixture(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With ORTIM_REPLAY_RECORD set, a (mocked) live call appends a JSONL
    entry that a replay client can then serve back verbatim."""
    record_path = tmp_path / "recorded.jsonl"
    monkeypatch.setenv(replay.RECORD_ENV, str(record_path))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-stub")

    live = LLMClient(provider="anthropic")
    monkeypatch.setattr(
        live,
        "_call_anthropic",
        lambda system, user, temperature, max_tokens, retries_used: LLMResponse(
            text="live answer",
            input_tokens=5,
            output_tokens=7,
            model="claude-opus-4-7",
            provider="anthropic",
        ),
    )
    live.call("sys prompt", "user prompt")

    entries = [
        json.loads(line)
        for line in record_path.read_text(encoding="utf-8").splitlines()
    ]
    assert len(entries) == 1
    assert entries[0]["text"] == "live answer"
    assert entries[0]["user_sha256"] == replay._sha256("user prompt")

    # …and the recording replays.
    monkeypatch.delenv(replay.RECORD_ENV, raising=False)
    monkeypatch.setenv(replay.FIXTURE_ENV, str(record_path))
    resp = LLMClient(provider="replay").call("sys prompt", "user prompt")
    assert resp.text == "live answer"
    assert resp.model == "claude-opus-4-7"


def test_replay_call_does_not_rerecord(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Replay + record simultaneously must not duplicate the fixture —
    only live paths record."""
    fixture = tmp_path / "fx.jsonl"
    _write_fixture(fixture, [("s1", "u1", "first")])
    monkeypatch.setenv(replay.FIXTURE_ENV, str(fixture))
    record_path = tmp_path / "out.jsonl"
    monkeypatch.setenv(replay.RECORD_ENV, str(record_path))

    LLMClient(provider="replay").call("s1", "u1")
    assert not record_path.exists()
