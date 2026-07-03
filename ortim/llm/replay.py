# SPDX-License-Identifier: FSL-1.1-Apache-2.0
# Copyright (c) 2026 ortim.dev
"""Replay provider — serves recorded LLM responses from a fixture file.

Why this exists: `pip install ortim && ortim demo` must complete on a
machine with **no API key**. The replay provider makes that possible by
serving responses captured from a real, live run of the same chain.

Two halves:

- **Recording** (`ORTIM_REPLAY_RECORD=/path/out.jsonl`): while a live
  provider serves requests, `LLMClient.call()` appends one JSONL entry
  per call — prompt fingerprints (sha256), short previews, and the full
  response with token counts + the provider/model that produced it.
- **Replay** (`provider="replay"`): entries are served back **in call
  order**. The chain is deterministic (temperature 0, fixed brief, each
  prompt built from the previous recorded output), so ordered replay is
  stable; prompt fingerprints are still checked and a mismatch logs a
  stderr warning rather than failing, because non-semantic drift (a
  timestamp in a prompt) must not break the keyless demo.

The replay cursor must survive across processes — `ortim demo` runs each
step as a subprocess — so when `ORTIM_REPLAY_STATE=/path/state.json` is
set, the cursor persists there; otherwise it is kept in-memory (enough
for single-process use and tests).

Design note (managed provider): replay is the first provider that is
neither BYO-key nor local. It rides the same `ProviderConfig.api_kind`
seam that a future `managed` kind (requests proxied through
api.ortim.dev under a subscription token quota) will use: add the
api_kind, dispatch in `LLMClient.call()`, and agent code stays unaware.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path

FIXTURE_ENV = "ORTIM_REPLAY_FIXTURE"
STATE_ENV = "ORTIM_REPLAY_STATE"
RECORD_ENV = "ORTIM_REPLAY_RECORD"

# Bundled fixture: a captured live run of the default `ortim demo` chain
# (brief -> PRD -> scope lock -> RFC -> DAG). Ships in the wheel via
# [tool.setuptools.package-data].
DEFAULT_FIXTURE = (
    Path(__file__).resolve().parent.parent / "_assets" / "replay" / "demo-default.jsonl"
)

# In-memory cursors for when no ORTIM_REPLAY_STATE file is configured,
# keyed by fixture path so parallel fixtures don't cross-consume.
_memory_cursors: dict[str, int] = {}


class ReplayError(RuntimeError):
    """Fixture missing/corrupt or exhausted — the replay cannot continue."""


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def record_call(
    system: str,
    user: str,
    *,
    text: str,
    input_tokens: int,
    output_tokens: int,
    model: str,
    provider: str,
) -> None:
    """Append one live LLM exchange to the record file.

    No-op unless `ORTIM_REPLAY_RECORD` points at a target path. Appends
    are per-call so a chain of subprocesses writing sequentially to the
    same file produces entries in true call order.
    """
    target = os.environ.get(RECORD_ENV, "").strip()
    if not target:
        return
    entry = {
        "system_sha256": _sha256(system),
        "user_sha256": _sha256(user),
        "system_head": system[:160],
        "user_head": user[:160],
        "text": text,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "model": model,
        "provider": provider,
    }
    path = Path(target)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def fixture_path() -> Path:
    override = os.environ.get(FIXTURE_ENV, "").strip()
    return Path(override) if override else DEFAULT_FIXTURE


def load_fixture(path: Path | None = None) -> list[dict]:
    target = path or fixture_path()
    if not target.exists():
        raise ReplayError(
            f"replay fixture not found: {target}. The bundled demo fixture "
            f"ships with the package; for custom replays set "
            f"{FIXTURE_ENV}=/path/to/fixture.jsonl"
        )
    entries: list[dict] = []
    for i, line in enumerate(
        target.read_text(encoding="utf-8").splitlines(), start=1
    ):
        line = line.strip()
        if not line:
            continue
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError as exc:
            raise ReplayError(
                f"replay fixture {target} line {i} is not valid JSON: {exc}"
            ) from exc
    if not entries:
        raise ReplayError(f"replay fixture {target} is empty")
    return entries


def _read_cursor(fixture: Path) -> int:
    state = os.environ.get(STATE_ENV, "").strip()
    if not state:
        return _memory_cursors.get(str(fixture), 0)
    state_path = Path(state)
    if not state_path.exists():
        return 0
    try:
        return int(json.loads(state_path.read_text(encoding="utf-8"))["cursor"])
    except (json.JSONDecodeError, KeyError, ValueError, TypeError):
        return 0


def _write_cursor(fixture: Path, value: int) -> None:
    state = os.environ.get(STATE_ENV, "").strip()
    if not state:
        _memory_cursors[str(fixture)] = value
        return
    state_path = Path(state)
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps({"cursor": value}), encoding="utf-8")


def reset_memory_cursors() -> None:
    """Test helper: forget in-memory replay positions."""
    _memory_cursors.clear()


def replay_next(system: str, user: str) -> dict:
    """Serve the next recorded entry for this fixture, advancing the cursor.

    Ordered replay with a fingerprint sanity check: if the live prompt's
    sha256 differs from the recorded one, warn on stderr and serve the
    recorded response anyway (see module docstring for why).
    """
    fixture = fixture_path()
    entries = load_fixture(fixture)
    cursor = _read_cursor(fixture)
    if cursor >= len(entries):
        raise ReplayError(
            f"replay fixture {fixture} exhausted after {len(entries)} calls. "
            f"The recorded run covers a fixed chain; this run made more LLM "
            f"calls than the recording. Configure a real provider "
            f"(`ortim config init`) for live runs."
        )
    entry = entries[cursor]
    if (
        entry.get("system_sha256") != _sha256(system)
        or entry.get("user_sha256") != _sha256(user)
    ):
        print(
            f"[ortim] replay: prompt fingerprint differs from the recording "
            f"at call #{cursor + 1}; serving the recorded response by order.",
            file=sys.stderr,
        )
    _write_cursor(fixture, cursor + 1)
    return entry
