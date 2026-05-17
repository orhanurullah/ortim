# SPDX-License-Identifier: FSL-1.1-Apache-2.0
# Copyright (c) 2026 ortim.dev
"""Smoke tests for the LLM provider registry."""

from __future__ import annotations

import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from ortim.llm.providers import (  # noqa: E402
    PROVIDERS,
    UnknownProvider,
    pricing_for,
    resolve_provider,
)


def test_registry_has_anthropic_and_deepseek() -> None:
    assert "anthropic" in PROVIDERS
    assert "deepseek" in PROVIDERS


def test_anthropic_has_no_base_url() -> None:
    cfg = PROVIDERS["anthropic"]
    assert cfg.base_url is None
    assert cfg.api_key_env == "ANTHROPIC_API_KEY"
    assert cfg.default_model.startswith("claude-")


def test_deepseek_uses_anthropic_compatible_endpoint() -> None:
    cfg = PROVIDERS["deepseek"]
    assert cfg.base_url == "https://api.deepseek.com/anthropic"
    assert cfg.api_key_env == "DEEPSEEK_API_KEY"
    assert cfg.default_model.startswith("deepseek-")


def test_resolve_defaults_to_anthropic_via_env() -> None:
    prev = os.environ.pop("LLM_PROVIDER", None)
    try:
        cfg = resolve_provider()
        assert cfg.name == "anthropic"
    finally:
        if prev is not None:
            os.environ["LLM_PROVIDER"] = prev


def test_resolve_reads_env() -> None:
    prev = os.environ.get("LLM_PROVIDER")
    os.environ["LLM_PROVIDER"] = "deepseek"
    try:
        cfg = resolve_provider()
        assert cfg.name == "deepseek"
    finally:
        if prev is None:
            os.environ.pop("LLM_PROVIDER", None)
        else:
            os.environ["LLM_PROVIDER"] = prev


def test_resolve_explicit_arg_wins_over_env() -> None:
    prev = os.environ.get("LLM_PROVIDER")
    os.environ["LLM_PROVIDER"] = "deepseek"
    try:
        cfg = resolve_provider("anthropic")
        assert cfg.name == "anthropic"
    finally:
        if prev is None:
            os.environ.pop("LLM_PROVIDER", None)
        else:
            os.environ["LLM_PROVIDER"] = prev


def test_resolve_rejects_unknown() -> None:
    try:
        resolve_provider("not-a-real-provider")
    except UnknownProvider:
        return
    raise AssertionError("Expected UnknownProvider")


def test_pricing_for_known_provider() -> None:
    in_p, out_p = pricing_for("deepseek", "deepseek-chat")
    assert in_p == PROVIDERS["deepseek"].input_usd_per_m
    assert out_p == PROVIDERS["deepseek"].output_usd_per_m


def test_pricing_for_unknown_provider_falls_back_to_anthropic() -> None:
    in_p, out_p = pricing_for("rumored-provider", "x")
    assert in_p == PROVIDERS["anthropic"].input_usd_per_m
    assert out_p == PROVIDERS["anthropic"].output_usd_per_m


if __name__ == "__main__":
    tests = [
        test_registry_has_anthropic_and_deepseek,
        test_anthropic_has_no_base_url,
        test_deepseek_uses_anthropic_compatible_endpoint,
        test_resolve_defaults_to_anthropic_via_env,
        test_resolve_reads_env,
        test_resolve_explicit_arg_wins_over_env,
        test_resolve_rejects_unknown,
        test_pricing_for_known_provider,
        test_pricing_for_unknown_provider_falls_back_to_anthropic,
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
