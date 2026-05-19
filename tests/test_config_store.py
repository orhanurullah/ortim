# SPDX-License-Identifier: FSL-1.1-Apache-2.0
# Copyright (c) 2026 ortim.dev
"""Tests for the user config store (`~/.ortim/config.toml`).

Covers: TOML read/write roundtrip, env-vs-config precedence in
`apply_to_env`, malformed-file tolerance, and `env_source` labeling.
The tests redirect the config path via `ORTIM_CONFIG` to a tmp file so
the operator's real `~/.ortim/config.toml` is never touched.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from ortim.config import store  # noqa: E402
from ortim.config.store import Config  # noqa: E402


@pytest.fixture
def isolated_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Point the config store at a tmp path + scrub the populated-set so
    each test starts from a clean slate. Also scrubs the env vars the
    store touches so test order can't leak state."""
    cfg_path = tmp_path / "config.toml"
    monkeypatch.setenv("ORTIM_CONFIG", str(cfg_path))
    for env in (
        "LLM_PROVIDER", "DEFAULT_MODEL",
        "ANTHROPIC_API_KEY", "DEEPSEEK_API_KEY", "OLLAMA_BASE_URL",
        "ARCHITECT_PROVIDER", "ARCHITECT_MODEL",
        "BABEL_PROVIDER", "BABEL_MODEL",
    ):
        monkeypatch.delenv(env, raising=False)
    store._POPULATED_FROM_CONFIG.clear()
    return cfg_path


def test_load_missing_file_returns_none(isolated_config: Path) -> None:
    assert not isolated_config.exists()
    assert store.load() is None


def test_save_and_load_roundtrip(isolated_config: Path) -> None:
    cfg = Config(
        default_provider="deepseek",
        default_model="deepseek-chat",
        provider_keys={"deepseek": "sk-test-xyz"},
        provider_base_urls={"ollama": "http://other-host:11434/v1"},
        roles={"architect_provider": "anthropic", "architect_model": "claude-opus-4-7"},
    )
    written_to = store.save(cfg)
    assert written_to == isolated_config

    loaded = store.load()
    assert loaded is not None
    assert loaded.default_provider == "deepseek"
    assert loaded.default_model == "deepseek-chat"
    assert loaded.provider_keys == {"deepseek": "sk-test-xyz"}
    assert loaded.provider_base_urls == {"ollama": "http://other-host:11434/v1"}
    assert loaded.roles == {
        "architect_provider": "anthropic",
        "architect_model": "claude-opus-4-7",
    }


def test_apply_to_env_does_not_override_existing(
    isolated_config: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`.env` / shell env always wins. Config only fills gaps."""
    monkeypatch.setenv("LLM_PROVIDER", "anthropic")  # pre-existing
    cfg = Config(
        default_provider="deepseek",
        provider_keys={"deepseek": "sk-from-config"},
    )
    populated = store.apply_to_env(cfg)

    # LLM_PROVIDER was pre-set → config does NOT override.
    assert os.environ["LLM_PROVIDER"] == "anthropic"
    assert "LLM_PROVIDER" not in populated

    # DEEPSEEK_API_KEY was unset → config populates.
    assert os.environ["DEEPSEEK_API_KEY"] == "sk-from-config"
    assert "DEEPSEEK_API_KEY" in populated


def test_apply_to_env_populates_when_unset(isolated_config: Path) -> None:
    cfg = Config(
        default_provider="ollama",
        default_model="qwen2.5-coder:7b",
        provider_base_urls={"ollama": "http://localhost:11434/v1"},
    )
    populated = store.apply_to_env(cfg)

    assert os.environ["LLM_PROVIDER"] == "ollama"
    assert os.environ["DEFAULT_MODEL"] == "qwen2.5-coder:7b"
    assert os.environ["OLLAMA_BASE_URL"] == "http://localhost:11434/v1"
    assert set(populated) == {"LLM_PROVIDER", "DEFAULT_MODEL", "OLLAMA_BASE_URL"}


def test_role_overrides_promoted_as_uppercase_env(isolated_config: Path) -> None:
    cfg = Config(
        roles={"architect_provider": "anthropic", "babel_model": "deepseek-chat"},
    )
    store.apply_to_env(cfg)
    assert os.environ["ARCHITECT_PROVIDER"] == "anthropic"
    assert os.environ["BABEL_MODEL"] == "deepseek-chat"


def test_env_source_labels(
    isolated_config: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "anthropic")  # pre-existing → "env"
    cfg = Config(
        default_provider="deepseek",  # shadowed by env
        provider_keys={"deepseek": "sk-x"},  # populates DEEPSEEK_API_KEY
    )
    store.apply_to_env(cfg)

    assert store.env_source("LLM_PROVIDER") == "env"
    assert store.env_source("DEEPSEEK_API_KEY") == "config"
    assert store.env_source("ANTHROPIC_API_KEY") == "default"


def test_malformed_toml_returns_none_with_warning(
    isolated_config: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    isolated_config.write_text("[provider\nbroken = ", encoding="utf-8")
    assert store.load() is None
    captured = capsys.readouterr()
    assert "WARNING" in captured.err
    assert "failed to read config" in captured.err


def test_parser_ignores_non_dict_sections(isolated_config: Path) -> None:
    """Garbage shapes (e.g. `provider = "x"` instead of `[provider]`) must
    not crash. The parser silently skips non-dict sections."""
    isolated_config.write_text(
        'provider = "anthropic"\nproviders = "broken"\nroles = []\n',
        encoding="utf-8",
    )
    cfg = store.load()
    assert cfg is not None
    assert cfg.default_provider is None  # garbage shape → ignored


def test_serialize_handles_quote_escaping(isolated_config: Path) -> None:
    cfg = Config(
        default_provider="anthropic",
        provider_keys={"anthropic": 'sk-with-"quote"-and-\\backslash'},
    )
    store.save(cfg)
    loaded = store.load()
    assert loaded is not None
    assert loaded.provider_keys["anthropic"] == 'sk-with-"quote"-and-\\backslash'


def test_default_path_honors_env_override(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "custom.toml"
    monkeypatch.setenv("ORTIM_CONFIG", str(target))
    assert store.default_path() == target


def test_default_path_falls_back_to_home(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ORTIM_CONFIG", raising=False)
    expected = Path.home() / ".ortim" / "config.toml"
    assert store.default_path() == expected


if __name__ == "__main__":
    import subprocess
    raise SystemExit(subprocess.call([sys.executable, "-m", "pytest", __file__, "-v"]))
