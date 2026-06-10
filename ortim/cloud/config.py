# SPDX-License-Identifier: FSL-1.1-Apache-2.0
# Copyright (c) 2026 ortim.dev
"""Cloud connection config — ~/.ortim/cloud.toml (override with ORTIM_CLOUD_CONFIG).

    [cloud]
    base_url = "https://cloud.ortim.dev"
    email    = "dev@example.com"
    token    = "<jwt access_token>"

The token is the user's JWT access_token (extracted from the login Set-Cookie).
Kept separate from the provider key config (config.toml); different lifecycle.
"""

from __future__ import annotations

import os
import stat
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path

DEFAULT_BASE_URL = "https://cloud.ortim.dev"


@dataclass
class CloudConfig:
    base_url: str = DEFAULT_BASE_URL
    email: str | None = None
    token: str | None = None

    @property
    def logged_in(self) -> bool:
        return bool(self.token)


def default_path() -> Path:
    override = os.getenv("ORTIM_CLOUD_CONFIG")
    if override:
        return Path(override)
    return Path.home() / ".ortim" / "cloud.toml"


def load(path: Path | None = None) -> CloudConfig:
    """Read cloud config; return defaults (not None) when missing/broken so
    callers always have a usable base_url."""
    target = path or default_path()
    if not target.exists():
        return CloudConfig(base_url=os.getenv("ORTIM_CLOUD_URL", DEFAULT_BASE_URL))
    try:
        raw = tomllib.loads(target.read_text(encoding="utf-8"))
    except (tomllib.TOMLDecodeError, OSError) as e:
        print(f"[ortim] WARNING: failed to read {target}: {e}", file=sys.stderr)
        return CloudConfig()
    section = raw.get("cloud") if isinstance(raw.get("cloud"), dict) else {}
    base_url = section.get("base_url") or os.getenv("ORTIM_CLOUD_URL") or DEFAULT_BASE_URL
    cfg = CloudConfig(base_url=str(base_url).rstrip("/"))
    if isinstance(section.get("email"), str):
        cfg.email = section["email"]
    if isinstance(section.get("token"), str) and section["token"].strip():
        cfg.token = section["token"].strip()
    return cfg


def save(cfg: CloudConfig, path: Path | None = None) -> Path:
    target = path or default_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    lines = ["# Ortim Cloud config. Managed by `ortim cloud login`.", "[cloud]",
             f'base_url = "{_q(cfg.base_url)}"']
    if cfg.email:
        lines.append(f'email = "{_q(cfg.email)}"')
    if cfg.token:
        lines.append(f'token = "{_q(cfg.token)}"')
    target.write_text("\n".join(lines) + "\n", encoding="utf-8")
    if os.name == "posix":
        try:
            os.chmod(target, stat.S_IRUSR | stat.S_IWUSR)
        except OSError:
            pass
    return target


def _q(s: str) -> str:
    return s.replace("\\", "\\\\").replace('"', '\\"')
