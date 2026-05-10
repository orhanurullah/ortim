# SPDX-License-Identifier: FSL-1.1-Apache-2.0
# Copyright (c) 2026 ortim.dev
"""Tests for the per-role LLM client factory.

We avoid hitting the real Anthropic SDK by inspecting how the router resolves
provider/model from env vs args. Actual SDK init requires an API key so we
gate construction tests behind env, but the resolution logic is pure.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from runtime.llm import resolve_provider  # noqa: E402
from runtime.llm.router import _env_for, client_for  # noqa: E402


def _scrub_env(*keys: str) -> dict[str, str | None]:
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


def test_env_for_returns_value_when_set() -> None:
    saved = _scrub_env("ANALYST_PROVIDER")
    os.environ["ANALYST_PROVIDER"] = "deepseek"
    try:
        assert _env_for("analyst", "PROVIDER") == "deepseek"
    finally:
        _restore(saved)


def test_env_for_returns_none_when_unset_or_blank() -> None:
    saved = _scrub_env("ANALYST_PROVIDER")
    try:
        assert _env_for("analyst", "PROVIDER") is None
        os.environ["ANALYST_PROVIDER"] = "   "
        assert _env_for("analyst", "PROVIDER") is None
    finally:
        _restore(saved)


def test_client_for_falls_back_to_global_when_role_unset() -> None:
    """Without role-specific env vars, router uses LLM_PROVIDER + DEFAULT_MODEL.

    We need an API key for instantiation, so use a dummy ANTHROPIC_API_KEY.
    """
    saved = _scrub_env(
        "BABEL_PROVIDER", "BABEL_MODEL", "LLM_PROVIDER",
        "DEFAULT_MODEL", "ANTHROPIC_API_KEY",
    )
    os.environ["ANTHROPIC_API_KEY"] = "sk-ant-test"
    try:
        client = client_for("babel")
        assert client.provider == "anthropic"
        # default model comes from provider's default_model
        assert client.model == resolve_provider("anthropic").default_model
    finally:
        _restore(saved)


def test_role_env_overrides_global() -> None:
    saved = _scrub_env(
        "BABEL_PROVIDER", "BABEL_MODEL", "LLM_PROVIDER",
        "DEFAULT_MODEL", "ANTHROPIC_API_KEY", "DEEPSEEK_API_KEY",
    )
    os.environ["LLM_PROVIDER"] = "anthropic"
    os.environ["ANTHROPIC_API_KEY"] = "sk-ant-test"
    os.environ["DEEPSEEK_API_KEY"] = "sk-deepseek-test"
    os.environ["BABEL_PROVIDER"] = "deepseek"
    os.environ["BABEL_MODEL"] = "deepseek-chat"
    try:
        babel = client_for("babel")
        analyst = client_for("analyst")
        assert babel.provider == "deepseek"
        assert babel.model == "deepseek-chat"
        # Analyst with no override → anthropic
        assert analyst.provider == "anthropic"
    finally:
        _restore(saved)


def test_explicit_args_override_env() -> None:
    saved = _scrub_env(
        "BABEL_PROVIDER", "BABEL_MODEL", "LLM_PROVIDER",
        "DEFAULT_MODEL", "ANTHROPIC_API_KEY", "DEEPSEEK_API_KEY",
    )
    os.environ["BABEL_PROVIDER"] = "deepseek"
    os.environ["DEEPSEEK_API_KEY"] = "sk-deepseek-test"
    os.environ["ANTHROPIC_API_KEY"] = "sk-ant-test"
    try:
        client = client_for("babel", provider="anthropic", model="claude-opus-4-7")
        assert client.provider == "anthropic"
        assert client.model == "claude-opus-4-7"
    finally:
        _restore(saved)


def test_missing_api_key_raises() -> None:
    saved = _scrub_env(
        "BABEL_PROVIDER", "BABEL_MODEL", "LLM_PROVIDER",
        "DEFAULT_MODEL", "ANTHROPIC_API_KEY", "DEEPSEEK_API_KEY",
    )
    os.environ["BABEL_PROVIDER"] = "deepseek"
    try:
        client_for("babel")
    except RuntimeError as e:
        assert "DEEPSEEK_API_KEY" in str(e)
        return
    finally:
        _restore(saved)
    raise AssertionError("Expected RuntimeError when DEEPSEEK_API_KEY is missing")


if __name__ == "__main__":
    tests = [
        test_env_for_returns_value_when_set,
        test_env_for_returns_none_when_unset_or_blank,
        test_client_for_falls_back_to_global_when_role_unset,
        test_role_env_overrides_global,
        test_explicit_args_override_env,
        test_missing_api_key_raises,
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
