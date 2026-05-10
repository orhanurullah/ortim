# SPDX-License-Identifier: FSL-1.1-Apache-2.0
# Copyright (c) 2026 ortim.dev
"""Pydantic models for the brownfield codebase reader.

Two consumers feed off these:

  * Architect — uses CodebaseSummary.to_prompt_text() to ground PRD/RFC in
    actual modules and frameworks (no invented `lib/features/imaginary/`).
  * Worker — uses read_related() to pull the *content* of files in a task's
    module_scope; the metadata here drives the cache decision.

Cache invariants:

  * Each FileEntry carries (mtime_ns, size_bytes, sha1). On rescan, mtime+size
    match → skip rehashing; else recompute sha1 and reparse symbols.
  * `last_scan_stats` exposes cache-hit counts so tests can verify
    incremental rescans actually happened.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class FileEntry(BaseModel):
    """One file under the scanned root, post-walk and post-cache resolution."""

    path: str  # POSIX-relative to root
    size_bytes: int
    mtime_ns: int
    sha1: str
    language: str | None = None  # "python","dart","ts","yaml",...
    role: str | None = None  # "source","test","config","doc","build"


class ModuleSymbols(BaseModel):
    """Top-level public symbols for a single source file.

    `path` is the file's POSIX-relative path (matches FileEntry.path).
    `public_names` are language-appropriate top-level identifiers — class /
    function / widget names, underscore-prefixed names excluded.
    `imports` are project-relative or external import targets, used by
    read_related() to compute 1-hop import graphs.
    """

    path: str
    public_names: list[str] = Field(default_factory=list)
    imports: list[str] = Field(default_factory=list)


class FrameworkHint(BaseModel):
    """One framework signal detected in the codebase.

    `confidence` is the fraction of a rule's signals that fired; rules with
    only a manifest hit (no matching code) score lower than rules where both
    manifest and code patterns matched.
    """

    name: str
    confidence: float
    evidence: list[str]
    version: str | None = None


class ScanStats(BaseModel):
    """Diagnostic metrics emitted by every scan_codebase call.

    Surfaced via `ortim inspect <id>` and consumed by tests that need to
    prove cache behavior without resorting to wall-clock timing.
    """

    files_walked: int
    files_parsed_fresh: int
    files_parsed_from_cache: int
    elapsed_ms: int


class CodebaseSummary(BaseModel):
    root: str  # absolute path; useful in audit, not used for IO
    scanned_at: str  # ISO UTC
    file_count: int
    truncated: bool  # True if `max_files` cap was hit
    files: list[FileEntry] = Field(default_factory=list)
    languages: dict[str, int] = Field(default_factory=dict)  # ".py" → count
    frameworks: list[FrameworkHint] = Field(default_factory=list)
    modules: list[ModuleSymbols] = Field(default_factory=list)
    deps_manifests: dict[str, str] = Field(default_factory=dict)  # filename → content
    app_class_hint: str | None = None  # "web" | "mobile" | "desktop" | "mixed"
    last_scan_stats: ScanStats | None = None

    def to_prompt_text(self, max_bytes: int = 2000) -> str:
        """Render a compact summary suitable for injection into Architect/Worker prompts.

        Trims the modules list and dep manifests if needed to stay under
        `max_bytes`. Frameworks are always shown — they are the smallest and
        highest-signal field for tier selection.
        """
        lines: list[str] = []
        lines.append(f"Detected app class hint: {self.app_class_hint or 'unknown'}")
        if self.frameworks:
            fw = ", ".join(
                f"{f.name}@{f.version}" if f.version else f.name
                for f in self.frameworks
            )
            lines.append(f"Frameworks: {fw}")
        lines.append(f"File count: {self.file_count} (truncated: {self.truncated})")
        if self.languages:
            top_langs = sorted(self.languages.items(), key=lambda kv: -kv[1])[:5]
            lines.append(
                "Languages: "
                + ", ".join(f"{ext.lstrip('.')}={n}" for ext, n in top_langs)
            )
        if self.deps_manifests:
            lines.append("Dep manifests: " + ", ".join(sorted(self.deps_manifests)))

        # Module list — newest section, may need truncation.
        module_lines: list[str] = ["Top-level modules:"]
        for mod in self.modules:
            names = ", ".join(mod.public_names[:6])
            if len(mod.public_names) > 6:
                names += ", ..."
            module_lines.append(f"  {mod.path}    ({names})")

        text = "\n".join(lines)
        for ml in module_lines:
            candidate = text + "\n" + ml
            if len(candidate.encode("utf-8")) > max_bytes:
                text = text + "\n  (modules truncated to fit prompt budget)"
                break
            text = candidate
        return text
