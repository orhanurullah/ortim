# SPDX-License-Identifier: FSL-1.1-Apache-2.0
# Copyright (c) 2026 ortim.dev
"""Markdown-based knowledge loader.

L1 principles, templates, glossary, and agent system prompts live as
markdown under `<ortim>/_assets/` and are bundled with the wheel. Loader
concatenates files in deterministic alphabetical order.

Pre-0.9.5 the loader was rooted at the repo and read from
`<repo>/agents/`, `<repo>/docs/principles/`, etc. The asset move puts
everything under `_assets/` with no `docs/` prefix.
"""

from __future__ import annotations

from pathlib import Path


class MemoryLoader:
    def __init__(self, assets_root: Path) -> None:
        """`assets_root` is the directory that contains agents/, principles/,
        glossary/, templates/, golden-paths/. In production this is
        `<site-packages>/ortim/_assets/`; in dev installs it is
        `<repo>/ortim/_assets/`.

        Backward-compat shim: pre-0.9.5 callers passed `<repo>` here
        (because docs/ and agents/ lived at the repo root). If we
        detect that shape (no `agents/` immediately under the path,
        but `ortim/_assets/agents/` underneath), silently switch.
        """
        if not (assets_root / "agents").exists() and (
            assets_root / "ortim" / "_assets" / "agents"
        ).exists():
            assets_root = assets_root / "ortim" / "_assets"
        self.assets_root = assets_root

    def _concat_md(self, directory: Path) -> str:
        if not directory.exists():
            return ""
        chunks: list[str] = []
        for md in sorted(directory.glob("*.md")):
            chunks.append(md.read_text(encoding="utf-8"))
        return "\n\n---\n\n".join(chunks)

    def load_l1_principles(self) -> str:
        return self._concat_md(self.assets_root / "principles")

    def load_glossary(self) -> str:
        return self._concat_md(self.assets_root / "glossary")

    def load_template(self, name: str) -> str:
        path = self.assets_root / "templates" / f"{name}.template.md"
        if not path.exists():
            raise FileNotFoundError(f"Template not found: {path}")
        return path.read_text(encoding="utf-8")

    def load_agent_prompt(self, name: str) -> str:
        path = self.assets_root / "agents" / f"{name}.md"
        if not path.exists():
            raise FileNotFoundError(f"Agent prompt not found: {path}")
        return path.read_text(encoding="utf-8")

    def load_tier_doc(self, tier_value: str) -> str:
        """Load the golden-path doc for a Tier.value (e.g. 'T4', 'M1', 'D1').

        Returns empty string if no doc exists — callers must tolerate the
        miss (older tiers may lack docs, and we don't want to crash RFC
        drafting just because someone added a Tier enum without a doc).
        """
        directory = self.assets_root / "golden-paths"
        if not directory.exists():
            return ""
        for md in directory.glob(f"{tier_value}-*.md"):
            return md.read_text(encoding="utf-8")
        return ""
