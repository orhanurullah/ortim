# SPDX-License-Identifier: FSL-1.1-Apache-2.0
# Copyright (c) 2026 ortim.dev
"""Smoke tests for the brownfield bootstrap helper.

These tests target `ortim.orchestrator.bootstrap_brownfield` directly
rather than spawning the CLI subprocess — Typer's runner brings up its own
console + signal handlers and is too noisy for a 200ms unit. The CLI
command in `ortim/main.py` is a thin wrapper around this helper, so
covering the helper covers the CLI's correctness.

Cases:
  29. `bootstrap_brownfield` on a Flutter sample → state advances to
      PRD_DRAFTING, app_class detected as 'mobile', .cache files created.
  30. `link_mode='symlink'` falls back to copy on systems where symlinks
      require elevation — we force this by patching Path.symlink_to.
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from ortim.orchestrator import (  # noqa: E402
    Project,
    ProjectState,
    bootstrap_brownfield,
)


def _make_flutter_sample(root: Path) -> Path:
    src = root / "flutter_app"
    (src / "lib" / "features" / "home").mkdir(parents=True)
    (src / "pubspec.yaml").write_text(
        "name: my_app\nflutter:\n  sdk: flutter\n",
        encoding="utf-8",
    )
    (src / "lib" / "main.dart").write_text(
        "import 'package:flutter/material.dart';\nvoid main() {}\n",
        encoding="utf-8",
    )
    (src / "lib" / "features" / "home" / "home_page.dart").write_text(
        "import 'package:flutter/material.dart';\n"
        "class HomePage extends StatelessWidget {}\n",
        encoding="utf-8",
    )
    return src


def test_bootstrap_brownfield_skips_babel_and_detects_mobile() -> None:
    """Test 29: brownfield → state=PRD_DRAFTING, app_class=mobile, cache present."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        src = _make_flutter_sample(tmp_path)
        workspace_root = tmp_path / "workspaces"

        # Force copy mode so we don't depend on Windows Developer Mode in CI.
        project, mode = bootstrap_brownfield(
            name="my-app",
            brief_tr="ana sayfaya arama çubuğu ekle",
            source_path=src,
            workspace_root=workspace_root,
            link_mode="copy",
            capture_baseline_on_bootstrap=False,
        )

        assert project.state == ProjectState.PRD_DRAFTING, project.state
        assert project.is_brownfield is True
        assert project.app_class == "mobile", (
            f"Flutter project must be detected as mobile; got {project.app_class}"
        )
        assert mode == "copy", mode

        ws = Project.workspace_path(project.id, workspace_root)
        assert (ws / "source" / "pubspec.yaml").exists()
        assert (ws / ".cache" / "codebase.json").exists()
        assert (ws / "intent.json").exists()
        assert (ws / "state.json").exists()


def test_bootstrap_brownfield_symlink_falls_back_to_copy() -> None:
    """Test 30: when symlinks require elevation, mode reports 'copy-fallback'."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        src = _make_flutter_sample(tmp_path)
        workspace_root = tmp_path / "workspaces"

        original_symlink = Path.symlink_to

        def _denied(self, target, target_is_directory=False):  # type: ignore[no-untyped-def]
            raise OSError("elevated privileges required (simulated)")

        with patch.object(Path, "symlink_to", _denied):
            project, mode = bootstrap_brownfield(
                name="my-app",
                brief_tr="brief",
                source_path=src,
                workspace_root=workspace_root,
                link_mode="symlink",
                capture_baseline_on_bootstrap=False,
            )
        # Sanity: patching restored
        assert Path.symlink_to is original_symlink

        assert mode == "copy-fallback", mode
        assert project.state == ProjectState.PRD_DRAFTING
