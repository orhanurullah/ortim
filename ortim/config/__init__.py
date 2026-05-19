# SPDX-License-Identifier: FSL-1.1-Apache-2.0
# Copyright (c) 2026 ortim.dev
"""User-level persistent configuration for ortim.

`~/.ortim/config.toml` provides a cwd-independent provider/key store so
PyPI users do not have to scatter `.env` files across every project
directory. The file is the lowest-precedence layer: CLI flags and shell
env vars (including `.env`-loaded ones) always win.
"""

from ortim.config.store import (
    PROVIDER_BASE_URL_ENV,
    PROVIDER_KEY_ENV,
    Config,
    apply_to_env,
    default_path,
    env_source,
    load,
    save,
)

__all__ = [
    "Config",
    "PROVIDER_BASE_URL_ENV",
    "PROVIDER_KEY_ENV",
    "apply_to_env",
    "default_path",
    "env_source",
    "load",
    "save",
]
