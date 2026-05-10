# SPDX-License-Identifier: FSL-1.1-Apache-2.0
# Copyright (c) 2026 ortim.dev
"""Unit tests for runtime.codebase.reader.scan_codebase.

Coverage map (M1-plan §A.2 tests 1–7):
  1. Empty directory → file_count=0, truncated=False.
  2. This repo's runtime/ tree → modules include runtime executor + orchestrator.
  3. Flutter sample fixture → frameworks=flutter, modules include lib/features/foo/.
  4. max_files cap → truncated=True.
  5. .gitignore-listed build/ dir is excluded.
  6. Cache hit: rescanning with cache_path skips re-parsing unchanged files.
  7. Cache invalidation: modifying one file reparses only that file.
"""

from __future__ import annotations

import os
import sys
import tempfile
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from runtime.codebase import read_related, scan_codebase  # noqa: E402
from runtime.codebase.schema import (  # noqa: E402
    CodebaseSummary,
    FileEntry,
    ModuleSymbols,
)

FLUTTER_SAMPLE = REPO_ROOT / "fixtures" / "flutter-sample"


def test_empty_directory_yields_empty_summary() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        summary = scan_codebase(Path(tmp))
        assert summary.file_count == 0
        assert summary.truncated is False
        assert summary.files == []
        assert summary.frameworks == []
        assert summary.modules == []
        assert summary.app_class_hint is None
        assert summary.last_scan_stats is not None
        assert summary.last_scan_stats.files_walked == 0


def test_scans_this_repo_runtime_tree() -> None:
    """Scanning runtime/ should recognise pytest as tooling and surface modules."""
    summary = scan_codebase(REPO_ROOT, max_files=3000)
    # We should not blow the cap on this repo (well under 3000 files post-skip).
    assert summary.truncated is False, (
        f"runtime/ scan unexpectedly truncated; walked={summary.file_count}"
    )
    # Pytest is configured in pyproject.toml + tests/ dir → must surface.
    fw_names = {f.name for f in summary.frameworks}
    assert "pytest" in fw_names, (
        f"pytest not detected; frameworks={[(f.name, f.confidence) for f in summary.frameworks]}"
    )
    # At least one module under runtime/executor and one under runtime/orchestrator.
    module_paths = [m.path for m in summary.modules]
    assert any(p.startswith("runtime/executor/") for p in module_paths), module_paths[:10]
    assert any(p.startswith("runtime/orchestrator/") for p in module_paths), module_paths[:10]


def test_flutter_fixture_detected_with_correct_app_class() -> None:
    summary = scan_codebase(FLUTTER_SAMPLE)
    fw_names = {f.name for f in summary.frameworks}
    assert "flutter" in fw_names, (
        f"flutter not detected; got {[(f.name, f.confidence) for f in summary.frameworks]}"
    )
    flutter = next(f for f in summary.frameworks if f.name == "flutter")
    assert flutter.confidence > 0.6, flutter
    assert summary.app_class_hint == "mobile", summary.app_class_hint
    # The fixture has FooPage and FooController as top-level classes.
    paths = {m.path for m in summary.modules}
    assert "lib/features/foo/foo_page.dart" in paths, paths
    assert "lib/features/foo/foo_controller.dart" in paths, paths
    foo_page = next(m for m in summary.modules if m.path.endswith("foo_page.dart"))
    assert "FooPage" in foo_page.public_names, foo_page.public_names


def test_max_files_cap_marks_truncated() -> None:
    """A tiny cap forces truncation on the Flutter fixture (4 files)."""
    summary = scan_codebase(FLUTTER_SAMPLE, max_files=2)
    assert summary.truncated is True
    assert summary.file_count == 2


def test_gitignored_build_dir_is_excluded() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / ".gitignore").write_text("build/\n", encoding="utf-8")
        (root / "src").mkdir()
        (root / "src" / "main.py").write_text("def main(): pass\n", encoding="utf-8")
        (root / "build").mkdir()
        (root / "build" / "artifact.txt").write_text("compiled", encoding="utf-8")
        (root / "build" / "deep").mkdir()
        (root / "build" / "deep" / "nested.py").write_text("x = 1\n", encoding="utf-8")

        summary = scan_codebase(root)
        paths = [fe.path for fe in summary.files]
        assert "src/main.py" in paths
        assert all(not p.startswith("build/") for p in paths), paths


def test_cache_hit_skips_reparse() -> None:
    """Second scan with the same cache_path should reuse all entries."""
    with tempfile.TemporaryDirectory() as tmp:
        cache = Path(tmp) / "codebase.json"
        first = scan_codebase(FLUTTER_SAMPLE, cache_path=cache)
        assert first.last_scan_stats is not None
        assert first.last_scan_stats.files_parsed_fresh > 0
        assert first.last_scan_stats.files_parsed_from_cache == 0
        assert cache.exists()

        second = scan_codebase(FLUTTER_SAMPLE, cache_path=cache)
        assert second.last_scan_stats is not None
        # All previously-parsed files should hit the cache; nothing fresh.
        assert second.last_scan_stats.files_parsed_fresh == 0, (
            f"Expected zero fresh parses on rescan; "
            f"got {second.last_scan_stats.files_parsed_fresh}"
        )
        assert second.last_scan_stats.files_parsed_from_cache == first.file_count
        # Same modules and frameworks should be present.
        assert {m.path for m in second.modules} == {m.path for m in first.modules}
        assert {f.name for f in second.frameworks} == {f.name for f in first.frameworks}


def test_cache_invalidates_only_changed_file() -> None:
    """Modifying one file should make exactly one file parse fresh on rescan."""
    with tempfile.TemporaryDirectory() as tmp:
        # Copy fixture into a writable location so we can mutate it.
        root = Path(tmp) / "project"
        _copytree(FLUTTER_SAMPLE, root)
        cache = Path(tmp) / "codebase.json"

        first = scan_codebase(root, cache_path=cache)
        assert first.last_scan_stats is not None
        first_file_count = first.file_count

        # Mutate one file. Sleep briefly to ensure mtime changes on Windows.
        target = root / "lib" / "features" / "foo" / "foo_controller.dart"
        time.sleep(0.05)
        target.write_text(
            "class FooController {\n"
            "  String greeting() => 'Hello, Bar!';\n"
            "  String farewell() => 'Bye!';\n"
            "}\n",
            encoding="utf-8",
        )
        # Force an mtime distinct from the prior scan even on coarse-grained FS.
        future = time.time() + 5
        os.utime(target, (future, future))

        second = scan_codebase(root, cache_path=cache)
        assert second.last_scan_stats is not None
        assert second.file_count == first_file_count
        assert second.last_scan_stats.files_parsed_fresh == 1, (
            f"Expected exactly one fresh parse; "
            f"got {second.last_scan_stats.files_parsed_fresh}"
        )
        # Verify the mutated file's symbols updated.
        foo = next(m for m in second.modules if m.path.endswith("foo_controller.dart"))
        assert "farewell" in foo.public_names, foo.public_names


def _copytree(src: Path, dst: Path) -> None:
    """Minimal recursive copy (avoids importing shutil for clarity)."""
    dst.mkdir(parents=True, exist_ok=True)
    for entry in src.iterdir():
        target = dst / entry.name
        if entry.is_dir():
            _copytree(entry, target)
        else:
            target.write_bytes(entry.read_bytes())


# ---- Day 2: read_related tests (8–12) -------------------------------------


def test_read_related_picks_files_under_module_scope() -> None:
    """Direct match: every file under lib/features/foo/ should be returned."""
    summary = scan_codebase(FLUTTER_SAMPLE)
    out = read_related(
        summary=summary,
        root=FLUTTER_SAMPLE,
        module_scope=["lib/features/foo"],
        task_description="",
        max_total_bytes=10_000,
    )
    paths = set(out)
    assert "lib/features/foo/foo_page.dart" in paths, paths
    assert "lib/features/foo/foo_controller.dart" in paths, paths
    # main.dart is NOT under foo/ — must be excluded.
    assert "lib/main.dart" not in paths, paths


def test_read_related_description_matches_class_names() -> None:
    """Description-only signal: a CamelCase class name in the brief picks up the file."""
    summary = scan_codebase(FLUTTER_SAMPLE)
    # No module_scope — only the description signal can pull files in.
    out = read_related(
        summary=summary,
        root=FLUTTER_SAMPLE,
        module_scope=[],
        task_description="FooPage'e arama çubuğu ekle",
        max_total_bytes=10_000,
    )
    paths = set(out)
    assert "lib/features/foo/foo_page.dart" in paths, (
        f"description match should include foo_page.dart; got {paths}"
    )
    # foo_controller.dart only exports FooController, which isn't in the
    # description — should NOT be picked up by description alone.
    assert "lib/features/foo/foo_controller.dart" not in paths, paths


def test_read_related_import_graph_one_hop() -> None:
    """1-hop import: pulling foo_page.dart should also pull foo_controller.dart."""
    summary = scan_codebase(FLUTTER_SAMPLE)
    out = read_related(
        summary=summary,
        root=FLUTTER_SAMPLE,
        # Direct match only on foo_page; controller arrives via import resolution.
        module_scope=["lib/features/foo/foo_page.dart"],
        task_description="",
        max_total_bytes=10_000,
    )
    paths = set(out)
    assert "lib/features/foo/foo_page.dart" in paths, paths
    assert "lib/features/foo/foo_controller.dart" in paths, (
        f"foo_page imports foo_controller; 1-hop should include it. Got: {paths}"
    )


def test_read_related_respects_byte_budget() -> None:
    """Greedy fill: when budget is tight, smaller files survive but big ones drop."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "src").mkdir()
        # Three files in scope. Sizes pinned to test the greedy logic:
        # big_a (600B) + small (80B) + big_b (600B). Budget 700B.
        (root / "src" / "big_a.py").write_text("x = '" + "a" * 590 + "'\n", encoding="utf-8")
        (root / "src" / "small.py").write_text("def tiny(): pass\n", encoding="utf-8")
        (root / "src" / "big_b.py").write_text("y = '" + "b" * 590 + "'\n", encoding="utf-8")

        summary = scan_codebase(root)
        out = read_related(
            summary=summary,
            root=root,
            module_scope=["src"],
            task_description="",
            max_total_bytes=700,
        )
        # We can fit one big_* (600B) and small.py (~17B) — but never both bigs.
        total = sum(len(v.encode("utf-8")) for v in out.values())
        assert total <= 700, f"byte budget exceeded: {total} > 700"
        assert len(out) >= 1, "expected at least one file under the budget"
        assert len(out) <= 2, f"both 600B files should not fit in 700B budget: {sorted(out)}"
        assert "src/small.py" in out, (
            f"small.py should always fit; got {sorted(out)}"
        )


def test_read_related_skips_stale_entries() -> None:
    """A FileEntry whose file vanished from disk must not appear in output."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "src").mkdir()
        (root / "src" / "real.py").write_text("def real_thing(): pass\n", encoding="utf-8")

        # Build a synthetic summary that pretends a "ghost.py" exists.
        real_entry = FileEntry(
            path="src/real.py",
            size_bytes=24,
            mtime_ns=0,
            sha1="dead" + "0" * 36,
            language="python",
            role="source",
        )
        ghost_entry = FileEntry(
            path="src/ghost.py",
            size_bytes=42,
            mtime_ns=0,
            sha1="ghost" + "0" * 35,
            language="python",
            role="source",
        )
        summary = CodebaseSummary(
            root=str(root.resolve()),
            scanned_at="2026-05-07T00:00:00+00:00",
            file_count=2,
            truncated=False,
            files=[real_entry, ghost_entry],
            modules=[
                ModuleSymbols(path="src/ghost.py", public_names=["GhostThing"]),
            ],
        )

        out = read_related(
            summary=summary,
            root=root,
            module_scope=["src"],
            task_description="",
            max_total_bytes=10_000,
        )
        assert "src/real.py" in out, out
        assert "src/ghost.py" not in out, (
            "ghost.py is in summary but missing on disk; stale skip must apply"
        )


if __name__ == "__main__":
    tests = [
        test_empty_directory_yields_empty_summary,
        test_scans_this_repo_runtime_tree,
        test_flutter_fixture_detected_with_correct_app_class,
        test_max_files_cap_marks_truncated,
        test_gitignored_build_dir_is_excluded,
        test_cache_hit_skips_reparse,
        test_cache_invalidates_only_changed_file,
        test_read_related_picks_files_under_module_scope,
        test_read_related_description_matches_class_names,
        test_read_related_import_graph_one_hop,
        test_read_related_respects_byte_budget,
        test_read_related_skips_stale_entries,
    ]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"PASS  {t.__name__}")
        except Exception as e:
            failed += 1
            print(f"FAIL  {t.__name__}: {e}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
