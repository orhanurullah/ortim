# SPDX-License-Identifier: FSL-1.1-Apache-2.0
# Copyright (c) 2026 ortim.dev
"""Brownfield codebase reader (M1).

Public surface:

    from runtime.codebase import scan_codebase, CodebaseSummary

The reader walks a workspace, builds a structured summary (files, languages,
frameworks, public symbols), and caches the result for incremental rescans.
"""

from runtime.codebase.baseline import (
    RegressionReport,
    TestBaseline,
    capture as capture_baseline,
    check_regression,
    detect_test_cmd,
    load_baseline,
    parse_test_count,
    write_baseline,
)
from runtime.codebase.reader import read_related, scan_codebase
from runtime.codebase.schema import (
    CodebaseSummary,
    FileEntry,
    FrameworkHint,
    ModuleSymbols,
    ScanStats,
)

__all__ = [
    "CodebaseSummary",
    "FileEntry",
    "FrameworkHint",
    "ModuleSymbols",
    "RegressionReport",
    "ScanStats",
    "TestBaseline",
    "capture_baseline",
    "check_regression",
    "detect_test_cmd",
    "load_baseline",
    "parse_test_count",
    "read_related",
    "scan_codebase",
    "write_baseline",
]
