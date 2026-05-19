# SPDX-License-Identifier: FSL-1.1-Apache-2.0
# Copyright (c) 2026 ortim.dev
"""Persistent user configuration store.

Stored at `~/.ortim/config.toml` (overridable via `ORTIM_CONFIG` env).
Schema:

    [provider]
    default = "deepseek"                # global LLM_PROVIDER fallback
    default_model = "deepseek-chat"     # optional DEFAULT_MODEL fallback

    [providers.anthropic]
    api_key = "sk-ant-..."
    [providers.deepseek]
    api_key = "sk-..."
    [providers.ollama]
    base_url = "http://localhost:11434/v1"

    [roles]
    architect_provider = "anthropic"
    architect_model = "claude-opus-4-7"

Precedence model: `apply_to_env(cfg)` copies values into `os.environ`
only when the target env var is currently unset. So the effective order
becomes `CLI flag > shell/.env env > config file > hardcoded default`,
without the router code needing to know about the config layer at all.
"""

from __future__ import annotations

import os
import stat
import sys
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

# Provider → env var that holds its API key. Local providers (ollama)
# have no key, so they are absent here by design.
PROVIDER_KEY_ENV: dict[str, str] = {
    "anthropic": "ANTHROPIC_API_KEY",
    "deepseek": "DEEPSEEK_API_KEY",
}

# Provider → env var for a base-URL override. Only providers whose
# `LLMClient` reads a base-URL env appear here; keep this in sync with
# `ortim.llm.client.LLMClient.__init__`.
PROVIDER_BASE_URL_ENV: dict[str, str] = {
    "ollama": "OLLAMA_BASE_URL",
}

# Tracks env-var names that `apply_to_env` populated from the config
# file during this process. `env_source()` consults this set so
# `ortim config show` can label rows as "config" vs "env" vs "default".
_POPULATED_FROM_CONFIG: set[str] = set()


@dataclass
class Config:
    """In-memory representation of `~/.ortim/config.toml`.

    Fields default to empty/None — an empty config is a valid state
    (means "use env + defaults"). All string values are stripped and
    lowercased on read where case is not user-facing (provider names,
    role keys); raw values like `api_key` keep their original case.
    """

    default_provider: str | None = None
    default_model: str | None = None
    provider_keys: dict[str, str] = field(default_factory=dict)
    provider_base_urls: dict[str, str] = field(default_factory=dict)
    # Flat dict like {"architect_provider": "anthropic",
    # "architect_model": "claude-opus-4-7"}. Keys mirror the env-var
    # convention the router consults — see `ortim.llm.router._env_for`.
    roles: dict[str, str] = field(default_factory=dict)


def default_path() -> Path:
    """Path to the user config file. `ORTIM_CONFIG` env overrides for tests."""
    override = os.getenv("ORTIM_CONFIG")
    if override:
        return Path(override)
    return Path.home() / ".ortim" / "config.toml"


def load(path: Path | None = None) -> Config | None:
    """Read the config from disk; return None when the file is missing
    or unreadable. Malformed TOML logs a stderr warning and returns None
    rather than crashing — a broken config must never block CLI startup."""
    target = path or default_path()
    if not target.exists():
        return None
    try:
        raw = tomllib.loads(target.read_text(encoding="utf-8"))
    except (tomllib.TOMLDecodeError, OSError) as e:
        print(
            f"[ortim] WARNING: failed to read config {target}: {e}",
            file=sys.stderr,
        )
        return None
    return _parse(raw)


def _parse(raw: dict) -> Config:
    cfg = Config()

    provider_section = raw.get("provider")
    if isinstance(provider_section, dict):
        default = provider_section.get("default")
        if isinstance(default, str) and default.strip():
            cfg.default_provider = default.strip().lower()
        default_model = provider_section.get("default_model")
        if isinstance(default_model, str) and default_model.strip():
            cfg.default_model = default_model.strip()

    providers_section = raw.get("providers")
    if isinstance(providers_section, dict):
        for name, body in providers_section.items():
            if not isinstance(body, dict):
                continue
            key = body.get("api_key")
            if isinstance(key, str) and key.strip():
                cfg.provider_keys[str(name).lower()] = key.strip()
            url = body.get("base_url")
            if isinstance(url, str) and url.strip():
                cfg.provider_base_urls[str(name).lower()] = url.strip()

    roles_section = raw.get("roles")
    if isinstance(roles_section, dict):
        for k, v in roles_section.items():
            if isinstance(v, str) and v.strip():
                cfg.roles[str(k).lower()] = v.strip()
    return cfg


def apply_to_env(cfg: Config) -> list[str]:
    """Copy config values into `os.environ` only where the target var is
    unset. Returns the list of env-var names populated from config so
    callers (`ortim config show`) can attribute sources.

    Never overwrites an already-set var — operators who export
    `LLM_PROVIDER=ollama` in their shell or `.env` always win over the
    config file.
    """
    populated: list[str] = []

    def _set(name: str, value: str | None) -> None:
        if not value:
            return
        if os.environ.get(name):
            return
        os.environ[name] = value
        populated.append(name)

    _set("LLM_PROVIDER", cfg.default_provider)
    _set("DEFAULT_MODEL", cfg.default_model)

    for provider, key in cfg.provider_keys.items():
        env_name = PROVIDER_KEY_ENV.get(provider)
        if env_name:
            _set(env_name, key)

    for provider, url in cfg.provider_base_urls.items():
        env_name = PROVIDER_BASE_URL_ENV.get(provider)
        if env_name:
            _set(env_name, url)

    # Role overrides are stored with the exact env-var stem the router
    # already reads: `architect_provider` → `ARCHITECT_PROVIDER`.
    for k, v in cfg.roles.items():
        _set(k.upper(), v)

    _POPULATED_FROM_CONFIG.update(populated)
    return populated


def env_source(name: str) -> str:
    """Where did this env var's current value come from?

    Returns one of:
      * "config"  — populated from `~/.ortim/config.toml` by `apply_to_env`
      * "env"     — already in `os.environ` (shell, `.env`, or earlier)
      * "default" — unset; consumers will fall back to hardcoded defaults

    Cannot distinguish shell env vs `.env` — both look identical to
    `os.environ` once `load_dotenv` has run.
    """
    if name in _POPULATED_FROM_CONFIG:
        return "config"
    if os.environ.get(name):
        return "env"
    return "default"


def save(cfg: Config, path: Path | None = None) -> Path:
    """Persist the config to disk. Creates the parent dir as needed and
    sets 0600 perms on POSIX so an `api_key` cannot leak to other local
    users. On Windows ACLs are not touched — operators with multi-user
    boxes should rely on profile-level isolation."""
    target = path or default_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(_serialize(cfg), encoding="utf-8")
    if os.name == "posix":
        try:
            os.chmod(target, stat.S_IRUSR | stat.S_IWUSR)
        except OSError:
            # chmod can legitimately fail on exotic filesystems (NFS
            # squash, FAT mounts); permission tightening is best-effort.
            pass
    return target


def _serialize(cfg: Config) -> str:
    """Hand-rolled TOML writer. The schema is small, fixed, and entirely
    ours, so pulling `tomli_w` as a runtime dep buys nothing."""
    lines: list[str] = [
        "# Ortim user config. Edit by hand or run `ortim config init`.",
        "# Stored at ~/.ortim/config.toml; chmod 600 on Unix (auto-set on save).",
        "",
    ]
    if cfg.default_provider or cfg.default_model:
        lines.append("[provider]")
        if cfg.default_provider:
            lines.append(f'default = "{_q(cfg.default_provider)}"')
        if cfg.default_model:
            lines.append(f'default_model = "{_q(cfg.default_model)}"')
        lines.append("")

    for name in sorted(set(cfg.provider_keys) | set(cfg.provider_base_urls)):
        lines.append(f"[providers.{name}]")
        if name in cfg.provider_keys:
            lines.append(f'api_key = "{_q(cfg.provider_keys[name])}"')
        if name in cfg.provider_base_urls:
            lines.append(f'base_url = "{_q(cfg.provider_base_urls[name])}"')
        lines.append("")

    if cfg.roles:
        lines.append("[roles]")
        for k in sorted(cfg.roles):
            lines.append(f'{k} = "{_q(cfg.roles[k])}"')
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def _q(s: str) -> str:
    """Escape for a basic TOML `"..."` literal. The schema rejects
    newlines/control chars at the typer-prompt layer so we only need to
    handle `"` and `\\` here."""
    return s.replace("\\", "\\\\").replace('"', '\\"')
