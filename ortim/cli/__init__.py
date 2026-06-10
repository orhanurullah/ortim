# SPDX-License-Identifier: FSL-1.1-Apache-2.0
# Copyright (c) 2026 ortim.dev
"""ortim/cli — CLI command modules.

This package splits the 4700+ lines of main.py into modules grouped
by responsibility:

  _globals.py  — REPO_ROOT, WORKSPACE_ROOT, console, shared helpers
  workspace.py — init, new, ls, use, list-projects + workspace/* subcommands
  planning.py  — run, advance, gates, states, refine, show, lock,
                 extend, extensions, scope + dialog/extend helpers
  execution.py — tasks, execute, run-all + skill/* subcommands
  reporting.py — budget, retro, drift-check, score-tier, mutation-test
  admin.py     — doctor, demo
"""
