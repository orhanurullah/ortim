# SPDX-License-Identifier: FSL-1.1-Apache-2.0
# Copyright (c) 2026 ortim.dev
"""ortim/cli — CLI komut modülleri.

Bu paket main.py'deki 4700+ satırı sorumluluğa göre bölünmüş
modüllere ayırır:

  _globals.py  — REPO_ROOT, WORKSPACE_ROOT, console, paylaşılan helper'lar
  workspace.py — init, new, ls, use, list-projects + workspace/* subcommands
  planning.py  — run, advance, gates, states, refine, show, lock,
                 extend, extensions, scope + dialog/extend helper'lar
  execution.py — tasks, execute, run-all + skill/* subcommands
  reporting.py — budget, retro, drift-check, score-tier, mutation-test
  admin.py     — doctor, demo
"""
