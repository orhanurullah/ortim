# SPDX-License-Identifier: FSL-1.1-Apache-2.0
# Copyright (c) 2026 ortim.dev
"""Bundled markdown assets (agents/, skills/, principles/, glossary/,
golden-paths/) shipped inside the wheel so PyPI installs don't depend on
the user having the source tree available.

`ortim.cli._globals.ASSETS_ROOT` resolves to the directory containing this
file. Loaders (`MemoryLoader`, `load_all_skills`, `doctor.check_*`) read
from there directly. No Python code lives here — this module exists only
to make the directory a real package so `importlib.resources` can find it.
"""
