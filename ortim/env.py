"""Env-var compatibility shim for the AI_FACTORY_* → ORTIM_* rename.

`env_get(name, default)` reads the canonical `ORTIM_*` name first; if unset,
falls back to the legacy `AI_FACTORY_*` name and emits a one-time stderr
deprecation warning. After one full minor release with this shim in place
(target: R7), the legacy fallback is dropped.

All env reads in the codebase route through this helper. New names follow
1:1 from the legacy name: `AI_FACTORY_X` → `ORTIM_X`.
"""

from __future__ import annotations

import os
import sys

_LEGACY_PREFIX = "AI_FACTORY_"
_NEW_PREFIX = "ORTIM_"

_warned: set[str] = set()


def _legacy_name(name: str) -> str | None:
    if name.startswith(_NEW_PREFIX):
        return _LEGACY_PREFIX + name[len(_NEW_PREFIX):]
    return None


def env_get(name: str, default: str | None = None) -> str | None:
    """Read an env var with dual-name fallback.

    `name` must use the new `ORTIM_*` prefix. If unset, the matching
    `AI_FACTORY_*` legacy name is consulted and a one-time deprecation
    warning is logged to stderr. Returns `default` if neither is set.
    """
    val = os.environ.get(name)
    if val is not None:
        return val
    legacy = _legacy_name(name)
    if legacy is not None:
        legacy_val = os.environ.get(legacy)
        if legacy_val is not None:
            if legacy not in _warned:
                _warned.add(legacy)
                print(
                    f"WARNING: {legacy} is deprecated; rename to {name} "
                    "(legacy fallback will be removed in a future release)",
                    file=sys.stderr,
                )
            return legacy_val
    return default


def env_set_for_test(new_name: str, value: str | None) -> None:
    """Test helper: set the new name and clear the legacy fallback so
    tests exercise the canonical path without warning noise."""
    legacy = _legacy_name(new_name)
    if legacy is not None:
        os.environ.pop(legacy, None)
    if value is None:
        os.environ.pop(new_name, None)
    else:
        os.environ[new_name] = value


def reset_deprecation_warnings() -> None:
    """Test helper: forget the one-time warning record so subsequent
    legacy reads warn again."""
    _warned.clear()
