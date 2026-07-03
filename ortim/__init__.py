# SPDX-License-Identifier: FSL-1.1-Apache-2.0
# Copyright (c) 2026 ortim.dev
"""Ortim runtime."""

from pathlib import Path as _Path

__version__ = "0.9.6"

# Path to the bundled markdown assets dir (`agents/`, `skills/`,
# `principles/`, `glossary/`, `golden-paths/`). Resolves correctly for
# both editable installs (repo's `ortim/_assets/`) and PyPI wheels
# (`site-packages/ortim/_assets/`). Loaders and doctor checks read here.
ASSETS_ROOT = _Path(__file__).resolve().parent / "_assets"
