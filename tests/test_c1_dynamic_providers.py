# SPDX-License-Identifier: FSL-1.1-Apache-2.0
# Copyright (c) 2026 ortim.dev
"""C1 acceptance tests — dynamic providers + setup-local wizard.

Covers the locked behaviors from docs/plans/pro-grade-transition.md §1.1
and §1.2:

  * Deep, per-field merge of `[providers.<name>]` over built-ins
  * Default `api_kind = "openai"` for custom providers
  * Per-model pricing override via nested `[providers.<n>.models."<m>"]`
  * `ortim config setup-local` idempotency
  * Clean exit when Ollama is not reachable
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import pytest  # noqa: E402


@pytest.fixture()
def _pristine_providers():
    """Snapshot + restore the provider registries around a test.

    The registries are merged **in place** (never `importlib.reload`d):
    reloading the module creates new `UnknownProvider` / `ProviderConfig`
    class objects while every previously-imported binding (ortim.llm
    package, other test modules) keeps the old ones — `except
    UnknownProvider` then silently stops catching. That identity break
    leaked across test files and made the suite order-dependent."""
    import ortim.llm.providers as providers

    saved = dict(providers.PROVIDERS)
    saved_overrides = dict(providers.MODEL_PRICING_OVERRIDES)
    yield providers
    providers.PROVIDERS.clear()
    providers.PROVIDERS.update(saved)
    providers.MODEL_PRICING_OVERRIDES.clear()
    providers.MODEL_PRICING_OVERRIDES.update(saved_overrides)


def _merge_config(providers, toml_path: Path, monkeypatch) -> object:
    """Point ORTIM_CONFIG at `toml_path` and re-run `_merge_providers()`
    against the temp config, mutating the registries in place."""
    monkeypatch.setenv("ORTIM_CONFIG", str(toml_path))
    providers._merge_providers()
    return providers


# ---------------------------------------------------------------------
# Provider TOML merge — partial-field override
# ---------------------------------------------------------------------


def test_provider_toml_partial_override(
    tmp_path, monkeypatch, _pristine_providers
) -> None:
    """Setting only base_url for an existing provider must leave pricing,
    default_model, and api_key_env intact — the deep-merge contract."""
    cfg = tmp_path / "config.toml"
    cfg.write_text(
        '[providers.anthropic]\n'
        'base_url = "https://proxy.internal/anthropic"\n',
        encoding="utf-8",
    )
    providers = _merge_config(_pristine_providers, cfg, monkeypatch)
    p = providers.PROVIDERS["anthropic"]
    assert p.base_url == "https://proxy.internal/anthropic"
    # Built-in fields survive the override.
    assert p.api_key_env == "ANTHROPIC_API_KEY"
    assert p.default_model.startswith("claude-")
    assert p.input_usd_per_m == 15.0
    assert p.output_usd_per_m == 75.0
    assert p.api_kind == "anthropic"


def test_provider_api_kind_defaults_openai(
    tmp_path, monkeypatch, _pristine_providers
) -> None:
    """A brand-new provider with no api_kind set falls back to "openai"
    — most third-party gateways speak the OpenAI dialect."""
    cfg = tmp_path / "config.toml"
    cfg.write_text(
        '[providers.openrouter]\n'
        'base_url    = "https://openrouter.ai/api/v1"\n'
        'api_key_env = "OPENROUTER_API_KEY"\n'
        'default_model = "anthropic/claude-3.5-sonnet"\n',
        encoding="utf-8",
    )
    providers = _merge_config(_pristine_providers, cfg, monkeypatch)
    p = providers.PROVIDERS["openrouter"]
    assert p.api_kind == "openai"
    assert p.base_url == "https://openrouter.ai/api/v1"
    assert p.api_key_env == "OPENROUTER_API_KEY"


def test_provider_model_pricing_override(
    tmp_path, monkeypatch, _pristine_providers
) -> None:
    """Nested per-model pricing wins over the provider's flat rate."""
    cfg = tmp_path / "config.toml"
    cfg.write_text(
        '[providers.openrouter]\n'
        'base_url        = "https://openrouter.ai/api/v1"\n'
        'api_key_env     = "OPENROUTER_API_KEY"\n'
        'input_usd_per_m = 1.0\n'
        'output_usd_per_m = 2.0\n'
        '\n'
        '[providers.openrouter.models."anthropic/claude-3.5-sonnet"]\n'
        'input_usd_per_m  = 3.0\n'
        'output_usd_per_m = 15.0\n',
        encoding="utf-8",
    )
    providers = _merge_config(_pristine_providers, cfg, monkeypatch)
    in_p, out_p = providers.pricing_for(
        "openrouter", "anthropic/claude-3.5-sonnet"
    )
    assert (in_p, out_p) == (3.0, 15.0)
    # A model without an override falls back to the provider-level rate.
    in_p2, out_p2 = providers.pricing_for("openrouter", "some/other-model")
    assert (in_p2, out_p2) == (1.0, 2.0)


# ---------------------------------------------------------------------
# setup-local wizard
# ---------------------------------------------------------------------


def _fake_ok_http_response() -> MagicMock:
    """A 200 OK GET / response from a healthy local Ollama probe."""
    res = MagicMock()
    res.status = 200
    res.read = MagicMock(return_value=b"Ollama is running")
    return res


def _fake_ollama_show_success() -> MagicMock:
    """`ollama show qwen2.5-coder:7b` returncode 0 — model present."""
    r = MagicMock()
    r.returncode = 0
    return r


def test_setup_local_idempotent(tmp_path, monkeypatch, _pristine_providers) -> None:
    """Running `ortim config setup-local --mode hybrid` twice must
    produce a byte-identical config.toml on the second run."""
    cfg_path = tmp_path / "config.toml"
    monkeypatch.setenv("ORTIM_CONFIG", str(cfg_path))

    from typer.testing import CliRunner
    from ortim.config.cli import config_app

    runner = CliRunner()

    conn = MagicMock()
    conn.getresponse = MagicMock(return_value=_fake_ok_http_response())

    with patch("http.client.HTTPConnection", return_value=conn), \
         patch("subprocess.run", return_value=_fake_ollama_show_success()):
        first = runner.invoke(config_app, ["setup-local", "--mode", "hybrid"])
        assert first.exit_code == 0, first.output
        first_bytes = cfg_path.read_bytes()

        second = runner.invoke(config_app, ["setup-local", "--mode", "hybrid"])
        assert second.exit_code == 0, second.output
        second_bytes = cfg_path.read_bytes()

    assert first_bytes == second_bytes, (
        "setup-local must be idempotent — second run mutated config.toml"
    )


def test_setup_local_ollama_absent_exit_1(tmp_path, monkeypatch) -> None:
    """Connection refused → user-friendly download URL + exit 1.
    No traceback, no config mutation."""
    cfg_path = tmp_path / "config.toml"
    monkeypatch.setenv("ORTIM_CONFIG", str(cfg_path))

    from typer.testing import CliRunner
    from ortim.config.cli import config_app

    runner = CliRunner()

    # Force the probe to fail like a real "Ollama not installed" box.
    conn = MagicMock()
    conn.request = MagicMock(side_effect=ConnectionRefusedError("nope"))

    with patch("http.client.HTTPConnection", return_value=conn):
        result = runner.invoke(config_app, ["setup-local", "--mode", "hybrid"])

    assert result.exit_code == 1
    assert "ollama.com/download" in result.output
    assert not cfg_path.exists(), (
        "setup-local must not write config.toml when Ollama is unreachable"
    )


if __name__ == "__main__":
    # Manual harness mirroring tests/test_llm_providers.py for environments
    # where pytest is unavailable. Uses pytest's monkeypatch only when
    # invoked via `pytest`; otherwise each test should be skipped here.
    print("Run via: pytest tests/test_c1_dynamic_providers.py")
